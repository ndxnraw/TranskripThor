"""Lokálne modely s rovnakým segmentovým rozhraním ako faster-whisper."""
import gc
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

SLOVAK_MODEL = 'kinit/whisper-large-v3-sk'
SAMPLE_RATE = 16000

def route(language, selected):
    if selected == SLOVAK_MODEL and language != 'sk':
        raise ValueError('Model KInIT je určený iba pre slovenčinu. Vyberte Slovenčina alebo iný model.')
    return selected

def device(model_id=SLOVAK_MODEL):
    if model_id != SLOVAK_MODEL:
        try:
            import ctranslate2
            return 'cuda' if ctranslate2.get_cuda_device_count() else 'cpu'
        except (ImportError, OSError, RuntimeError):
            return 'cpu'
    try:
        import torch
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    except (ImportError, OSError):
        return 'cpu'

def hardware_error(exc):
    return isinstance(exc, MemoryError) or any(word in str(exc).lower() for word in
        ('out of memory', 'cuda', 'cudnn', 'cublas', 'allocation', 'not compiled with'))

def release_memory():
    gc.collect()
    try:
        torch = sys.modules.get('torch')
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except (ImportError, OSError, RuntimeError):
        pass

def checked_segments(items, offset, duration):
    """Neodhadovať chýbajúce časové značky; chybu ponechať viditeľnú."""
    result = []
    last = 0.0
    for item in items:
        text = str(item['text']).strip()
        if not text:
            continue
        start, end = item['start'], item['end']
        if start is None or end is None:
            raise RuntimeError('Model nevrátil úplné časové značky. Skúste záložný Whisper.')
        start, end = float(start), float(end)
        if not math.isfinite(start + end) or start < 0 or end < start or start < last:
            raise RuntimeError('Model vrátil neplatné časové značky.')
        start, end = min(start, duration), min(end, duration)
        last = start
        words = checked_segments(item.get('words', []), offset, duration)
        for word in words:
            word.word = word.text
        result.append(SimpleNamespace(start=offset + start, end=offset + end, text=text, words=words))
    return result

class LocalAdapter:
    def __init__(self, model_id, cache, offline, selected_device, emit, stop):
        self.model_id = model_id
        self.cache = Path(cache)
        self.offline = offline
        self.device = selected_device
        self.emit = emit
        self.stop = stop
        self.model = self.processor = self.pipe = None
        self.load()

    def close(self):
        self.pipe = self.model = self.processor = None

    def on_cpu(self):
        self.emit('log', f'{self.model_id}: GPU nie je dostupné alebo nemá dosť pamäte; skúšam CPU.')
        self.close()
        release_memory()
        self.device = 'cpu'
        self.load()

    def transcribe(self, source, language=None, **kwargs):
        # Rovnaké PyAV dekódovanie, mono 16 kHz a Silero VAD ako pôvodný engine.
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        audio = decode_audio(source, sampling_rate=SAMPLE_RATE)
        duration = len(audio) / SAMPLE_RATE
        def generate():
            if self.stop.is_set() or not len(audio):
                return
            spans = get_speech_timestamps(audio, VadOptions(max_speech_duration_s=28, speech_pad_ms=200))
            for span in spans:
                # Pevná horná hranica aj pri zmene implementácie VAD.
                for start in range(span['start'], span['end'], 28 * SAMPLE_RATE):
                    if self.stop.is_set():
                        return
                    end = min(span['end'], start + 28 * SAMPLE_RATE)
                    chunk = audio[start:end]
                    try:
                        items = self.infer(chunk)
                    except Exception as exc:
                        if self.device == 'cuda' and hardware_error(exc):
                            self.on_cpu()
                            items = self.infer(chunk)
                        else:
                            raise RuntimeError(f'{self.model_id}: prepis zlyhal ({exc}). '
                                'Pri nedostatku pamäte vyberte menší model v ponuke.') from exc
                    # Výsledok celého kroku sa overí pred emitovaním: žiadne duplikáty pri GPU retry.
                    for segment in checked_segments(items, start / SAMPLE_RATE, len(chunk) / SAMPLE_RATE):
                        if self.stop.is_set():
                            return
                        yield segment
        return generate(), SimpleNamespace(language=language, duration=duration)

