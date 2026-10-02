"""Complete transcript editor, paged presentation, local audio playback."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from project import Project, fingerprint
from playback import Player
from subtitles import SubtitleOptions, timestamp
from ui import PALETTES


class Editor:
    PAGE_SIZE = 150

    def __init__(self, app, folder):
        self.app, self.folder = app, folder
        with Project(folder) as project:
            self.segments = project.segments()
            self.source, self.digest = project.get('source'), project.get('fingerprint')
        self.window = tk.Toplevel(app.root)
        self.window.title('Editor prepisu — ND TranskripThor')
        scale = max(1, app.root.winfo_fpixels('1i')/96)
        self.window.geometry(f'{min(round(1080*scale), app.root.winfo_screenwidth()-40)}x{min(round(730*scale), app.root.winfo_screenheight()-80)}+20+20')
        self.window.minsize(750, 550)
        self.current = None
        self.dirty = False
        self.loading_text = False
        self.page = 0
        self.matches = list(range(len(self.segments)))
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.speaker_busy = False
        self.player = Player()
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill='both', expand=True)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x')
        self.query = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.query).pack(side='left', fill='x', expand=True)
        ttk.Button(toolbar, text='Hľadať v celom prepise', command=self.search).pack(side='left', padx=5)
        ttk.Button(toolbar, text='Uložiť TXT/SRT', command=self.save).pack(side='right')
        tree_panel = ttk.Frame(outer)
        tree_panel.pack(fill='both', expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(tree_panel, columns=('time', 'language', 'speaker', 'text'), show='headings', height=10)
        for name, label, width in [('time', 'Čas', 180), ('language', 'Jazyk', 55), ('speaker', 'Hovoriaci', 100), ('text', 'Prepis', 500)]:
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, minwidth=45, stretch=name == 'text')
        scroll = ttk.Scrollbar(tree_panel, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        pages = ttk.Frame(outer)
        pages.pack(fill='x')
        ttk.Button(pages, text='← Predošlé', command=lambda: self.change_page(-1)).pack(side='left')
        ttk.Button(pages, text='Ďalšie →', command=lambda: self.change_page(1)).pack(side='left')
        self.page_label = tk.StringVar()
        ttk.Label(pages, textvariable=self.page_label).pack(side='right')
        self.text = tk.Text(outer, height=5, wrap='word', undo=True, font=(app.font, 11))
        self.text.pack(fill='x', pady=8)
        self.text.bind('<<Modified>>', self.modified)
        voice = ttk.Frame(outer)
        voice.pack(fill='x')
        ttk.Label(voice, text='Hovoriaci úseku:').pack(side='left')
        self.speaker = tk.StringVar()
        ttk.Entry(voice, textvariable=self.speaker, width=22).pack(side='left')
        self.speaker.trace_add('write', lambda *_: self.mark_dirty() if not self.loading_text else None)
        ttk.Button(voice, text='Premenovať v celom prepise', command=self.rename_speaker).pack(side='left', padx=5)
        self.speaker_button = ttk.Button(voice, text='Rozlíšiť hlasy (voliteľné)', command=self.diarize)
        self.speaker_button.pack(side='right')
        playback = ttk.Frame(outer)
        playback.pack(fill='x', pady=8)
        ttk.Button(playback, text='▶ Úsek', command=self.play_segment).pack(side='left')
        ttk.Button(playback, text='▶ Pokračovať', command=self.play).pack(side='left')
        ttk.Button(playback, text='Ⅱ Pauza', command=self.player.pause).pack(side='left')
        self.position = tk.DoubleVar(value=0)
        self.slider = ttk.Scale(playback, variable=self.position, from_=0, to=1)
        self.slider.pack(side='left', fill='x', expand=True, padx=8)
        self.dragging = False
        self.slider.bind('<ButtonPress-1>', self.begin_seek)
        self.slider.bind('<ButtonRelease-1>', self.seek)
        self.clock = tk.StringVar(value='00:00:00,000')
        ttk.Label(playback, textvariable=self.clock).pack(side='right')
        subtitle = ttk.Frame(outer)
        subtitle.pack(fill='x')
        self.cue_values = []
        for label, default in [('Znakov/riadok', 42), ('Riadkov', 2), ('Min. sekúnd', 1), ('Max. sekúnd', 7)]:
            ttk.Label(subtitle, text=label).pack(side='left', padx=(0, 4))
            value = tk.StringVar(value=str(default))
            ttk.Entry(subtitle, textvariable=value, width=5).pack(side='left', padx=(0, 10))
            self.cue_values.append(value)
        self.status = tk.StringVar(value='Pripravujem zvuk… Kliknutie na úsek prehrá jeho obsah.')
        ttk.Label(outer, textvariable=self.status, wraplength=900).pack(fill='x', pady=(8, 0))
        self.apply_theme()
        self.render()
        threading.Thread(target=self.load_audio, daemon=True).start()
        self.window.after(100, self.poll)

    def apply_theme(self):
        palette = PALETTES[self.app.theme]
        self.window.configure(bg=palette['bg'])
        self.text.configure(bg=palette['field'], fg=palette['text'], insertbackground=palette['text'],
                            selectbackground=palette['blue'], selectforeground='white')
        from window_style import titlebar
        self.window.after_idle(lambda: titlebar(self.window, self.app.theme == 'dark', palette['bg'], palette['text']))

    def mark_dirty(self):
        if self.current is not None:
            self.dirty = True
            self.window.title('Editor prepisu — neuložené úpravy *')

    def modified(self, event=None):
        if self.text.edit_modified():
            if not self.loading_text:
                self.mark_dirty()
            self.text.edit_modified(False)

    def capture(self):
        if self.current is not None:
            item = self.segments[self.current]
            text = self.text.get('1.0', 'end-1c')
            if text != item['text']:
                item['text'], item['words'] = text, []  # edited words no longer have trustworthy alignment
            item['speaker'] = self.speaker.get().strip()

    def render(self):
        self.tree.delete(*self.tree.get_children())
        first = self.page * self.PAGE_SIZE
        for index in self.matches[first:first + self.PAGE_SIZE]:
            item = self.segments[index]
            self.tree.insert('', 'end', iid=str(index), values=(
                f'{timestamp(item["start"])} – {timestamp(item["end"])}', item.get('language') or '',
                item.get('speaker', ''), item['text']))
        self.page_label.set(f'{first+1 if self.matches else 0}–{min(first+self.PAGE_SIZE,len(self.matches))} / {len(self.matches)} úsekov')

    def select(self, event=None):
        chosen = self.tree.selection()
        if not chosen:
            return
        self.capture()
        self.current = int(chosen[0])
        item = self.segments[self.current]
        self.loading_text = True
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', item['text'])
        self.text.edit_modified(False)
        self.speaker.set(item.get('speaker', ''))
        self.loading_text = False
        if self.player.audio is not None:
            self.play_segment()

    def search(self):
        self.capture()
        query = self.query.get().casefold()
        self.matches = [i for i, item in enumerate(self.segments) if query in item['text'].casefold()]
        self.page = 0
        self.render()

    def change_page(self, delta):
        self.capture()
        self.page = max(0, min(self.page + delta, max(0, (len(self.matches)-1)//self.PAGE_SIZE)))
        self.render()

    def load_audio(self):
        try:
            if fingerprint(self.source, self.stop) != self.digest:
                raise ValueError('Zdrojová nahrávka sa zmenila. Prehrávanie je zablokované; text možno upravovať.')
            if not self.stop.is_set():
                duration = self.player.load(self.source)
                self.events.put(('loaded', duration))
        except Exception as exc:
            self.events.put(('error', str(exc)))

    def play(self, start=None, end=None):
        try:
            self.player.play(start, end)
        except Exception as exc:
            self.status.set(f'Prehrávanie nie je dostupné: {exc}')

    def play_segment(self):
        if self.current is not None:
            item = self.segments[self.current]
            self.play(item['start'], item['end'])

    def begin_seek(self, event=None):
        self.dragging = True
        self.player.pause()

    def seek(self, event=None):
        self.dragging = False
        self.play(self.position.get())

    def save(self):
        self.capture()
        try:
            chars, lines, minimum, maximum = [value.get() for value in self.cue_values]
            options = SubtitleOptions(int(chars), int(lines), float(minimum), float(maximum))
            with Project(self.folder) as project:
                project.edit(self.segments)
                warnings = project.export(options, corrected=True)
            self.dirty = False
            self.window.title('Editor prepisu — ND TranskripThor')
            self.status.set('Uložené: prepis.opravene.txt a titulky.opravene.srt. ' + ' '.join(warnings))
            return True
        except Exception as exc:
            messagebox.showerror('Uloženie', str(exc), parent=self.window)
            return False

    def rename_speaker(self):
        self.capture()
        old = self.speaker.get().strip()
        if not old:
            return
        new = simpledialog.askstring('Premenovať hlas', f'Nový názov pre {old}:', parent=self.window)
        if new and new.strip():
            for item in self.segments:
                if item.get('speaker') == old:
                    item['speaker'] = new.strip()
            self.speaker.set(new.strip())
            self.dirty = True
            self.render()

    def diarize(self):
        if self.speaker_busy or self.player.audio is None:
            self.status.set('Počkajte na pripravenie zvuku alebo dokončenie rozlíšenia hlasov.')
            return
        from model_catalog import cached_path, SPEAKER_MODEL
        path = cached_path(self.app.cache, SPEAKER_MODEL)
        if not path:
            messagebox.showinfo('Rozlíšenie hlasov', 'Najprv stiahnite voliteľný model WeSpeaker v Správcovi modelov. Bez tokenu, licencia CC BY 4.0. Bežný prepis ho nepotrebuje.', parent=self.window)
            return
        if not messagebox.askyesno('Rozlíšenie hlasov', 'Spustiť lokálne zoskupenie hlasov? Nahradí aktuálne priradenia. Neurčuje skutočnú identitu a výsledky treba skontrolovať.', parent=self.window):
            return
        self.capture()
        self.speaker_busy = True
        self.speaker_button.configure(state='disabled')
        def run():
            try:
                from speakers import assign_speakers
                result = assign_speakers(self.player.audio, self.segments, path, self.stop,
                                         lambda text: self.events.put(('status', text)))
                self.events.put(('speakers', result))
            except Exception as exc:
                self.events.put(('speaker_error', str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        if not self.window.winfo_exists():
            return
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'loaded':
                self.slider.configure(to=max(1, value))
                self.status.set('Zvuk pripravený. Kliknite na úsek pre prehratie.')
            elif kind == 'speakers':
                for item, speaker in zip(self.segments, value):
                    item['speaker'] = speaker
                self.speaker_busy = False
                self.speaker_button.configure(state='normal')
                self.dirty = True
                self.current = None
                self.render()
                self.status.set('Hlasy priradené. Skontrolujte výsledky a uložte zmeny.')
            else:
                if kind == 'speaker_error':
                    self.speaker_busy = False
                    self.speaker_button.configure(state='normal')
                self.status.set(value)
        if not self.dragging:
            self.position.set(self.player.position / 16000)
        self.clock.set(timestamp(self.position.get()))
        self.window.after(100, self.poll)

    def close(self):
        self.capture()
        if self.speaker_busy:
            self.stop.set()
            self.status.set('Zastavujem rozlíšenie hlasov; počkajte na aktuálny úsek.')
            return False
        if self.dirty:
            answer = messagebox.askyesnocancel('Neuložené úpravy', 'Uložiť zmeny pred zatvorením?', parent=self.window)
            if answer is None or (answer and not self.save()):
                return False
        self.stop.set()
        self.player.close()
        self.window.destroy()
        return True
