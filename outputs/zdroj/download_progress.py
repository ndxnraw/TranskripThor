"""Honest download heartbeat based on physical Hugging Face cache writes."""
import threading
import time
from itertools import chain


def cache_bytes(folder):
    # Windows without symlink privileges moves completed blobs into snapshots.
    # Count both locations, deduplicating snapshot links on other installations.
    total, seen = 0, set()
    for path in chain((folder / 'blobs').glob('*'), (folder / 'snapshots').rglob('*')):
        try:
            resolved = path.resolve()
            if resolved not in seen and path.is_file():
                total += path.stat().st_size
                seen.add(resolved)
        except OSError:
            pass  # Concurrent rename; the next sample will see the destination.
    return total


def size_text(value):
    return f'{value/1024**3:.2f} GB' if value >= 1024**3 else f'{value/1024**2:.1f} MB'


class DownloadMonitor:
    def __init__(self, folder, model, emit, stop, clock=time.monotonic):
        self.folder, self.model, self.emit, self.stop, self.clock = folder, model, emit, stop, clock
        self.initial = self.previous = cache_bytes(folder)
        self.started = self.last_sample = self.last_change = clock()
        self.files = ''
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.thread = None

    def file_count(self, count, total):
        with self.lock:
            self.files = f' • hotové súbory {count:g}/{total:g}' if total else ''

    def report(self):
        now = self.clock()
        current = cache_bytes(self.folder)
        advance = max(0, current-self.previous)
        speed = advance/max(now-self.last_sample, 0.001)
        if advance:
            self.last_change = now
        idle = int(now-self.last_change)
        self.previous, self.last_sample = current, now
        with self.lock:
            files = self.files
        if self.stop.is_set():
            detail = 'Zastavujem; čakám na ukončenie aktuálneho prenosu. Dáta v cache zostávajú.'
        elif advance:
            detail = f'Zápis {size_text(speed)}/s'
        else:
            detail = f'Bez nových dát {idle} s; čakám na server, sieť alebo prípravu súboru.'
        self.emit('status', f'Sťahujem {self.model}{files}\nCache: {size_text(current)} (+{size_text(max(0,current-self.initial))} od spustenia) • {detail}')

    def __enter__(self):
        self.emit('download_state', True)
        self.report()
        def run():
            while not self.done.wait(1):
                self.report()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.done.set()
        self.thread.join()
        self.emit('download_state', False)