class SlovakWhisper(LocalAdapter):
    def load(self):
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
        hub = str(self.cache / 'huggingface')
        opts = dict(cache_dir=hub, local_files_only=self.offline, trust_remote_code=False)
        source = self.model_id
        opts['revision'] = 'v2.0'
        if self.device == 'cpu':
            torch.set_num_threads(max(1, min(4, (os.cpu_count() or 2) - 1)))
        self.processor = AutoProcessor.from_pretrained(source, **opts)
        dtype = torch.float16 if self.device == 'cuda' else torch.float32
        self.model = AutoModelForSpeechSeq2Seq.from_pretrained(
            source, torch_dtype=dtype, use_safetensors=True,
            attn_implementation='eager', **opts).to(self.device).eval()
        self.pipe = pipeline('automatic-speech-recognition', model=self.model,
            tokenizer=self.processor.tokenizer, feature_extractor=self.processor.feature_extractor,
            device=0 if self.device == 'cuda' else -1, torch_dtype=dtype)

    def infer(self, audio):
        import torch
        with torch.inference_mode():
            result = self.pipe({'raw': audio, 'sampling_rate': SAMPLE_RATE},
                return_timestamps='word', generate_kwargs={'language': 'sk', 'task': 'transcribe'})
        if result.get('text', '').strip() and not result.get('chunks'):
            raise RuntimeError('Whisper nevrátil časové značky.')
        # Word alignment supplies the final boundary even when the decoder omits
        # its closing segment token. Group words without inventing timestamps.
        words = [dict(text=item['text'], start=item['timestamp'][0], end=item['timestamp'][1])
                 for item in result.get('chunks', [])]
        checked_segments(words, 0, len(audio) / SAMPLE_RATE)
        segments = []
        for word in words:
            text = word['text'].strip()
            if not text:
                continue
            if not segments or segments[-1]['text'].endswith(('.', '?', '!')) or \
                    word['end'] - segments[-1]['start'] > 7:
                segments.append(dict(text=text, start=word['start'], end=word['end'], words=[word]))
            else:
                segments[-1]['text'] += ' ' + text
                segments[-1]['end'] = word['end']
                segments[-1]['words'].append(word)
        return segments

def load_backend(model_id, cache, offline, selected_device, emit, stop):
    cls = {SLOVAK_MODEL: SlovakWhisper}.get(model_id)
    if cls:
        # Oddeliť konštrukciu od load(), aby bolo možné uvoľniť aj čiastočne načítané modely.
        adapter = cls.__new__(cls)
        try:
            cls.__init__(adapter, model_id, cache, offline, selected_device, emit, stop)
            return adapter
        except Exception:
            adapter.close()
            raise
    from faster_whisper import WhisperModel
    return WhisperModel(model_id, device=selected_device,
        compute_type='float16' if selected_device == 'cuda' else 'int8',
        download_root=str(cache), local_files_only=offline)

class ModelManager:
    """Jeden aktívny model: opätovné použitie medzi súbormi, obmedzená RAM/VRAM."""
    def __init__(self):
        self.model = self.key = None

    def get(self, language, selected_model, cache, offline, emit, stop):
        requested = route(language, selected_model)
        if stop.is_set():
            raise InterruptedError('Načítanie prerušené.')
        # Jazyk nemení váhy viacjazyčného Whisperu; nevyžaduje opätovné načítanie.
        key = (requested, str(Path(cache).resolve()))
        if key == self.key and self.model is not None:
            if isinstance(self.model, LocalAdapter):
                self.model.stop, self.model.emit = stop, emit
            return self.model
        self.close()
        errors = []
        selected = device(requested)
        for target in ([selected, 'cpu'] if selected == 'cuda' else ['cpu']):
            try:
                emit('status', f'Načítavam model {requested} ({target}) do pamäte…')
                model = load_backend(requested, cache, offline, target, emit, stop)
                if stop.is_set():
                    if isinstance(model, LocalAdapter):
                        model.close()
                    del model
                    release_memory()
                    raise InterruptedError('Načítanie prerušené.')
                self.model, self.key = model, key
                emit('log', f'Aktívny model: {requested}; zariadenie: {target}.')
                return model
            except InterruptedError:
                raise
            except Exception as exc:
                errors.append(f'{requested} ({target}): {exc}')
                emit('log', errors[-1])
                release_memory()
                if stop.is_set():
                    raise InterruptedError('Načítanie prerušené.') from exc
                if target != 'cuda' or not hardware_error(exc):
                    break
        raise RuntimeError('Vybraný model sa nepodarilo načítať. Skontrolujte cache a RAM/VRAM. '
            'V režime Iba offline musí byť model už stiahnutý. Môžete vybrať menší model.\n' + '\n'.join(errors))

    def close(self):
        if isinstance(self.model, LocalAdapter):
            self.model.close()
        self.model = self.key = None
        release_memory()
