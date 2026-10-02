"""Local audio playback with seek/pause; decoding stays off the Tk thread."""
import threading
from speech_models import SAMPLE_RATE


class Player:
    def __init__(self):
        self.audio = None
        self.position = 0
        self.limit = 0
        self.stream = None
        self.lock = threading.Lock()
        self.closed = False

    def load(self, source):
        from faster_whisper.audio import decode_audio
        audio = decode_audio(str(source), sampling_rate=SAMPLE_RATE)
        with self.lock:
            if not self.closed:
                self.audio = audio
                self.position, self.limit = 0, len(audio)
        return len(audio) / SAMPLE_RATE

    def play(self, start=None, end=None):
        import sounddevice as sd
        self.pause()
        if self.audio is None:
            raise ValueError('Zvuk sa ešte pripravuje.')
        with self.lock:
            if start is not None:
                self.position = min(len(self.audio), max(0, round(start * SAMPLE_RATE)))
            self.limit = min(len(self.audio), round(end * SAMPLE_RATE)) if end is not None else len(self.audio)
        def callback(outdata, frames, timing, status):
            with self.lock:
                count = max(0, min(frames, self.limit - self.position))
                outdata.fill(0)
                outdata[:count, 0] = self.audio[self.position:self.position + count]
                self.position += count
                if count < frames:
                    raise sd.CallbackStop
        self.stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32', callback=callback)
        self.stream.start()

    def pause(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def close(self):
        self.pause()
        with self.lock:
            self.closed = True
            self.audio = None
