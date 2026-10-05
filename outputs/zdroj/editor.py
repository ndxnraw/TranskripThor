"""Complete transcript editor, paged presentation, local audio playback."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from project import Project, fingerprint
from playback import Player
from subtitles import SubtitleOptions, timestamp
from ui import PALETTES


class Editor:
    PAGE_SIZE = 40

    def __init__(self, app, folder, parent=None):
        self.app, self.folder = app, folder
        with Project(folder) as project:
            self.segments = project.segments()
            self.source, self.digest = project.get('source'), project.get('fingerprint')
        self.embedded = parent is not None
        self.window = tk.Frame(parent) if self.embedded else tk.Toplevel(app.root)
        if self.embedded:
            self.window.pack(fill='both', expand=True)
        else:
            self.window.title('Editor prepisu — ND TranskripThor')
            scale = max(1, app.root.winfo_fpixels('1i')/96)
            self.window.geometry(f'{min(round(1080*scale), app.root.winfo_screenwidth()-40)}x{min(round(730*scale), app.root.winfo_screenheight()-80)}+20+20')
            self.window.minsize(750, 550)
            self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.current = None
        self.dirty = False
        self.loading_text = False
        self.page = 0
        self.matches = list(range(len(self.segments)))
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.speaker_busy = False
        self.player = Player()
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill='both', expand=True)
        heading = ttk.Frame(outer)
        heading.pack(fill='x', pady=(0, 8))
        self.saved_state = tk.StringVar(value='Všetky úpravy uložené')
        ttk.Label(heading, textvariable=self.saved_state, style='Muted.TLabel').pack(side='right')
        self.source_label = ttk.Label(heading, text=Path(self.source).name, style='Muted.TLabel', wraplength=500)
        self.source_label.pack(side='left', fill='x', expand=True)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x')
        self.query = tk.StringVar()
        search = ttk.Entry(toolbar, textvariable=self.query)
        search.pack(side='left', fill='x', expand=True)
        search.bind('<Return>', lambda _: self.search())
        ttk.Button(toolbar, text='Hľadať', command=self.search).pack(side='left', padx=5)
        ttk.Button(toolbar, text='Ďalší výskyt', command=self.next_match).pack(side='left')
        ttk.Button(toolbar, text='Uložiť TXT/SRT', style='Accent.TButton', command=self.save).pack(side='right', padx=(8, 0))
        # Pack fixed controls first so they remain accessible at minimum size.
        bottom = ttk.Frame(outer)
        bottom.pack(side='bottom', fill='x')
        self.status = tk.StringVar(value='Pripravujem zvuk… Výber úseku zvuk automaticky nespustí.')
        self.status_label = ttk.Label(bottom, textvariable=self.status, wraplength=800, style='Muted.TLabel')
        self.status_label.pack(side='bottom', fill='x', pady=4)
        details_toggle = ttk.Button(bottom, text='Úsek, hovoriaci a titulky ▾', command=self.toggle_details)
        details_toggle.pack(fill='x', pady=4)
        self.details = ttk.Frame(bottom)
        from transcript_blocks import TranscriptBlocks
        self.tree = TranscriptBlocks(outer, self)
        self.tree.pack(fill='both', expand=True, pady=(8, 0))
        pages = ttk.Frame(bottom)
        pages.pack(fill='x', pady=4)
        ttk.Button(pages, text='← Predošlé úseky', command=lambda: self.change_page(-1)).pack(side='left')
        ttk.Button(pages, text='Ďalšie úseky →', command=lambda: self.change_page(1)).pack(side='left', padx=5)
        self.page_label = tk.StringVar()
        ttk.Label(pages, textvariable=self.page_label).pack(side='right')
        # Replaced by an inline Text when a block is selected.
        self.text = tk.Text(self.window)
        voice = ttk.Frame(self.details)
        voice.pack(fill='x')
        ttk.Label(voice, text='Hovoriaci úseku:').pack(side='left')
        self.speaker = tk.StringVar()
        ttk.Entry(voice, textvariable=self.speaker, width=22).pack(side='left')
        self.speaker.trace_add('write', lambda *_: self.mark_dirty() if not self.loading_text else None)
        ttk.Button(voice, text='Premenovať v celom prepise', command=self.rename_speaker).pack(side='left', padx=5)
        self.speaker_button = ttk.Button(voice, text='Rozlíšiť hlasy (voliteľné)', command=self.diarize)
        self.speaker_button.pack(side='right')
        playback = ttk.Frame(bottom)
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
        subtitle = ttk.Frame(self.details)
        subtitle.pack(fill='x')
        self.cue_values = []
        for label, default in [('Znakov/riadok', 42), ('Riadkov', 2), ('Min. sekúnd', 1), ('Max. sekúnd', 7)]:
            ttk.Label(subtitle, text=label).pack(side='left', padx=(0, 4))
            value = tk.StringVar(value=str(default))
            ttk.Entry(subtitle, textvariable=value, width=5).pack(side='left', padx=(0, 10))
            self.cue_values.append(value)
        self.window.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(200, event.width-32)) if event.widget == self.window else None)
        self.apply_theme()
        self.render()
        threading.Thread(target=self.load_audio, daemon=True).start()
        self.poll_timer = self.window.after(100, self.poll)

    def apply_theme(self):
        palette = PALETTES[self.app.theme]
        self.window.configure(bg=palette['bg'])
        if self.text.winfo_exists():
            self.text.configure(bg=palette['field'], fg=palette['text'], insertbackground=palette['text'],
                                selectbackground=palette['blue'], selectforeground=palette['accent_text'])
        self.tree.canvas.configure(bg=palette['bg'])
        if not self.embedded:
            from window_style import titlebar
            self.window.after_idle(lambda: titlebar(self.window, self.app.theme == 'dark', palette['bg'], palette['text']))

    def mark_dirty(self):
        if self.current is not None:
            self.dirty = True
            self.saved_state.set('● Neuložené úpravy')
            if not self.embedded:
                self.window.title('Editor prepisu — neuložené úpravy *')

    def modified(self, event=None):
        if self.text.edit_modified():
            if not self.loading_text:
                self.mark_dirty()
                self.status.set('Text bol upravený. Čas úseku zostáva; presné časovanie jeho slov sa zruší.')
            self.text.edit_modified(False)

    def capture(self):
        if self.current is not None:
            item = self.segments[self.current]
            text = self.text.get('1.0', 'end-1c')
            if text != item['text']:
                self.mark_dirty()
                item['text'], item['words'] = text, []  # edited words no longer have trustworthy alignment
            if item.get('speaker', '') != self.speaker.get().strip():
                self.mark_dirty()
            item['speaker'] = self.speaker.get().strip()

    def render(self):
        self.current = None
        first = self.page * self.PAGE_SIZE
        self.tree.render(self.matches[first:first + self.PAGE_SIZE])
        self.page_label.set(f'{first+1 if self.matches else 0}–{min(first+self.PAGE_SIZE,len(self.matches))} / {len(self.matches)} úsekov')

    def select(self, event=None):
        chosen = self.tree.selection()
        if not chosen:
            return
        self.capture()
        self.current = int(chosen[0])
        item = self.segments[self.current]
        self.loading_text = True
        self.tree.edit(self.current, item['text'])
        self.speaker.set(item.get('speaker', ''))
        self.loading_text = False
        if self.app.autoplay.get() and self.player.audio is not None:
            self.play_segment()

    def search(self):
        self.capture()
        query = self.query.get().casefold()
        self.matches = [i for i, item in enumerate(self.segments) if query in item['text'].casefold()]
        self.page = 0
        self.render()

    def next_match(self):
        if not self.matches:
            return
        self.capture()
        position = (self.matches.index(self.current)+1) % len(self.matches) if self.current in self.matches else 0
        index = self.matches[position]
        if self.page != position // self.PAGE_SIZE:
            self.page = position // self.PAGE_SIZE
            self.render()
        self.tree.selection_set(str(index))
        self.select()
        self.tree.reveal(index)

    def toggle_details(self):
        if self.details.winfo_manager():
            self.details.pack_forget()
        else:
            self.details.pack(fill='x', pady=4)

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
            self.saved_state.set('Všetky úpravy uložené')
            if not self.embedded:
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
        if self.app.busy or (self.app.model_dialog and self.app.model_dialog.window.winfo_exists() and self.app.model_dialog.busy):
            self.status.set('Počkajte na dokončenie prepisu alebo práce s modelmi.')
            return
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
                self.status.set('Zvuk pripravený. Vyberte úsek a stlačte ▶ Úsek.')
            elif kind == 'speakers':
                for item, speaker in zip(self.segments, value):
                    item['speaker'] = speaker
                self.speaker_busy = False
                self.speaker_button.configure(state='normal')
                self.dirty = True
                self.saved_state.set('● Neuložené úpravy')
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
        self.poll_timer = self.window.after(100, self.poll)

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
        self.window.after_cancel(self.poll_timer)
        self.window.destroy()
        if self.embedded:
            self.app.editor_empty.pack(pady=24)
        return True
