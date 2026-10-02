"""Čitateľné titulky. Bez časov slov nikdy nevymýšľať hranice slov."""
import math
import textwrap
from dataclasses import dataclass


@dataclass(frozen=True)
class SubtitleOptions:
    characters: int = 42
    lines: int = 2
    min_duration: float = 1.0
    max_duration: float = 7.0

    def __post_init__(self):
        if not 10 <= self.characters <= 120 or not 1 <= self.lines <= 4 or \
                not 0 < self.min_duration <= self.max_duration <= 30:
            raise ValueError('Titulky: 10–120 znakov, 1–4 riadky a časy 0–30 s (minimum ≤ maximum).')


def timestamp(seconds):
    value = max(0, round(seconds * 1000))
    seconds, ms = divmod(value, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'


def normalized(text):
    return ' '.join(text.split())


def cues(segments, options=None):
    options = options or SubtitleOptions()
    result, warnings = [], set()
    for segment in segments:
        text = normalized(segment['text'])
        if not text:
            continue
        start, end = float(segment['start']), float(segment['end'])
        if not math.isfinite(start + end) or not 0 <= start < end:
            raise ValueError('Neplatný časový interval titulku.')
        words = segment.get('words') or []
        aligned = normalized(' '.join(w.get('word', '') for w in words)) == text
        previous = start
        for word in words:
            a, b = word.get('start', -1), word.get('end', -1)
            if not math.isfinite(a + b) or not previous <= a < b <= end:
                aligned = False
            previous = b
        groups = []
        if aligned and words:
            group = []
            for word in words:
                combined = normalized(' '.join(w['word'] for w in group + [word]))
                full = (len(textwrap.wrap(combined, options.characters)) > options.lines or
                        (group and word['end'] - group[0]['start'] > options.max_duration))
                sentence = group and group[-1]['word'].rstrip().endswith(('.', '!', '?')) and \
                    group[-1]['end'] - group[0]['start'] >= options.min_duration
                if group and (full or sentence):
                    groups.append(dict(start=group[0]['start'], end=group[-1]['end'],
                                       text=normalized(' '.join(w['word'] for w in group))))
                    group = []
                group.append(word)
            if group:
                groups.append(dict(start=group[0]['start'], end=group[-1]['end'],
                                   text=normalized(' '.join(w['word'] for w in group))))
        else:
            groups = [dict(start=start, end=end, text=text)]
            if len(textwrap.wrap(text, options.characters)) > options.lines or end-start > options.max_duration:
                warnings.add('Bez presných časov slov zostal dlhý úsek spolu; limit riadkov/času môže byť prekročený.')
        result.extend(groups)
    for index, cue in enumerate(result):
        if index:
            cue['start'] = max(cue['start'], result[index-1]['end'])
        if cue['start'] >= cue['end'] or round(cue['start']*1000) >= round(cue['end']*1000):
            raise ValueError('Prekrývajúce sa alebo príliš krátke titulky nemožno bezpečne exportovať.')
        next_start = result[index+1]['start'] if index+1 < len(result) else cue['end']
        cue['end'] = min(max(cue['end'], cue['start'] + options.min_duration), max(cue['end'], next_start))
        cue['text'] = '\n'.join(textwrap.wrap(cue['text'], options.characters, break_long_words=False))
        if any(len(line) > options.characters for line in cue['text'].splitlines()):
            warnings.add('Samostatné dlhé slovo prekračuje limit znakov; nebolo rozdelené ani zmenené.')
    return result, sorted(warnings)


def render_srt(segments, options=None):
    items, warnings = cues(segments, options)
    return ''.join(f'{i}\n{timestamp(s["start"])} --> {timestamp(s["end"])}\n{s["text"]}\n\n'
                   for i, s in enumerate(items, 1)), warnings
