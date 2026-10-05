"""Atómové nastavenia a fronta; žiadne údaje neopúšťajú počítač."""
import json
import os
import re
import uuid
from pathlib import Path

STATES = ('čaká', 'spracúva sa', 'hotovo', 'prerušené', 'chyba')


def atomic_text(path, text, encoding='utf-8'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding=encoding) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class StateStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.warning = ''

    def read(self, name, default):
        path = self.folder / name
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            self.warning = f'Súbor {name} sa nepodarilo načítať. Použité sú predvolené hodnoty.'
            # Preserve evidence rather than overwriting a damaged file on exit.
            if path.exists():
                try:
                    path.rename(path.with_name(path.name + '.damaged-' + uuid.uuid4().hex[:8]))
                except OSError:
                    pass
            return default

    def save(self, name, value):
        atomic_text(self.folder / name, json.dumps(value, ensure_ascii=False, indent=2))

    def settings(self, languages, models):
        raw = self.read('settings.json', {})
        raw = raw if isinstance(raw, dict) else {}
        result = {}
        for key, choices in [('language', languages), ('model', models), ('theme', ('light', 'dark'))]:
            if isinstance(raw.get(key), str) and raw[key] in choices:
                result[key] = raw[key]
        for key in ('offline', 'autoplay'):
            if isinstance(raw.get(key), bool):
                result[key] = raw[key]
        if isinstance(raw.get('output'), str) and raw['output'].strip():
            result['output'] = raw['output']
        if isinstance(raw.get('geometry'), str) and re.fullmatch(r'\d{3,5}x\d{3,5}(?:[+-]\d+[+-]\d+)?', raw['geometry']):
            result['geometry'] = raw['geometry']
        return result

    def queue(self):
        raw = self.read('queue.json', [])
        result, ids = [], set()
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get('source'), str):
                continue
            identifier = item.get('id')
            if not isinstance(identifier, str) or identifier in ids:
                identifier = uuid.uuid4().hex
            ids.add(identifier)
            status = item.get('state', 'čaká')
            if status == 'spracúva sa':
                status = 'prerušené'
            result.append(dict(id=identifier, source=item['source'],
                state=status if status in STATES else 'čaká',
                project=item.get('project') if isinstance(item.get('project'), str) else '',
                error=item.get('error') if isinstance(item.get('error'), str) else ''))
        return result


def queue_item(source):
    return dict(id=uuid.uuid4().hex, source=str(Path(source).resolve()), state='čaká', project='', error='')


class ProgressClock:
    """ETA only after measurable work; loading/download time is excluded."""
    def __init__(self, now):
        self.started = now
        self.samples = []

    def update(self, fraction, now):
        if not self.samples or fraction > self.samples[-1][1]:
            self.samples.append((now, fraction))
            self.samples = self.samples[-50:]

    def remaining(self, now):
        if len(self.samples) < 3:
            return None
        elapsed = self.samples[-1][0] - self.samples[0][0]
        advance = self.samples[-1][1] - self.samples[0][1]
        if elapsed < 10 or advance < 0.02:
            return None
        return max(0, (1 - self.samples[-1][1]) * elapsed / advance - (now - self.samples[-1][0]))
