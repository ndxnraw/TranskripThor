"""Compact Studio presentation; transcription remains in the existing worker."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk


class RecordingList(ttk.Treeview):
    """Structured queue with the index selection contract used by App."""
    def __init__(self, parent, scale):
        super().__init__(parent, columns=('name', 'state'), show='headings', height=3, selectmode='extended')
        self.heading('name', text='Nahrávka')
        self.heading('state', text='Stav')
        self.column('name', width=round(500*scale), minwidth=100)
        self.column('state', width=round(150*scale), minwidth=90, stretch=False)

    def curselection(self):
        selected = set(self.selection())
        return tuple(i for i, key in enumerate(self.get_children()) if key in selected)

    def selection_set(self, *indices):
        children = self.get_children()
        super().selection_set([children[int(i)] if isinstance(i, int) else i for i in indices])

    def selection_clear(self, *_):
        self.selection_remove(self.selection())

    def set_items(self, items):
        keys = {item['id'] for item in items}
        for key in self.get_children():
            if key not in keys:
                self.delete(key)
        for index, item in enumerate(items):
            key = item['id']
            values = (Path(item['source']).name, item['state'].capitalize())
            if not self.exists(key):
                self.insert('', 'end', iid=key, values=values, tags=(item['state'],))
            elif tuple(self.item(key, 'values')) != values:
                self.item(key, values=values, tags=(item['state'],))
            self.move(key, '', index)


def build_ui(app, root, languages, models, output, cache):
    from ui import VERSION, AUTHOR, apply_theme, clear_logs
    from window_style import titlebar
    from ui import PALETTES
    root.title('ND TranskripThor')
    scale = max(1, root.winfo_fpixels('1i') / 96)
    app.theme, app.cache = 'dark', cache
    app.style = ttk.Style(root)
    app.style.theme_use('clam')
    app.font = 'Segoe UI'
    app.text_widgets, app.surfaces = [], []
    app.language = tk.StringVar(value='Slovenčina')
    app.quality = tk.StringVar(value=next(iter(models)))
    app.output = tk.StringVar(value=str(output))
    app.offline = tk.BooleanVar(value=False)
    app.autoplay = tk.BooleanVar(value=False)
    footer = ttk.Frame(root, padding=(16, 6))
    footer.pack(side='bottom', fill='x')
    ttk.Label(footer, text=f'Verzia {VERSION}', style='Footer.TLabel').pack(side='left')
    ttk.Label(footer, text=AUTHOR, style='Footer.TLabel').pack(side='right')
    header = ttk.Frame(root, padding=(16, 10))
    header.pack(fill='x')
    with Image.open(Path(__file__).parent/'assets/transkripthor.png') as logo:
        app.logo_image = ImageTk.PhotoImage(logo.resize((round(36*scale), round(36*scale)), Image.Resampling.LANCZOS), master=root)
        app.window_icon = ImageTk.PhotoImage(logo.resize((256, 256)), master=root)
    root.iconphoto(True, app.window_icon)
    app.icon = tk.Label(header, image=app.logo_image, bd=0)
    app.icon.pack(side='left', padx=(0, 12))
    brand = ttk.Frame(header)
    brand.pack(side='left')
    ttk.Label(brand, text='ND TranskripThor', style='Title.TLabel').pack(anchor='w')
    ttk.Label(brand, text='Lokálny prepis • vaše nahrávky zostávajú u vás', style='Muted.TLabel').pack(anchor='w')
    app.theme_button = ttk.Button(header, command=lambda: apply_theme(app, 'light' if app.theme == 'dark' else 'dark'))
    app.theme_button.pack(side='right')
    app.workspace_tabs = ttk.Notebook(root)
    app.workspace_tabs.pack(fill='both', expand=True, padx=16)
    app.pages = {}
    for key, name in [('recordings','Nahrávky'), ('editor','Editor'), ('models','Modely'), ('settings','Nastavenia'), ('details','Podrobnosti spracovania')]:
        page = ttk.Frame(app.workspace_tabs, padding=10)
        app.workspace_tabs.add(page, text=name)
        app.pages[key] = page
    app.editor_page, app.models_page = app.pages['editor'], app.pages['models']
    app.editor_empty = ttk.Label(app.editor_page, text='Vyberte hotovú alebo prerušenú nahrávku a otvorte jej prepis.', style='Muted.TLabel')
    app.editor_empty.pack(pady=24)
    app.workspace_tabs.bind('<<NotebookTabChanged>>', app.page_changed)
    page = app.pages['recordings']
    toolbar = ttk.Frame(page)
    toolbar.pack(fill='x', pady=(0, 8))
    app.add = ttk.Button(toolbar, text='＋ Pridať nahrávky', style='Accent.TButton', command=app.add_files)
    app.add.pack(side='left')
    app.file_count = tk.StringVar()
    ttk.Label(toolbar, textvariable=app.file_count, style='Muted.TLabel').pack(side='right')
    app.drop_hint = tk.StringVar(value='Pridať nahrávky umožňuje vybrať jeden alebo viac súborov.')
    area = ttk.Frame(page, style='Panel.TFrame', padding=8)
    area.pack(fill='both', expand=True)
    app.file_area = area
    ttk.Label(area, textvariable=app.drop_hint, style='CardMuted.TLabel', wraplength=850).pack(fill='x')
    app.listbox = RecordingList(area, scale)
    app.queue_scroll = ttk.Scrollbar(area, command=app.listbox.yview)
    app.listbox.configure(yscrollcommand=app.queue_scroll.set)
    app.listbox.bind('<<TreeviewSelect>>', lambda event: app.update_selection())
    app.listbox.bind('<Double-Button-1>', lambda event: app.context_action())
    app.listbox.bind('<Return>', lambda event: app.context_action())
    app.empty = ttk.Frame(area, style='Field.TFrame', padding=12)
    app.empty.pack(fill='both', expand=True)
    ttk.Label(app.empty, text='Začnite pridaním nahrávky', style='Empty.TLabel').pack(pady=4)
    actions = ttk.Frame(page)
    actions.pack(fill='x', pady=6)
    app.context_button = ttk.Button(actions, text='Otvoriť prepis', command=app.context_action)
    app.context_button.pack(side='left')
    app.editor_button = ttk.Button(actions, text='Editor', command=app.open_editor)
    app.editor_button.pack(side='left', padx=4)
    app.info_button = ttk.Button(actions, text='Podrobnosti', command=app.show_item_info)
    app.info_button.pack(side='left')
    app.remove = ttk.Button(actions, text='Odobrať', command=app.remove_files)
    app.remove.pack(side='left', padx=4)
    app.move_up = ttk.Button(actions, text='↑', width=3, command=lambda: app.move_item(-1))
    app.move_up.pack(side='left')
    app.move_down = ttk.Button(actions, text='↓', width=3, command=lambda: app.move_item(1))
    app.move_down.pack(side='left', padx=4)
    app.new_button = ttk.Button(actions, text='Nový prepis', command=lambda: app.start('new'))
    app.new_button.pack(side='right')
    app.selection_info = tk.StringVar(value='Vyberte nahrávku pre ďalšie možnosti.')
    app.selection_label = ttk.Label(page, textvariable=app.selection_info, style='Muted.TLabel', wraplength=800)
    app.selection_label.pack(fill='x', pady=(0, 6))
    setup = ttk.Frame(page, style='Panel.TFrame', padding=10)
    setup.pack(fill='x')
    ttk.Label(setup, text='Nastavenia čakajúcich nahrávok', style='CardBold.TLabel').pack(anchor='w')
    row = ttk.Frame(setup, style='Card.TFrame')
    row.pack(fill='x', pady=6)
    row.columnconfigure(1, weight=1)
    row.columnconfigure(3, weight=1)
    ttk.Label(row, text='Jazyk', style='CardMuted.TLabel').grid(row=0, column=0, padx=(0, 6))
    app.lang_box = ttk.Combobox(row, textvariable=app.language, values=list(languages), state='readonly', width=18)
    app.lang_box.grid(row=0, column=1, sticky='ew')
    ttk.Label(row, text='Model', style='CardMuted.TLabel').grid(row=0, column=2, padx=8)
    app.model_box = ttk.Combobox(row, textvariable=app.quality, values=list(models), state='readonly', width=22)
    app.model_box.grid(row=0, column=3, sticky='ew')
    from speech_models import DEVICES
    app.device_choice = tk.StringVar(value=next(iter(DEVICES)))
    ttk.Label(row, text='Zariadenie', style='CardMuted.TLabel').grid(row=1, column=0, padx=(0, 6), pady=(6, 0))
    app.device_box = ttk.Combobox(row, textvariable=app.device_choice, values=list(DEVICES), state='readonly', width=24)
    app.device_box.grid(row=1, column=1, columnspan=3, sticky='ew', pady=(6, 0))
    app.offline_box = ttk.Checkbutton(row, text='Iba offline', variable=app.offline)
    app.offline_box.grid(row=0, column=4, padx=(8, 0))
    path = ttk.Frame(setup, style='Card.TFrame')
    path.pack(fill='x')
    ttk.Label(path, text='Uložiť do', style='CardMuted.TLabel').pack(side='left', padx=(0, 8))
    app.output_entry = ttk.Entry(path, textvariable=app.output)
    app.output_entry.pack(side='left', fill='x', expand=True)
    app.browse = ttk.Button(path, text='Vybrať…', command=app.choose_folder)
    app.browse.pack(side='left', padx=(8, 0))
    app.readiness = tk.StringVar()
    app.readiness_label = ttk.Label(page, textvariable=app.readiness, style='Muted.TLabel', wraplength=800)
    app.readiness_label.pack(fill='x', pady=6)
    run = ttk.Frame(page)
    run.pack(fill='x')
    app.start_button = ttk.Button(run, text='Spustiť čakajúce', style='Accent.TButton', command=app.start)
    app.start_button.pack(side='left')
    app.stop_button = ttk.Button(run, text='Zastaviť', command=app.cancel, state='disabled')
    app.stop_button.pack(side='left', padx=8)
    ttk.Button(run, text='Otvoriť výsledky', command=app.open_results).pack(side='right')
    status = ttk.Frame(page, padding=(0, 6, 0, 0))
    status.pack(fill='x')
    app.status = tk.StringVar(value='Pridajte nahrávku a spustite prepis.')
    ttk.Label(status, textvariable=app.status, style='Muted.TLabel', wraplength=900).pack(anchor='w')
    bar = ttk.Frame(status)
    bar.pack(fill='x', pady=3)
    app.progress = ttk.Progressbar(bar, maximum=100)
    app.progress.pack(side='left', fill='x', expand=True)
    app.percent = tk.StringVar(value='0 %')
    ttk.Label(bar, textvariable=app.percent, width=5, anchor='e').pack(side='right')
    app.batch_progress = ttk.Progressbar(status, maximum=100)
    app.batch_progress.pack(fill='x')
    app.timing = tk.StringVar(value='Dávka: 0 % • Čas sa odhadne počas prepisu.')
    app.timing_label = ttk.Label(status, textvariable=app.timing, style='Muted.TLabel')
    app.timing_label.pack(anchor='w')
    app.device_status = tk.StringVar(value='Zariadenie: čaká na načítanie modelu')
    app.device_label = ttk.Label(status, textvariable=app.device_status, style='Muted.TLabel')
    app.device_label.pack(anchor='w')
    settings = app.pages['settings']
    ttk.Label(settings, text='Nastavenia a pomoc', style='Title.TLabel').pack(anchor='w', pady=(8, 16))
    ttk.Checkbutton(settings, text='Automaticky prehrať zvuk pri výbere úseku v editore', variable=app.autoplay).pack(anchor='w', pady=8)
    ttk.Label(settings, text='Jazyk, model, výstupný priečinok a režim offline nastavíte na karte Nahrávky.\nOkno sa vždy otvorí v minimálnej veľkosti. Modely sa sťahujú samostatne; zvuk zostáva lokálny.', style='Muted.TLabel', wraplength=700).pack(anchor='w', pady=12)
    ttk.Button(settings, text='Obnoviť predvolené nastavenia', command=app.reset_settings).pack(anchor='w', pady=8)
    ttk.Label(settings, text='Pokračovať obnoví uložené nastavenia projektu. Nový prepis vytvorí nový priečinok.\nV editore vyberte úsek, upravte text a zvoľte Uložiť TXT/SRT.\nRučná úprava textu zruší presné časovanie slov daného úseku.', style='Muted.TLabel', wraplength=700).pack(anchor='w', pady=12)
    details = app.pages['details']
    app.clear_button = ttk.Button(details, text='Vymazať náhľad a správy', command=lambda: clear_logs(app))
    app.clear_button.pack(anchor='e', pady=(0, 6))
    app.result_tabs = ttk.Notebook(details)
    app.result_tabs.pack(fill='both', expand=True)
    for label, attr in [('Náhľad prepisu', 'preview'), ('Prevádzkové správy', 'activity')]:
        panel = ttk.Frame(app.result_tabs)
        app.result_tabs.add(panel, text=label)
        text = tk.Text(panel, wrap='word', height=4, state='disabled', font=(app.font, 11), relief='flat', padx=12, pady=10)
        scrollbar = ttk.Scrollbar(panel, command=text.yview)
        scrollbar.pack(side='right', fill='y')
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(fill='both', expand=True)
        setattr(app, attr, text)
        app.text_widgets.append(text)
    apply_theme(app, 'dark')
    def resized(event):
        if event.widget == root:
            width = max(200, page.winfo_width()-24)
            app.selection_label.configure(wraplength=width)
            app.readiness_label.configure(wraplength=width)
    root.bind('<Configure>', resized, add='+')
    root.bind('<Map>', lambda event: root.after_idle(lambda: titlebar(root, app.theme == 'dark', PALETTES[app.theme]['bg'], PALETTES[app.theme]['text'])) if event.widget == root else None, add='+')
    root.update_idletasks()
    width = min(round(1040*scale), root.winfo_screenwidth()-40)
    height = min(round(740*scale), root.winfo_screenheight()-80)
    root.minsize(width, height)
    root.geometry(f'{width}x{height}+20+20')
    root.protocol('WM_DELETE_WINDOW', app.close)
    root.after(100, app.poll)
