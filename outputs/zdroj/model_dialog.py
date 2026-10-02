import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from model_catalog import inventory, download, remove_model


class ModelDialog:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Správca modelov')
        self.window.transient(app.root)
        self.window.grab_set()
        scale = max(1,app.root.winfo_fpixels('1i')/96)
        self.window.geometry(f'{min(round(1000*scale),app.root.winfo_screenwidth()-40)}x{min(round(450*scale),app.root.winfo_screenheight()-80)}+20+20')
        from ui import PALETTES
        from window_style import titlebar
        palette = PALETTES[app.theme]
        self.window.configure(bg=palette['bg'])
        self.window.after_idle(lambda: titlebar(self.window,app.theme=='dark',palette['bg'],palette['text']))
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.tree = ttk.Treeview(self.window, columns=('state', 'size', 'description'), height=9)
        self.tree.heading('#0', text='Model')
        for key, text in [('state', 'Lokálne'), ('size', 'Miesto'), ('description', 'Použitie')]:
            self.tree.heading(key, text=text)
        self.tree.column('#0', width=230)
        self.tree.column('state', width=100)
        self.tree.column('size', width=90)
        self.tree.column('description', width=400)
        self.tree.pack(fill='both', expand=True, padx=12, pady=12)
        actions = ttk.Frame(self.window)
        actions.pack(fill='x', padx=12)
        self.buttons = []
        for label, command in [('Stiahnuť', self.download), ('Odstrániť', self.remove), ('Obnoviť', self.refresh)]:
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side='left', padx=4)
            self.buttons.append(button)
        ttk.Button(actions, text='Zastaviť sťahovanie', command=self.stop.set).pack(side='right')
        self.status = tk.StringVar(value='Čítam lokálnu cache…')
        ttk.Label(self.window, textvariable=self.status, wraplength=850).pack(fill='x', padx=12, pady=12)
        self.refresh()
        self.window.after(100, self.poll)

    def run(self, action):
        if self.busy:
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
        if not selected:
            return
        if self.app.offline.get():
            messagebox.showinfo('Iba offline', 'Na stiahnutie modelu vypnite Iba offline v hlavnom okne.', parent=self.window)
            return
        self.run(lambda: download(self.app.cache, selected[0],
                                 lambda kind, value: self.events.put((kind, value)), self.stop))

    def remove(self):
        selected = self.tree.selection()
        if selected and messagebox.askyesno('Odstrániť model', f'Odstrániť lokálne súbory modelu {selected[0]}? Nahrávky a prepisy zostanú zachované.', parent=self.window):
            self.app.models.close()
            self.app.model = None
            self.run(lambda: remove_model(self.app.cache, selected[0]))

    def poll(self):
        if not self.window.winfo_exists():
            return
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'rows':
                self.tree.delete(*self.tree.get_children())
                for row in value:
                    self.tree.insert('', 'end', iid=row['model'], text=row['model'], values=(
                        'Dostupný' if row['available'] else 'Chýba/neúplný', f'{row["size"]/1024**2:.1f} MB', row['description']))
                self.status.set('Lokálna dostupnosť overená. Sťahovanie neposiela nahrávky ani prepisy.')
            elif kind == 'done':
                self.busy = False
                for button in self.buttons:
                    button.configure(state='normal')
            else:
                self.status.set(value)
        self.window.after(100, self.poll)

    def close(self):
        if self.busy:
            self.stop.set()
            self.status.set('Zastavujem po aktuálnom prenose; počkajte, prosím.')
            return
        self.window.destroy()
