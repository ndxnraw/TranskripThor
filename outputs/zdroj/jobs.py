"""Checkpoint orchestration around the existing Whisper implementations."""
from dataclasses import asdict
from pathlib import Path

from mixed_language import MixedConfig, MIXED_LANGUAGE, speech_chunks, transcribe_mixed, offset_segment
from project import Project, fingerprint
from speech_models import LocalAdapter, SAMPLE_RATE, hardware_error, checked_segments


def job_settings(model_name, language):
    return dict(pipeline=2, model=model_name, language=language, beam_size=5,
                task='transcribe', word_timestamps=True, condition_on_previous_text=False,
                segmentation=asdict(MixedConfig()))


def segment_data(item):
    return dict(start=item.start, end=item.end, text=item.text.strip(),
        language=getattr(item, 'language', None),
        language_confidence=getattr(item, 'language_confidence', None),
        words=[dict(start=w.start, end=w.end, word=w.word, probability=getattr(w, 'probability', None))
               for w in (getattr(item, 'words', None) or [])], speaker='')


def transcribe_job(model, source, target, settings, stop, emit, resume=False):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    emit('status', 'Príprava zvuku: kontrolujem nahrávku…')
    before = Path(source).stat()
    digest = fingerprint(source, stop)
    with Project(target, create=not resume) as project:
        if resume:
            project.verify(digest, settings)
            if project.get('complete'):
                project.export()
                return True
        emit('status', 'Príprava zvuku: dekódujem a hľadám reč…')
        audio = decode_audio(str(source), sampling_rate=SAMPLE_RATE)
        after = Path(source).stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Zdrojová nahrávka sa počas prípravy zmenila. Spustite nový prepis.')
        if stop.is_set():
            return False
        config = MixedConfig(**settings['segmentation'])
        if resume:
            plan = project.get('plan')
            if len(audio) != project.get('samples'):
                raise ValueError('Zmenila sa dĺžka dekódovaného zvuku. Spustite nový prepis.')
        else:
            spans = get_speech_timestamps(audio, VadOptions(max_speech_duration_s=config.max_speech_segment_duration,
                min_silence_duration_ms=config.min_silence_duration_ms, speech_pad_ms=config.speech_pad_ms))
            plan = list(speech_chunks(spans, len(audio), config))
            project.initialize(source, digest, settings, plan, len(audio))
        language = settings['language']
        previous = project.get('previous_language')
        next_chunk = project.get('next_chunk')
        emit('status', 'Prepisujem reč…')
        emit('progress', 100 * (plan[next_chunk-1][1] / max(1, len(audio))) if next_chunk else 0)
        for index in range(next_chunk, len(plan)):
            if stop.is_set():
                project.export()
                return False
            start, end = plan[index]
            chunk = audio[start:end]
            if language == MIXED_LANGUAGE:
                items, _ = transcribe_mixed(model, None, stop, config, True, audio=chunk,
                    speech_spans=[dict(start=0, end=len(chunk))], previous_language=previous, log_offset=start/SAMPLE_RATE)
            elif isinstance(model, LocalAdapter):
                try:
                    raw = model.infer(chunk)
                except Exception as exc:
                    if model.device == 'cuda' and hardware_error(exc):
                        model.on_cpu()
                        emit('device', 'CPU')
                        raw = model.infer(chunk)
                    else:
                        raise
                items = checked_segments(raw, 0, len(chunk) / SAMPLE_RATE)
            else:
                items, info = model.transcribe(chunk, language=language, task='transcribe',
                    beam_size=5, vad_filter=False, word_timestamps=True, condition_on_previous_text=False)
                detected = info.language
            saved = []
            for item in items:
                if stop.is_set():
                    break
                selected = getattr(item, 'language', language or (detected if not isinstance(model, LocalAdapter) else 'sk'))
                shifted = offset_segment(item, start / SAMPLE_RATE, len(chunk) / SAMPLE_RATE,
                                         selected, getattr(item, 'language_confidence', None))
                if shifted.text.strip():
                    if shifted.end <= shifted.start:
                        raise ValueError('Model vrátil text bez platného časového intervalu.')
                    saved.append(segment_data(shifted))
            if stop.is_set():
                # Entire unfinished chunk is retried. Never checkpoint a partial decoder iterator.
                project.export()
                return False
            if saved:
                previous = saved[-1]['language']
            project.commit_chunk(index, saved, previous)
            for segment in saved:
                emit('segment', segment)
            emit('progress', min(99, end / max(1, len(audio)) * 100))
        project.finish()
        for warning in project.export():
            emit('log', warning)
        emit('progress', 100)
        return True
