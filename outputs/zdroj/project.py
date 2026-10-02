"""Transactional checkpoint per complete audio chunk; editable full transcript."""
import hashlib
import json
import sqlite3
from pathlib import Path
from state import atomic_text
from subtitles import render_srt


def fingerprint(source, stop=None):
    path = Path(source)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            if stop and stop.is_set():
                raise InterruptedError('Kontrola nahrávky prerušená.')
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Nahrávka sa počas čítania zmenila.')
    return dict(size=after.st_size, sha256=digest.hexdigest())


class Project:
    def __init__(self, folder, create=False):
        self.folder = Path(folder)
        if create:
            self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / 'projekt.sqlite3'
        if not create and not path.is_file():
            raise ValueError('Chýba projekt.sqlite3. Starší TXT/SRT nemá bezpečný bod pokračovania.')
        self.db = sqlite3.connect(path, timeout=15)
        self.db.execute('PRAGMA synchronous=FULL')
        if create:
            with self.db:
                self.db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                self.db.execute('CREATE TABLE IF NOT EXISTS segments (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO metadata VALUES (?, ?)', (key, json.dumps(value, ensure_ascii=False)))

    def initialize(self, source, digest, settings, plan, samples):
        with self.db:
            for key, value in dict(schema=1, source=str(Path(source).resolve()), fingerprint=digest,
                settings=settings, plan=plan, samples=samples, next_chunk=0, complete=False).items():
                self.put(key, value)

    def verify(self, digest, settings):
        if self.get('schema') != 1 or self.get('fingerprint') != digest:
            raise ValueError('Nahrávka sa nezhoduje s uloženým projektom. Spustite nový prepis.')
        if self.get('settings') != settings:
            raise ValueError('Model, jazyk alebo nastavenia sa zmenili. Obnovte pôvodné nastavenia alebo spustite nový prepis.')

    def segments(self):
        return [dict(json.loads(data), id=identifier) for identifier, data in
                self.db.execute('SELECT id, data FROM segments ORDER BY id')]

    def commit_chunk(self, index, segments, previous_language):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.get('next_chunk') != index:
                raise ValueError('Neplatný bod pokračovania; úsek už bol uložený alebo preskočený.')
            identifier = self.db.execute('SELECT COALESCE(MAX(id), -1)+1 FROM segments').fetchone()[0]
            for segment in segments:
                self.db.execute('INSERT INTO segments VALUES (?, ?)',
                                (identifier, json.dumps(segment, ensure_ascii=False)))
                identifier += 1
            self.put('next_chunk', index + 1)
            self.put('previous_language', previous_language)

    def edit(self, segments):
        with self.db:
            for segment in segments:
                self.db.execute('UPDATE segments SET data=? WHERE id=?',
                                (json.dumps(segment, ensure_ascii=False), segment['id']))

    def finish(self):
        with self.db:
            self.put('complete', True)

    def export(self, options=None, corrected=False):
        segments = self.segments()
        srt, warnings = render_srt(segments, options)
        suffix = '.opravene' if corrected else ('' if self.get('complete') else '.partial')
        # Database is authoritative. Interrupted exports can always be regenerated.
        atomic_text(self.folder / f'prepis{suffix}.txt', ''.join(s['text'].strip()+'\n' for s in segments if s['text'].strip()), 'utf-8-sig')
        atomic_text(self.folder / f'titulky{suffix}.srt', srt, 'utf-8-sig')
        return warnings
