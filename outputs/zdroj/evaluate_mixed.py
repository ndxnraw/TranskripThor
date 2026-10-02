"""Offline evaluation on user-authorized, manually reviewed recordings."""
import argparse
import json
import re
import threading
import time
from pathlib import Path
from mixed_language import transcribe_mixed
from speech_models import ModelManager
from state import atomic_text


def tokens(text):
    return re.findall(r'\w+', text.casefold(), flags=re.UNICODE)


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis)+1))
    for i, token in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(token != other)))
        previous = current
    return previous[-1]


def metrics(reference, hypothesis, seconds, duration):
    ref = tokens(' '.join(s['text'] for s in reference))
    hyp = tokens(' '.join(s['text'] for s in hypothesis))
    correct = total = 0.0
    for segment in reference:
        length = segment['end'] - segment['start']
        if length <= 0 or segment['language'] not in ('cs','sk'):
            raise ValueError('Referencia musí mať platné intervaly a jazyk cs/sk.')
        total += length
        intervals = sorted((max(segment['start'], candidate['start']), min(segment['end'], candidate['end']))
                           for candidate in hypothesis if candidate['language'] == segment['language'])
        last = segment['start']
        for start, end in intervals:
            correct += max(0, end - max(start,last))
            last = max(last,end)
    return dict(wer=distance(ref,hyp)/max(1,len(ref)), reference_words=len(ref),
                language_time_accuracy=correct/max(.001,total), processing_seconds=seconds,
                audio_seconds=duration, real_time_factor=seconds/max(.001,duration))


def main():
    parser = argparse.ArgumentParser(description='Lokálne vyhodnotenie CZ/SK. Žiadne nahrávky sa neodosielajú.')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--models', nargs='+', default=['small'])
    parser.add_argument('--output', type=Path, default=Path('vyhodnotenie.json'))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if not manifest.get('recordings'):
        raise ValueError('Chýbajú reálne nahrávky. Doplňte eval/manifest.example.json podľa návodu.')
    manager, results = ModelManager(), []
    for model_name in args.models:
        if model_name not in ('tiny','small','medium','large-v3'):
            raise ValueError('Zmiešaný režim vyžaduje viacjazyčný Whisper.')
        started = time.perf_counter()
        model = manager.get('cs-sk', model_name, args.cache, True, lambda *a: None, threading.Event())
        load_seconds = time.perf_counter() - started
        for recording in manifest['recordings']:
            if recording.get('kind') != 'real' or not recording.get('authorized') or not recording.get('reviewed_by'):
                raise ValueError('Reálne meranie vyžaduje oprávnenie, kind=real a meno kontrolóra referencie.')
            source = (args.manifest.parent/recording['audio']).resolve()
            started = time.perf_counter()
            segments, info = transcribe_mixed(model, str(source), threading.Event(), word_timestamps=True)
            hypothesis = [dict(start=s.start,end=s.end,text=s.text,language=s.language,
                               language_confidence=s.language_confidence) for s in segments]
            elapsed = time.perf_counter()-started
            results.append(dict(id=recording['id'], model=model_name, kind='real', tags=recording.get('tags',[]),
                load_seconds=load_seconds, metrics=metrics(recording['segments'],hypothesis,elapsed,info.duration),
                hypothesis=hypothesis))
            atomic_text(args.output, json.dumps(results,ensure_ascii=False,indent=2))
    manager.close()
    print(f'Lokálne merania uložené: {args.output}')


if __name__ == '__main__':
    main()
