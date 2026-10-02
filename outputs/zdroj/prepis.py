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
from mixed_language import MIXED_LANGUAGE, transcribe_mixed
from state import StateStore, queue_item, ProgressClock
from jobs import job_settings, transcribe_job
from project import Project

os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')

LANGUAGES = {'Slovenčina': 'sk', 'Čeština': 'cs', 'Čeština + slovenčina': MIXED_LANGUAGE,
             'Angličtina': 'en', 'Maďarčina': 'hu', 'Automaticky': None}
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
    if language == MIXED_LANGUAGE:
        segments, info = transcribe_mixed(model, str(source), stop)
    else:
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
    def __init__(self, root, state_dir=None):
        self.root = root
        show_on_ready = root.state() != 'withdrawn'
        root.withdraw()
        self.store = StateStore(state_dir or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LokalnyPrepis')
        self.items = self.store.queue()
        self.editors = []
        self.model_dialog = None
        self.persist_timer = None
        self.batch_ids = []
        self.batch_index = 0
        self.file_progress = 0
        self.clock = None
        self.batch_mode = 'pending'
        self.events = queue.Queue(maxsize=512)
        self.stop = threading.Event()
        self.busy = False
        self.model = None
        self.model_name = None
        self.models = ModelManager()
        build_ui(self, root, LANGUAGES, MODELS, Path.home() / 'Documents' / 'Prepisy', Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LokalnyPrepis' / 'models')
        self.restore_settings()
        self.refresh_queue()
        for variable in (self.language, self.quality, self.output, self.offline):
            variable.trace_add('write', lambda *_: self.schedule_save())
        root.bind('<Configure>', lambda event: self.schedule_save() if event.widget == root else None, add='+')
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES
            TkinterDnD._require(root)
            root.drop_target_register(DND_FILES)
            root.dnd_bind('<<Drop>>', lambda event: self.accept_files(root.tk.splitlist(event.data)))
        except (ImportError, tk.TclError, AttributeError, RuntimeError) as exc:
            self.events.put(('log', f'Pretiahnutie súborov nie je dostupné: {exc}. Použite Pridať nahrávky.'))
        if self.store.warning:
            self.events.put(('log', self.store.warning))
        if show_on_ready:
            root.deiconify()

    @property
    def files(self):
        return [item['source'] for item in self.items]

    @files.setter
    def files(self, paths):
        self.items = [queue_item(path) for path in paths]

    def restore_settings(self):
        from ui import apply_theme
        settings = self.store.settings(LANGUAGES, MODELS)
        self.language.set(settings.get('language', 'Slovenčina'))
        self.quality.set(settings.get('model', next(iter(MODELS))))
        self.output.set(settings.get('output', str(Path.home() / 'Documents' / 'Prepisy')))
        self.offline.set(settings.get('offline', False))
        apply_theme(self, settings.get('theme', 'dark'))
        # Start at the existing DPI-aware minimum, regardless of saved geometry.

    def schedule_save(self):
        if self.persist_timer:
            self.root.after_cancel(self.persist_timer)
        self.persist_timer = self.root.after(500, self.save_state)

    def save_state(self):
        self.persist_timer = None
        try:
            self.store.save('settings.json', dict(language=self.language.get(), model=self.quality.get(),
                output=self.output.get(), theme=self.theme, offline=self.offline.get(), geometry=self.root.geometry()))
            self.store.save('queue.json', self.items)
            return True
        except OSError as exc:
            self.status.set(f'Nastavenia/frontu sa nepodarilo uložiť: {exc}')
            return False

    def reset_settings(self):
        if self.busy:
            return
        from ui import apply_theme
        self.language.set('Slovenčina')
        self.quality.set(next(iter(MODELS)))
        self.output.set(str(Path.home() / 'Documents' / 'Prepisy'))
        self.offline.set(False)
        width, height = self.root.minsize()
        self.root.geometry(f'{width}x{height}')
        apply_theme(self, 'dark')
        self.save_state()

    def refresh_queue(self):
        selected = self.listbox.curselection()
        self.listbox.delete(0, 'end')
        for item in self.items:
            self.listbox.insert('end', f'[{item["state"]}]  {Path(item["source"]).name}' +
                                (f' — {item["error"]}' if item.get('error') else ''))
        for index in selected:
            if index < len(self.items):
                self.listbox.selection_set(index)
        update_files(self)

    def accept_files(self, paths):
        if self.busy:
            return
        for path in paths:
            if Path(path).is_file() and str(Path(path).resolve()) not in self.files:
                self.items.append(queue_item(path))
        self.refresh_queue()
        self.save_state()

    def add_files(self):
        files = filedialog.askopenfilenames(title='Vyberte zvukové súbory', filetypes=[
            ('Zvuk a video', '*.mp3 *.wav *.m4a *.flac *.ogg *.opus *.aac *.wma *.mp4 *.mkv'), ('Všetky súbory', '*.*')])
        self.accept_files(files)

    def remove_files(self):
        if self.busy:
            return
        for index in reversed(self.listbox.curselection()):
            del self.items[index]
        self.refresh_queue()
        self.save_state()

    def move_item(self, direction):
        if self.busy:
            return
        selected = self.listbox.curselection()
        if len(selected) == 1:
            index, target = selected[0], selected[0] + direction
            if 0 <= target < len(self.items) and self.items[index]['state'] == self.items[target]['state'] == 'čaká':
                self.items[index], self.items[target] = self.items[target], self.items[index]
                self.refresh_queue()
                self.listbox.selection_clear(0, 'end')
                self.listbox.selection_set(target)
                self.save_state()

    def open_editor(self):
        selected = self.listbox.curselection()
        if not selected:
            return
        item = self.items[selected[0]]
        if item['state'] == 'spracúva sa':
            messagebox.showinfo('Editor', 'Pred upravovaním zastavte prepis, aby sa dáta nemenili súčasne.')
            return
        if not item.get('project'):
            messagebox.showinfo('Editor', 'Položka ešte nemá uložený projekt prepisu.')
            return
        from editor import Editor
        try:
            for editor in self.editors:
                if editor.window.winfo_exists() and editor.folder == item['project']:
                    editor.window.lift()
                    return
            self.editors.append(Editor(self, item['project']))
        except Exception as exc:
            messagebox.showerror('Editor', str(exc))

    def manage_models(self):
        if self.busy:
            return
        if any(editor.window.winfo_exists() and editor.speaker_busy for editor in self.editors):
            messagebox.showinfo('Správca modelov', 'Počkajte na dokončenie rozlíšenia hlasov.')
            return
        if self.model_dialog and self.model_dialog.window.winfo_exists():
            self.model_dialog.window.lift()
            return
        from model_dialog import ModelDialog
        self.model_dialog = ModelDialog(self)

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output.set(folder)

    def open_results(self):
        selected = self.listbox.curselection()
        folder = Path(self.items[selected[0]]['project']) if selected and self.items[selected[0]].get('project') else Path(self.output.get()).expanduser()
        if folder.is_dir():
            os.startfile(str(folder))
        else:
            messagebox.showinfo('Výsledky', 'Výstupný priečinok ešte neexistuje.')

    def start(self, mode='pending'):
        if self.busy:
            return
        if self.model_dialog and self.model_dialog.window.winfo_exists():
            messagebox.showinfo('Správca modelov', 'Pred spustením zatvorte Správcu modelov.')
            return
        for editor in self.editors:
            if editor.window.winfo_exists() and not editor.close():
                return
        self.batch_mode = mode
        states = ('čaká',) if mode == 'pending' else ('prerušené', 'chyba')
        chosen = list(self.listbox.curselection())
        selected_items = [self.items[i] for i in chosen] if mode == 'new' and chosen else self.items
        selected_items = [item for item in selected_items if mode == 'new' or item['state'] in states]
        self.batch_ids = [item['id'] for item in selected_items]
        if not selected_items or not self.output.get().strip():
            messagebox.showinfo('Prepis', 'Nie sú vybrané vhodné položky. Pridajte nahrávku, použite Opakovať alebo Nový od začiatku.')
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
        self.clock = ProgressClock(time.monotonic())
        self.batch_index = self.file_progress = 0
        self.save_state()
        args = ([item['source'] for item in selected_items], self.output.get(), LANGUAGES[self.language.get()], MODELS[self.quality.get()], self.offline.get())
        threading.Thread(target=self.work, args=args, daemon=True).start()

    def cancel(self):
        self.stop.set()
        self.status.set('Zastavujem po aktuálnom kroku… rozpracovaný text sa zachová.')
        self.stop_button.configure(state='disabled')

    def work(self, files, folder, language, model_name, offline):
        emit = lambda kind, value: self.events.put((kind, value))
        def update(identifier, **changes):
            ack = threading.Event()
            result = []
            emit('job', (identifier, changes, ack, result))
            ack.wait()
            if not result[0]:
                raise OSError('Frontu sa nepodarilo bezpečne uložiť. Skontrolujte výstup a voľné miesto.')
        done = failed = 0
        current = None
        try:
            from model_catalog import ensure_model, cached_path
            ensure_model(self.cache, model_name, offline, emit, self.stop)
            revision = cached_path(self.cache, model_name).name
            if getattr(self, 'loaded_revision', None) != revision:
                self.models.close()
            self.model = None
            emit('status', 'Načítavam model do pamäte…')
            self.model = self.models.get(language, model_name, self.cache, True, emit, self.stop)
            self.loaded_revision = revision
            self.model_name = model_name
            from speech_models import LocalAdapter
            actual_device = self.model.device if isinstance(self.model, LocalAdapter) else self.model.model.device
            emit('device', 'GPU (CUDA)' if actual_device == 'cuda' else 'CPU')
            for i, file in enumerate(files, 1):
                if self.stop.is_set():
                    break
                identifier = self.batch_ids[i-1]
                current = next(item for item in self.items if item['id'] == identifier)
                emit('batch_index', i-1)
                emit('progress', 0)
                emit('log', '\n' + Path(file).name)
                try:
                    target = current.get('project') if self.batch_mode != 'new' else ''
                    resume = False
                    if target and (Path(target) / 'projekt.sqlite3').is_file():
                        with Project(target) as project:
                            resume = project.get('schema') == 1
                    if not target:
                        target = str(reserve_output(folder, Path(file).stem))
                    update(identifier, state='spracúva sa', project=str(target), error='')
                    settings = job_settings(model_name, language)
                    settings['model_revision'] = revision
                    complete = transcribe_job(self.model, file, target, settings,
                                              self.stop, emit, resume=resume)
                    update(identifier, state='hotovo' if complete else 'prerušené')
                    done += int(complete)
                    emit('log', f'{"Uložené" if complete else "Čiastočný prepis"}: {target}')
                except InterruptedError:
                    update(identifier, state='prerušené')
                    break
                except Exception as exc:
                    failed += 1
                    update(identifier, state='chyba', error=str(exc))
                    emit('log', f'Chyba súboru {Path(file).name}: {exc}')
                if not self.stop.is_set():
                    emit('batch_index', i-1)
                    emit('progress', 100)
            emit('status', f'{"Zastavené" if self.stop.is_set() else "Dokončené"}. Hotové: {done}/{len(files)}. Chyby: {failed}.')
        except InterruptedError:
            emit('status', 'Načítanie prerušené.')
        except Exception as exc:
            if current is None:
                for identifier in self.batch_ids:
                    update(identifier, state='chyba', error=str(exc))
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
                self.file_progress = value
                if self.clock:
                    self.clock.update((self.batch_index + value/100) / max(1, len(self.batch_ids)), time.monotonic())
            elif kind == 'batch_index':
                self.batch_index = value
                self.file_progress = 0
            elif kind == 'device':
                self.device_status.set('Zariadenie: ' + value)
            elif kind == 'segment':
                preview.append(f'[{timestamp(value["start"])} – {timestamp(value["end"])}] {value["text"]}')
            elif kind == 'text':
                preview.append(value)
            elif kind == 'log':
                activity.append(value)
            elif kind == 'job':
                identifier, changes, ack, result = value
                try:
                    next(item for item in self.items if item['id'] == identifier).update(changes)
                    self.refresh_queue()
                    result.append(self.save_state())
                finally:
                    if not result:
                        result.append(False)
                    ack.set()
            elif kind == 'error':
                errors.append(value)
            elif kind == 'finished':
                finished = True
        if latest_status is not None and self.status.get() != latest_status:
            self.status.set(latest_status)
        if self.busy and self.stop.is_set() and not finished:
            self.status.set('Zastavujem: čakám na aktuálny prepis alebo prenos modelu. Bezpečne uložené úseky zostávajú zachované.')
        if latest_progress is not None:
            self.progress['value'] = latest_progress
            self.percent.set(f'{int(latest_progress)} %')
        if self.clock:
            now = time.monotonic()
            fraction = min(1, (self.batch_index + self.file_progress/100) / max(1, len(self.batch_ids)))
            if float(self.batch_progress['value']) != fraction * 100:
                self.batch_progress['value'] = fraction * 100
            remaining = self.clock.remaining(now)
            elapsed = int(now - self.clock.started)
            eta = f'približne {int(remaining)//60}:{int(remaining)%60:02}' if remaining is not None else 'ešte sa počíta'
            timing = f'Dávka: {fraction:.0%} • Uplynulo {elapsed//60}:{elapsed%60:02} • Zostáva: {eta}'
            if self.timing.get() != timing:
                self.timing.set(timing)
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
            self.clock = None
            self.save_state()
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
            for editor in self.editors:
                if editor.window.winfo_exists() and not editor.close():
                    return
            if self.model_dialog and self.model_dialog.window.winfo_exists():
                self.model_dialog.close()
                if self.model_dialog.window.winfo_exists():
                    return
            if not self.save_state():
                messagebox.showerror('Uloženie', 'Nastavenia/fronta sa neuložili. Skontrolujte voľné miesto.')
                return
            self.root.destroy()

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    if os.environ.get('ND_TRANSKRIPTHOR_DEBUG') == '1':
        import logging
        debug_folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LokalnyPrepis'
        debug_folder.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(debug_folder / 'asr-debug.log', maxBytes=2_000_000,
                                      backupCount=2, encoding='utf-8')
        logging.getLogger('mixed_language').addHandler(handler)
        logging.getLogger('mixed_language').setLevel(logging.DEBUG)
    if len(sys.argv) == 5 and sys.argv[1] in ('--self-test', '--self-test-sk', '--self-test-hu', '--self-test-mixed', '--self-test-v2'):
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
                if sys.argv[1] in ('--self-test-mixed', '--self-test-v2'):
                    language = MIXED_LANGUAGE
            if sys.argv[1] == '--self-test-v2':
                target = reserve_output(folder, Path(sys.argv[3]).stem)
                complete = transcribe_job(model, sys.argv[3], target, job_settings('small', language), threading.Event(), lambda *a: None)
            else:
                target, complete = transcribe_file(model, sys.argv[3], folder, language, threading.Event(), lambda *a: None)
            if not complete or not (target / 'prepis.txt').read_text(encoding='utf-8-sig').strip():
                raise RuntimeError('Diagnostický prepis je prázdny alebo neúplný.')
            root = tk.Tk()
            root.withdraw()
            app = App(root, folder / 'test-state')
            root.update()
            if sys.argv[1] == '--self-test-v2':
                # Verify native libraries included in the Windows distribution.
                root.tk.call('package', 'present', 'tkdnd')
                import sounddevice
                sounddevice.query_devices()
                import kaldi_native_fbank
                from editor import Editor
            root.destroy()
            (folder / 'diagnostika.txt').write_text(f'OK: {complete}\n{target}', encoding='utf-8')
        except Exception:
            (folder / 'diagnostika.txt').write_text(traceback.format_exc(), encoding='utf-8')
            sys.exit(1)
    else:
        root = tk.Tk()
        app = App(root)
        root.mainloop()
