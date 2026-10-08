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
from speech_models import ModelManager, SLOVAK_MODEL, route, DEVICES, GPUError
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
        for variable in (self.language, self.quality, self.output, self.offline, self.autoplay, self.device_choice):
            variable.trace_add('write', lambda *_: self.schedule_save())
        self.device_choice.trace_add('write', self.device_changed)
        for variable in (self.language, self.quality, self.offline):
            variable.trace_add('write', lambda *_: self.update_readiness())
        self.update_readiness()
        root.bind('<Configure>', lambda event: self.schedule_save() if event.widget == root else None, add='+')
        from file_drop import FileDrop
        self.file_drop = FileDrop(self)
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
        self.device_choice.set(next(label for label, code in DEVICES.items() if code == settings.get('device', 'cpu')))
        self.output.set(settings.get('output', str(Path.home() / 'Documents' / 'Prepisy')))
        self.offline.set(settings.get('offline', False))
        self.autoplay.set(settings.get('autoplay', False))
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
                device=DEVICES.get(self.device_choice.get(), 'cpu'),
                output=self.output.get(), theme=self.theme, offline=self.offline.get(), autoplay=self.autoplay.get(), geometry=self.root.geometry()))
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
        self.device_choice.set(next(iter(DEVICES)))
        self.output.set(str(Path.home() / 'Documents' / 'Prepisy'))
        self.offline.set(False)
        self.autoplay.set(False)
        width, height = self.root.minsize()
        self.root.geometry(f'{width}x{height}')
        apply_theme(self, 'dark')
        self.save_state()

    def refresh_queue(self):
        self.listbox.set_items(self.items)
        update_files(self)
        self.update_selection()

    def update_selection(self):
        selected = self.listbox.curselection()
        item = self.items[selected[0]] if len(selected) == 1 else None
        idle = not self.busy
        label = 'Otvoriť prepis'
        actionable = bool(item and item.get('project'))
        if item and item['state'] in ('prerušené', 'chyba'):
            label, actionable = ('Pokračovať' if item.get('project') else 'Skúsiť znova'), True
        self.context_button.configure(text=label, state='normal' if idle and actionable else 'disabled')
        self.editor_button.configure(state='normal' if idle and item and item.get('project') else 'disabled')
        self.info_button.configure(state='normal' if item else 'disabled')
        for button in (self.remove, self.new_button):
            button.configure(state='normal' if idle and selected else 'disabled')
        for button, direction in ((self.move_up, -1), (self.move_down, 1)):
            target = selected[0]+direction if item else -1
            movable = item and item['state'] == 'čaká' and 0 <= target < len(self.items) and self.items[target]['state'] == 'čaká'
            button.configure(state='normal' if idle and movable else 'disabled')
        if item:
            detail = item['source']
            if item.get('error'):
                detail += '\nChyba: ' + item['error']
            elif item['state'] == 'prerušené':
                detail += '\nPokračovanie použije nastavenia uloženého projektu.'
            # Keep the queue usable even for lengthy backend errors; full details remain accessible.
            self.selection_info.set(detail[:260] + ('…' if len(detail) > 260 else ''))
        else:
            self.selection_info.set(f'Vybrané nahrávky: {len(selected)}' if selected else 'Vyberte nahrávku pre ďalšie možnosti.')

    def context_action(self):
        if self.busy:
            return
        selected = self.listbox.curselection()
        if len(selected) != 1:
            return
        item = self.items[selected[0]]
        if item['state'] in ('prerušené', 'chyba'):
            self.start('retry', identifiers=[item['id']])
        elif item.get('project'):
            self.open_editor()

    def show_item_info(self):
        selected = self.listbox.curselection()
        if len(selected) != 1:
            return
        item = self.items[selected[0]]
        text = item['source'] + '\n\nStav: ' + item['state']
        if item.get('project'):
            text += '\nProjekt: ' + item['project']
            try:
                with Project(item['project']) as project:
                    settings = project.get('settings', {})
                text += f'\nUložený model: {settings.get("model", "—")}\nUložený jazyk: {settings.get("language") or "automaticky"}'
            except Exception as exc:
                text += '\nProjekt sa nedá načítať: ' + str(exc)
        if item.get('error'):
            text += '\n\nChyba: ' + item['error'] + '\n\nSkontrolujte súbor, model a voľné miesto. Pri nezhode projektu použite Nový prepis.'
        messagebox.showinfo('Podrobnosti nahrávky', text, parent=self.root)

    def page_changed(self, _event=None):
        if self.workspace_tabs.select() == str(self.models_page):
            self.manage_models()

    def update_readiness(self):
        from model_catalog import cached_path
        try:
            model = MODELS[self.quality.get()]
            route(LANGUAGES[self.language.get()], model)
            available = cached_path(self.cache, model) is not None
            self.readiness.set('Model je pripravený lokálne.' if available else
                'Model chýba. V režime offline ho nemožno stiahnuť; otvorte kartu Modely.' if self.offline.get() else
                'Model sa pri prvom použití stiahne. Zvuk ani prepis sa neodosielajú.')
        except (KeyError, ValueError, OSError) as exc:
            self.readiness.set(str(exc))

    def accept_files(self, paths):
        if self.busy:
            self.status.set('Počas prepisu nemožno pridávať nahrávky. Najprv prepis zastavte.')
            return False
        from file_drop import path_key
        known = {path_key(path) for path in self.files}
        added, duplicates, invalid = [], 0, 0
        for path in paths:
            try:
                if not isinstance(path, str) or not path or not Path(path).is_file():
                    invalid += 1
                    continue
                key = path_key(path)
                if key in known:
                    duplicates += 1
                    continue
                added.append(queue_item(path))
                known.add(key)
            except (OSError, ValueError):
                invalid += 1
        self.items.extend(added)
        self.refresh_queue()
        if added and not self.save_state():
            del self.items[-len(added):]
            self.refresh_queue()
            return False
        self.status.set(f'Pridané: {len(added)}. Preskočené: {duplicates + invalid} '
            f'(duplicity: {duplicates}, neexistujúce súbory/priečinky alebo neplatné cesty: {invalid}).')
        return bool(added or duplicates)

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
                    self.workspace_tabs.select(self.editor_page)
                    return
            for editor in self.editors:
                if editor.window.winfo_exists() and not editor.close():
                    return
            self.editor_empty.pack_forget()
            self.editors.append(Editor(self, item['project'], parent=self.editor_page))
            self.workspace_tabs.select(self.editor_page)
        except Exception as exc:
            messagebox.showerror('Editor', str(exc))

    def manage_models(self):
        if self.busy:
            return
        if any(editor.window.winfo_exists() and editor.speaker_busy for editor in self.editors):
            messagebox.showinfo('Správca modelov', 'Počkajte na dokončenie rozlíšenia hlasov.')
            return
        if self.model_dialog and self.model_dialog.window.winfo_exists():
            return
        from model_dialog import ModelDialog
        self.model_dialog = ModelDialog(self, parent=self.models_page)

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

    def start(self, mode='pending', identifiers=None):
        if self.busy:
            return
        if self.model_dialog and self.model_dialog.window.winfo_exists() and self.model_dialog.busy:
            messagebox.showinfo('Správca modelov', 'Počkajte na dokončenie práce s modelmi.')
            return
        for editor in self.editors:
            if editor.window.winfo_exists() and not editor.close():
                return
        self.batch_mode = mode
        states = ('čaká',) if mode == 'pending' else ('prerušené', 'chyba')
        chosen = list(self.listbox.curselection())
        selected_items = [self.items[i] for i in chosen] if mode == 'new' else self.items
        if identifiers is not None:
            selected_items = [item for item in selected_items if item['id'] in identifiers]
        selected_items = [item for item in selected_items if mode == 'new' or item['state'] in states]
        self.batch_ids = [item['id'] for item in selected_items]
        if not selected_items or not self.output.get().strip():
            messagebox.showinfo('Prepis', 'Nie sú vybrané vhodné položky. Pridajte nahrávku, použite Opakovať alebo Nový od začiatku.')
            return
        language, model = LANGUAGES[self.language.get()], MODELS[self.quality.get()]
        self.resume_settings = None
        try:
            if identifiers is not None and len(selected_items) == 1 and selected_items[0].get('project'):
                with Project(selected_items[0]['project']) as project:
                    self.resume_settings = project.get('settings')
                if self.resume_settings:
                    language, model = self.resume_settings['language'], self.resume_settings['model']
            route(language, model)
            from model_catalog import cached_path
            if self.offline.get() and cached_path(self.cache, model) is None:
                messagebox.showinfo('Model nie je dostupný', 'Vybraný model nie je uložený v počítači. Na karte Modely ho stiahnite po vypnutí režimu Iba offline.')
                self.workspace_tabs.select(self.models_page)
                return
        except Exception as exc:
            messagebox.showinfo('Výber modelu', str(exc))
            return
        self.busy = True
        self.update_selection()
        self.stop.clear()
        for widget in (self.add, self.remove, self.lang_box, self.model_box, self.device_box, self.browse, self.output_entry, self.offline_box, self.start_button):
            widget.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.progress['value'] = 0
        self.percent.set('0 %')
        self.clock = ProgressClock(time.monotonic())
        self.batch_index = self.file_progress = 0
        self.save_state()
        args = ([item['source'] for item in selected_items], self.output.get(), language, model, self.offline.get(), DEVICES.get(self.device_choice.get(), 'cpu'))
        threading.Thread(target=self.work, args=args, daemon=True).start()

    def cancel(self):
        self.stop.set()
        self.status.set('Zastavujem po aktuálnom kroku… rozpracovaný text sa zachová.')
        self.stop_button.configure(state='disabled')

    def device_changed(self, *_):
        if not self.busy:
            self.model = None
            self.models.close()
            self.device_status.set('Zariadenie: čaká na načítanie modelu')

    def confirm_cpu(self):
        """Called only on the Tk thread; closing the dialog means cancel."""
        window = tk.Toplevel(self.root)
        window.title('GPU nie je dostupné')
        window.transient(self.root)
        answer = [False]
        ttk.Label(window, text='GPU sa nepodarilo použiť. Môžete pokračovať na CPU.', padding=20).pack()
        actions = ttk.Frame(window, padding=12)
        actions.pack(fill='x')
        def finish(accepted):
            answer[0] = accepted
            window.destroy()
        ttk.Button(actions, text='Pokračovať na CPU', command=lambda: finish(True)).pack(side='left', padx=6)
        cancel = ttk.Button(actions, text='Zrušiť', command=lambda: finish(False))
        cancel.pack(side='right', padx=6)
        window.protocol('WM_DELETE_WINDOW', lambda: finish(False))
        window.bind('<Escape>', lambda _event: finish(False))
        window.grab_set()
        cancel.focus_set()
        self.root.wait_window(window)
        return answer[0]

    def request_cpu(self, exc, emit):
        emit('log', f'GPU: {type(exc).__name__}: {exc}')
        ack, answer = threading.Event(), []
        emit('cpu_request', (ack, answer))
        while not ack.wait(.1):
            if self.stop.is_set():
                raise InterruptedError('Prechod na CPU zrušený.')
        if self.stop.is_set() or not answer or not answer[0]:
            self.stop.set()
            raise InterruptedError('Prechod na CPU zrušený; uložené úseky zostali zachované.')

    def work(self, files, folder, language, model_name, offline, selected_device='cpu'):
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
            def load():
                emit('device', 'čaká na načítanie modelu')
                self.model = self.models.get(language, model_name, self.cache, True, emit, self.stop, selected_device)
                from speech_models import LocalAdapter
                actual = self.model.device if isinstance(self.model, LocalAdapter) else self.model.model.device
                emit('device', 'GPU (CUDA)' if actual == 'cuda' else 'CPU')
                return self.model
            def recover(exc):
                nonlocal selected_device
                self.request_cpu(exc, emit)
                selected_device = 'cpu'
                self.model = None
                self.models.close()
                return load()
            try:
                load()
            except GPUError as exc:
                recover(exc)
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
                    settings = dict(self.resume_settings) if getattr(self, 'resume_settings', None) else job_settings(model_name, language)
                    settings['model_revision'] = revision
                    complete = transcribe_job(self.model, file, target, settings,
                                              self.stop, emit, resume=resume, recover_gpu=recover, selected_device=selected_device)
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
            if kind == 'download_state':
                self.progress.stop()
                self.progress.configure(mode='indeterminate' if value else 'determinate', value=0)
                self.percent.set('…' if value else '0 %')
                if value:
                    self.progress.start(20)
            elif kind == 'status':
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
            elif kind == 'cpu_request':
                ack, answer = value
                try:
                    accepted = not self.stop.is_set() and self.confirm_cpu()
                    if accepted:
                        self.device_choice.set(next(iter(DEVICES)))
                        self.save_state()
                    answer.append(accepted)
                finally:
                    ack.set()
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
            self.progress.stop()
            self.progress.configure(mode='determinate')
            self.busy = False
            self.clock = None
            self.save_state()
            for widget in (self.add, self.remove, self.browse, self.output_entry, self.offline_box, self.start_button):
                widget.configure(state='normal')
            self.lang_box.configure(state='readonly')
            self.model_box.configure(state='readonly')
            self.device_box.configure(state='readonly')
            self.stop_button.configure(state='disabled')
            self.update_selection()
            self.update_readiness()
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
    if len(sys.argv) == 3 and sys.argv[1] == '--dnd-test':
        # Isolated native Explorer QA; never load/save the user's queue.
        from file_drop import create_root
        root = create_root()
        folder = Path(sys.argv[2])
        app = App(root, folder / 'state')
        app.cache = folder / 'models'
        app.output.set(str(folder / 'results'))
        root.title('ND TranskripThor – DnD test')
        root.mainloop()
    elif len(sys.argv) == 5 and sys.argv[1] == '--self-test-download':
        import json
        from model_catalog import download, cached_path
        folder = Path(sys.argv[4])
        folder.mkdir(parents=True, exist_ok=True)
        records = []
        try:
            download(Path(sys.argv[3]), sys.argv[2], lambda kind, value: records.append((kind,value)), threading.Event())
            if not cached_path(Path(sys.argv[3]), sys.argv[2]):
                raise RuntimeError('Stiahnutý model nie je pripravený.')
            (folder/'download.json').write_text(json.dumps(dict(status='PASS',events=records),ensure_ascii=False),encoding='utf-8')
        except Exception as exc:
            (folder/'download.json').write_text(json.dumps(dict(status='FAIL',error=str(exc),events=records),ensure_ascii=False),encoding='utf-8')
            sys.exit(1)
    elif len(sys.argv) == 5 and sys.argv[1] in ('--self-test', '--self-test-sk', '--self-test-hu', '--self-test-mixed', '--self-test-v2'):
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
                model = ModelManager().get(None, sys.argv[2], folder / 'model-cache', True,
                    lambda *a: None, threading.Event(), 'cpu')
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
        from file_drop import create_root
        root = create_root()
        app = App(root)
        root.mainloop()
