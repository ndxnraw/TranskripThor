import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from model_catalog import inventory, download, remove_model


class ModelDialog:
    def __init__(self, app, parent=None):
        self.app = app
        self.embedded = parent is not None
        self.window = tk.Frame(parent) if self.embedded else tk.Toplevel(app.root)
        if self.embedded:
            self.window.pack(fill='both', expand=True)
        else:
            self.window.title('Správca modelov')
            self.window.transient(app.root)
            self.window.protocol('WM_DELETE_WINDOW', self.close)
        scale = max(1,app.root.winfo_fpixels('1i')/96)
        if not self.embedded:
            self.window.geometry(f'{min(round(1000*scale),app.root.winfo_screenwidth()-40)}x{min(round(450*scale),app.root.winfo_screenheight()-80)}+20+20')
        from ui import PALETTES
        from window_style import titlebar
        palette = PALETTES[app.theme]
        self.window.configure(bg=palette['bg'])
        if not self.embedded:
            self.window.after_idle(lambda: titlebar(self.window,app.theme=='dark',palette['bg'],palette['text']))
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        ttk.Label(self.window, text='Modely v tomto počítači', style='Title.TLabel').pack(anchor='w', padx=12, pady=12)
        self.tree = ttk.Treeview(self.window, columns=('state', 'size'), height=9)
        self.tree.heading('#0', text='Model')
        for key, text in [('state', 'Lokálne'), ('size', 'Miesto')]:
            self.tree.heading(key, text=text)
        self.tree.column('#0', width=round(400*scale))
        self.tree.column('state', width=round(150*scale), stretch=False)
        self.tree.column('size', width=round(100*scale), stretch=False)
        self.tree.pack(fill='both', expand=True, padx=12, pady=12)
        self.description = tk.StringVar(value='Vyberte model. Bežný prepis nevyžaduje model na rozlíšenie hlasov.')
        self.description_label = ttk.Label(self.window, textvariable=self.description, wraplength=800, style='Muted.TLabel')
        self.description_label.pack(fill='x', padx=12, pady=8)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        actions = ttk.Frame(self.window)
        actions.pack(fill='x', padx=12)
        self.buttons = []
        for label, command in [('Stiahnuť', self.download), ('Odstrániť', self.remove), ('Obnoviť', self.refresh)]:
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side='left', padx=4)
            self.buttons.append(button)
        ttk.Button(actions, text='Zastaviť sťahovanie', command=self.stop.set).pack(side='right')
        self.progress = ttk.Progressbar(self.window, mode='indeterminate')
        self.progress.pack(fill='x', padx=12, pady=(8, 0))
        self.status = tk.StringVar(value='Čítam lokálnu cache…')
        ttk.Label(self.window, textvariable=self.status, wraplength=850).pack(fill='x', padx=12, pady=12)
        self.refresh()
        self.poll_timer = self.window.after(100, self.poll)

    def select(self, _event=None):
        from model_catalog import DESCRIPTIONS, SPEAKER_MODEL
        selected = self.tree.selection()
        key = selected[0] if selected else ''
        self.description.set(DESCRIPTIONS.get(key, 'Vyberte konkrétny model.'))
        if key == SPEAKER_MODEL:
            self.description.set(self.description.get() + ' Voliteľné; nepozná skutočnú identitu osoby. CC BY 4.0, bez tokenu.')

    def in_use(self):
        return self.app.busy or any(e.window.winfo_exists() and e.speaker_busy for e in self.app.editors)

    def run(self, action):
        if self.busy or self.in_use():
            self.status.set('Počkajte na dokončenie prepisu alebo rozlíšenia hlasov.')
            return
        self.busy = True
        self.stop.clear()
        for button in self.buttons:
            button.configure(state='disabled')
        def worker():
            try:
                action()
                self.events.put(('rows', inventory(self.app.cache)))
            except Exception as exc:
                self.events.put(('status', str(exc)))
            finally:
                self.events.put(('done', None))
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        self.run(lambda: None)

    def download(self):
        selected = self.tree.selection()
        if not selected or selected[0].startswith('group:'):
            return
        if self.app.offline.get():
            messagebox.showinfo('Iba offline', 'Na stiahnutie modelu vypnite Iba offline v hlavnom okne.', parent=self.window)
            return
        self.run(lambda: download(self.app.cache, selected[0],
                                 lambda kind, value: self.events.put((kind, value)), self.stop))

    def remove(self):
        if self.busy or self.in_use():
            self.status.set('Model sa práve používa. Najprv zastavte spracovanie.')
            return
        selected = self.tree.selection()
        if selected and not selected[0].startswith('group:') and messagebox.askyesno('Odstrániť model', f'Odstrániť lokálne súbory modelu {selected[0]}? Nahrávky a prepisy zostanú zachované.', parent=self.window):
            self.app.models.close()
            self.app.model = None
            self.run(lambda: remove_model(self.app.cache, selected[0]))

    def poll(self):
        if not self.window.winfo_exists():
            return
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'download_state':
                self.progress.stop()
                if value:
                    self.progress.start(20)
            elif kind == 'rows':
                self.tree.delete(*self.tree.get_children())
                from model_catalog import SPEAKER_MODEL
                from prepis import MODELS
                names = {value: name for name, value in MODELS.items()}
                self.tree.insert('', 'end', iid='group:asr', text='Prepis reči', open=True)
                self.tree.insert('', 'end', iid='group:speakers', text='Voliteľné rozlíšenie hlasov', open=True)
                for row in value:
                    self.tree.insert('group:speakers' if row['model'] == SPEAKER_MODEL else 'group:asr', 'end', iid=row['model'], text=names.get(row['model'], 'WeSpeaker'), values=(
                        'Dostupný' if row['available'] else 'Chýba/neúplný', f'{row["size"]/1024**2:.1f} MB'))
                self.status.set('Lokálna dostupnosť overená. Sťahovanie neposiela nahrávky ani prepisy.')
            elif kind == 'done':
                self.progress.stop()
                self.busy = False
                for button in self.buttons:
                    button.configure(state='normal')
                self.app.update_readiness()
            else:
                self.status.set(value)
        self.poll_timer = self.window.after(100, self.poll)

    def close(self):
        if self.busy:
            self.stop.set()
            self.status.set('Zastavujem po aktuálnom prenose; počkajte, prosím.')
            return
        self.window.after_cancel(self.poll_timer)
        self.window.destroy()
