"""Lokálny prepis pre Windows. Zvuk neopúšťa počítač."""
import os
import sys
import queue
import time
import threading
from pathlib import Path
from datetime import datetime
from dpi import enable_high_dpi
enable_high_dpi()
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ui import build_ui, update_files
from speech_models import ModelManager, SLOVAK_MODEL, route

os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')

LANGUAGES = {'Slovenčina': 'sk', 'Čeština': 'cs', 'Angličtina': 'en', 'Maďarčina': 'hu', 'Automaticky': None}
MODELS = {'Small – vyvážený': 'small', 'Medium – presnejší, pomalší': 'medium',
          'Large v3 – najvyššia kvalita, náročný': 'large-v3', 'Tiny – rýchly test': 'tiny',
          'KInIT – slovenský Large v3': SLOVAK_MODEL}

def timestamp(seconds):
    ms = max(0, round(seconds * 1000))
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def reserve_output(folder, stem):
    """Každá nahrávka má vlastný priečinok; nikdy neprepíše starší prepis."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    base = stem[:100] + '_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    for n in range(10000):
        target = folder / (base if not n else f'{base}_{n}')
        try:
            target.mkdir()
            return target
        except FileExistsError:
            pass
    raise OSError('Nedá sa vytvoriť jedinečný priečinok prepisu.')

def transcribe_file(model, source, folder, language, stop, emit):
    target = reserve_output(folder, Path(source).stem)
    segments, info = model.transcribe(str(source), language=language, beam_size=5,
                                      vad_filter=True, condition_on_previous_text=False)
    emit('log', f'Rozpoznaný jazyk: {info.language}; trvanie: {info.duration / 60:.1f} min.')
    complete = False
    count = 0
    # Priebežné ukladanie zachová výsledok aj po prerušení alebo chybe.
    with (target / 'prepis.partial.txt').open('w', encoding='utf-8-sig') as txt, \
         (target / 'titulky.partial.srt').open('w', encoding='utf-8-sig') as srt:
        for segment in segments:
            if stop.is_set():
                break
            text = segment.text.strip()
            if text:
                count += 1
                txt.write(text + '\n')
                srt.write(f'{count}\n{timestamp(segment.start)} --> {timestamp(segment.end)}\n{text}\n\n')
                txt.flush()
                srt.flush()
                emit('text', text)
            emit('progress', min(99, 100 * segment.end / max(info.duration, 0.001)))
        else:
            complete = not stop.is_set()
    if complete:
        (target / 'prepis.partial.txt').rename(target / 'prepis.txt')
        (target / 'titulky.partial.srt').rename(target / 'titulky.srt')
        emit('progress', 100)
        if not count:
            emit('log', 'V nahrávke sa nepodarilo rozpoznať reč.')
    return target, complete

class App:
    def __init__(self, root):
        self.root = root
        self.files = []
        self.events = queue.Queue(maxsize=512)
        self.stop = threading.Event()
        self.busy = False
        self.model = None
        self.model_name = None
        self.models = ModelManager()
        build_ui(self, root, LANGUAGES, MODELS, Path.home() / 'Documents' / 'Prepisy', Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LokalnyPrepis' / 'models')

    def add_files(self):
        files = filedialog.askopenfilenames(title='Vyberte zvukové súbory', filetypes=[
            ('Zvuk a video', '*.mp3 *.wav *.m4a *.flac *.ogg *.opus *.aac *.wma *.mp4 *.mkv'), ('Všetky súbory', '*.*')])
        for file in files:
            if file not in self.files:
                self.files.append(file)
                self.listbox.insert('end', file)
        update_files(self)

    def remove_files(self):
        for index in reversed(self.listbox.curselection()):
            del self.files[index]
            self.listbox.delete(index)
        update_files(self)

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output.set(folder)

    def open_results(self):
        folder = Path(self.output.get()).expanduser()
        if folder.is_dir():
            os.startfile(str(folder))
        else:
            messagebox.showinfo('Výsledky', 'Výstupný priečinok ešte neexistuje.')

    def start(self):
        if self.busy:
            return
        if not self.files or not self.output.get().strip():
            messagebox.showinfo('Prepis', 'Pridajte aspoň jednu nahrávku a vyberte výstupný priečinok.')
            return
        try:
            route(LANGUAGES[self.language.get()], MODELS[self.quality.get()])
        except (KeyError, ValueError) as exc:
            messagebox.showinfo('Výber modelu', str(exc))
            return
        self.busy = True
        self.stop.clear()
        for widget in (self.add, self.remove, self.lang_box, self.model_box, self.browse, self.output_entry, self.offline_box, self.start_button):
            widget.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.progress['value'] = 0
        self.percent.set('0 %')
        args = (list(self.files), self.output.get(), LANGUAGES[self.language.get()], MODELS[self.quality.get()], self.offline.get())
        threading.Thread(target=self.work, args=args, daemon=True).start()

    def cancel(self):
        self.stop.set()
        self.status.set('Zastavujem po aktuálnom kroku… rozpracovaný text sa zachová.')
        self.stop_button.configure(state='disabled')

    def work(self, files, folder, language, model_name, offline):
        emit = lambda kind, value: self.events.put((kind, value))
        done = failed = 0
        try:
            self.model = None
            self.model = self.models.get(language, model_name, self.cache, offline, emit, self.stop)
            self.model_name = model_name
            for i, file in enumerate(files, 1):
                if self.stop.is_set():
                    break
                emit('status', f'{i}/{len(files)} • {Path(file).name}')
                emit('progress', 0)
                emit('log', '\n' + Path(file).name)
                try:
                    target, complete = transcribe_file(self.model, file, folder, language, self.stop, emit)
                    done += int(complete)
                    emit('log', f'{"Uložené" if complete else "Čiastočný prepis"}: {target}')
                except Exception as exc:
                    failed += 1
                    emit('log', f'Chyba súboru {Path(file).name}: {exc}')
            emit('status', f'{"Zastavené" if self.stop.is_set() else "Dokončené"}. Hotové: {done}/{len(files)}. Chyby: {failed}.')
        except InterruptedError:
            emit('status', 'Načítanie prerušené.')
        except Exception as exc:
            emit('status', 'Prepis sa nepodarilo spustiť.')
            emit('error', str(exc) + '\n\nPri prvom použití povoľte stiahnutie modelu (vypnite „Iba offline“). Skontrolujte internet a voľné miesto. Pri nedostatku pamäte vyberte menší model.')
        finally:
            emit('finished', None)

    def poll(self):
        # Zlučovanie udalostí: najviac jeden zápis do každého poľa na dávku.
        preview, activity, errors = [], [], []
        latest_status = latest_progress = None
        finished = False
        deadline = time.perf_counter() + 0.004
        for _ in range(200):
            if time.perf_counter() >= deadline:
                break
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'status':
                latest_status = value
            elif kind == 'progress':
                latest_progress = value
            elif kind in ('text', 'log'):
                preview.append(value)
                if kind == 'log':
                    activity.append(value)
            elif kind == 'error':
                errors.append(value)
            elif kind == 'finished':
                finished = True
        if latest_status is not None and self.status.get() != latest_status:
            self.status.set(latest_status)
        if latest_progress is not None:
            self.progress['value'] = latest_progress
            self.percent.set(f'{int(latest_progress)} %')
        for widget, lines in ((self.preview, preview), (self.activity, activity)):
            if not lines:
                continue
            follow = widget.yview()[1] >= 0.99
            widget.configure(state='normal')
            widget.insert('end', '\n'.join(lines) + '\n')
            line_count = int(widget.index('end-1c').split('.')[0])
            if line_count > 1200:
                widget.delete('1.0', f'{line_count - 1200 + 1}.0')
            if follow:
                widget.see('end')
            widget.configure(state='disabled')
        if finished:
            self.busy = False
            for widget in (self.add, self.remove, self.browse, self.output_entry, self.offline_box, self.start_button):
                widget.configure(state='normal')
            self.lang_box.configure(state='readonly')
            self.model_box.configure(state='readonly')
            self.stop_button.configure(state='disabled')
        for error in errors:
            messagebox.showerror('Chyba prepisu', error)
        self.root.after(50 if self.busy or not self.events.empty() else 250, self.poll)

    def close(self):
        if self.busy:
            self.cancel()
            messagebox.showinfo('Prebieha prepis', 'Počkajte na zastavenie aktuálneho kroku a potom okno zatvorte. Rozpracovaný text sa priebežne ukladá.')
        else:
            self.root.destroy()

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    if len(sys.argv) == 5 and sys.argv[1] in ('--self-test', '--self-test-sk', '--self-test-hu'):
        # Diagnostika zostaveného EXE: lokálny model, zvuk a výstupný priečinok.
        import traceback
        folder = Path(sys.argv[4])
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if sys.argv[1] == '--self-test-sk':
                from speech_models import load_backend, SLOVAK_MODEL
                model = ModelManager().get('sk', SLOVAK_MODEL, sys.argv[2], True, lambda *a: None, threading.Event())
                language = 'sk'
            else:
                from faster_whisper import WhisperModel
                model = WhisperModel(sys.argv[2], device='cpu', compute_type='int8', local_files_only=True)
                language = 'hu' if sys.argv[1] == '--self-test-hu' else 'en'
            target, complete = transcribe_file(model, sys.argv[3], folder, language, threading.Event(), lambda *a: None)
            if not complete or not (target / 'prepis.txt').read_text(encoding='utf-8-sig').strip():
                raise RuntimeError('Diagnostický prepis je prázdny alebo neúplný.')
            root = tk.Tk()
            root.withdraw()
            app = App(root)
            root.update()
            root.destroy()
            (folder / 'diagnostika.txt').write_text(f'OK: {complete}\n{target}', encoding='utf-8')
        except Exception:
            (folder / 'diagnostika.txt').write_text(traceback.format_exc(), encoding='utf-8')
            sys.exit(1)
    else:
        root = tk.Tk()
        app = App(root)
        root.mainloop()
