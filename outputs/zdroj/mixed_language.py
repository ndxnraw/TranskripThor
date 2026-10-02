"""CZ/SK režim nad existujúcou inštanciou faster-whisper, bez ďalších váh."""
import logging
import math
from copy import copy
from dataclasses import dataclass
from types import SimpleNamespace

from speech_models import SAMPLE_RATE

MIXED_LANGUAGE = 'cs-sk'
SUPPORTED_TRANSCRIPTION_LANGUAGES = ('cs', 'sk')
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MixedConfig:
    language_confidence_threshold: float = 0.60
    language_difference_threshold: float = 0.15
    min_speech_segment_duration: float = 5.0
    max_speech_segment_duration: float = 25.0
    merge_gap_duration: float = 0.5
    min_silence_duration_ms: int = 400
    speech_pad_ms: int = 200
    score_tie_threshold: float = 0.03

    def __post_init__(self):
        for value in vars(self).values():
            if not math.isfinite(value) or value < 0:
                raise ValueError('Prahy CZ/SK musia byť konečné nezáporné čísla.')
        if not 0 < self.min_speech_segment_duration <= self.max_speech_segment_duration <= 30:
            raise ValueError('Dĺžka CZ/SK úsekov musí byť v rozsahu (0, 30] sekúnd.')
        if max(self.language_confidence_threshold, self.language_difference_threshold) > 1:
            raise ValueError('Pravdepodobnostné prahy musia byť najviac 1.')


def speech_chunks(spans, audio_length, config):
    """Zachovať pôvodnú časovú os; krátke úseky spájať iba cez krátke pauzy.

    Padding VAD sa neprekrýva. Dlhé úseky delíme rovnomerne, bez krátkeho
    zvyšku a bez overlapu, ktorý by produkoval duplicitné slová.
    """
    minimum = round(config.min_speech_segment_duration * SAMPLE_RATE)
    maximum = round(config.max_speech_segment_duration * SAMPLE_RATE)
    gap = round(config.merge_gap_duration * SAMPLE_RATE)
    groups = []
    for span in spans:
        start, end = max(0, int(span['start'])), min(audio_length, int(span['end']))
        if groups:
            start = max(start, groups[-1][1])
        if end <= start:
            continue
        if groups and start - groups[-1][1] <= gap and \
                (groups[-1][1] - groups[-1][0] < minimum or end - start < minimum) and \
                end - groups[-1][0] <= maximum:
            groups[-1] = (groups[-1][0], end)
        else:
            groups.append((start, end))
    for start, end in groups:
        count = math.ceil((end - start) / maximum)
        for index in range(count):
            yield (start + (end - start) * index // count,
                   start + (end - start) * (index + 1) // count)


def transcription_score(segments):
    # Token-weighted mean: segment splitting must not determine the winner.
    total = weight = 0
    for segment in segments:
        score = getattr(segment, 'avg_logprob', float('-inf'))
        if segment.text.strip() and math.isfinite(score):
            size = max(1, len(getattr(segment, 'tokens', [])))
            total += score * size
            weight += size
    return total / weight if weight else float('-inf')


def offset_segment(segment, offset, duration, language, confidence):
    result = copy(segment)
    def bounds(item):
        if not math.isfinite(item.start + item.end) or not 0 <= item.start <= item.end:
            raise RuntimeError('Whisper vrátil neplatné časové značky.')
        return offset + min(item.start, duration), offset + min(item.end, duration)
    result.start, result.end = bounds(segment)
    result.language, result.language_confidence = language, confidence
    if getattr(segment, 'words', None) is not None:
        result.words = []
        for word in segment.words:
            shifted = copy(word)
            shifted.start, shifted.end = bounds(word)
            result.words.append(shifted)
    return result


def transcribe_mixed(model, source, stop, config=None, word_timestamps=False,
                     audio=None, speech_spans=None, previous_language=None, log_offset=0):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    config = config or MixedConfig()
    if not callable(getattr(model, 'detect_language', None)):
        raise ValueError('Pre režim Čeština + slovenčina vyberte viacjazyčný Whisper model.')
    if audio is None:
        audio = decode_audio(source, sampling_rate=SAMPLE_RATE)
    duration = len(audio) / SAMPLE_RATE

    def generate():
        if stop.is_set() or not len(audio):
            return
        spans = speech_spans if speech_spans is not None else get_speech_timestamps(audio, VadOptions(
            max_speech_duration_s=config.max_speech_segment_duration,
            min_silence_duration_ms=config.min_silence_duration_ms,
            speech_pad_ms=config.speech_pad_ms))
        previous = previous_language
        identifier = 0
        for start, end in speech_chunks(spans, len(audio), config):
            if stop.is_set():
                return
            chunk = audio[start:end]  # numpy view; no temporary WAV or full copy
            _, _, probabilities = model.detect_language(audio=chunk, vad_filter=False)
            probabilities = dict(probabilities)
            probs = {lang: float(probabilities.get(lang, 0)) for lang in SUPPORTED_TRANSCRIPTION_LANGUAGES}
            if any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values()):
                raise RuntimeError('Whisper vrátil neplatné pravdepodobnosti jazykov.')
            language = max(probs, key=probs.get)
            ambiguous = (probs[language] < config.language_confidence_threshold or
                         abs(probs['cs'] - probs['sk']) < config.language_difference_threshold)
            candidates = {}
            for candidate in (SUPPORTED_TRANSCRIPTION_LANGUAGES if ambiguous else (language,)):
                if stop.is_set():
                    return
                items, _ = model.transcribe(chunk, language=candidate, task='transcribe',
                    beam_size=5, vad_filter=False, condition_on_previous_text=False,
                    word_timestamps=word_timestamps)
                candidates[candidate] = []
                for item in items:
                    if stop.is_set():
                        return
                    candidates[candidate].append(item)
            if ambiguous:
                scores = {lang: transcription_score(items) for lang, items in candidates.items()}
                logger.debug('[ASR] Ambiguous language: cs=%.3f sk=%.3f; testing both languages',
                             probs['cs'], probs['sk'])
                # Only a short, acoustically ambiguous, nearly tied chunk can
                # inherit the previous language. Clear evidence always wins.
                tied = scores['cs'] == scores['sk'] or \
                    abs(scores['cs'] - scores['sk']) <= config.score_tie_threshold
                if tied:
                    if previous and (end - start) / SAMPLE_RATE <= config.min_speech_segment_duration and \
                            abs(probs['cs'] - probs['sk']) < config.language_difference_threshold:
                        language = previous
                else:
                    language = max(scores, key=scores.get)
                logger.debug('[ASR] Selected %s based on transcription confidence: %s', language, scores)
            confidence = probs[language]
            logger.debug('[ASR] %.2f - %.2f | %s | confidence=%.3f',
                         log_offset + start / SAMPLE_RATE, log_offset + end / SAMPLE_RATE, language, confidence)
            for item in candidates[language]:
                if stop.is_set():
                    return
                result = offset_segment(item, start / SAMPLE_RATE, len(chunk) / SAMPLE_RATE,
                                        language, confidence)
                result.id = identifier
                identifier += 1
                yield result
            if any(item.text.strip() for item in candidates[language]):
                previous = language

    return generate(), SimpleNamespace(language=MIXED_LANGUAGE, duration=duration)
