"""Spoločné moderné rozhranie pre Windows a Linux."""
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk
from tkinter import ttk, messagebox
from window_style import titlebar, rounded_styles

VERSION = '2.0.2'
AUTHOR = 'Created by Daniel Návojský using Codex | 2026'
PALETTES = {
    'dark': dict(bg='#0c1422', card='#152135', field='#101b2d', text='#edf3ff', muted='#bdcbe0', border='#293a53', blue='#2383ff', info='#172f50', disabled='#344259'),
    'light': dict(bg='#f0f5fc', card='#ffffff', field='#f7f9fd', text='#18263c', muted='#475a78', border='#d9e3f0', blue='#0878ef', info='#e9f3ff', disabled='#dce3ed'),
}

def build_ui(app, root, languages, models, output, cache):
    root.title('ND TranskripThor')
    scale = max(1.0, root.winfo_fpixels('1i') / 96)
    width = min(round(1120 * scale), root.winfo_screenwidth() - 60)
    height = min(round(850 * scale), root.winfo_screenheight() - 90)
    root.geometry(f'{width}x{height}+20+20')
    root.minsize(min(920, width), min(620, height))
    app.theme = 'dark'
    app.style = ttk.Style(root)
    app.style.theme_use('clam')
    app.font = 'Segoe UI' if root.tk.call('tk', 'windowingsystem') == 'win32' else 'DejaVu Sans'
    app.surfaces = []
    app.text_widgets = []
    footer = ttk.Frame(root, padding=(22, 9, 22, 10))
    footer.pack(side='bottom', fill='x')
    ttk.Label(footer, text=f'Verzia {VERSION}', style='Footer.TLabel').pack(side='left')
    ttk.Label(footer, text=AUTHOR, style='Footer.TLabel').pack(side='right')
    outer = ttk.Frame(root, padding=(22, 12, 22, 8))
    outer.pack(fill='both', expand=True)
    header = ttk.Frame(outer)
    header.pack(fill='x', pady=(0, 10))
    logo = Image.open(Path(__file__).resolve().parent / 'assets' / 'transkripthor.png')
    size = round(56 * scale)
    app.logo_image = ImageTk.PhotoImage(logo.resize((size, size), Image.Resampling.LANCZOS), master=root)
    app.window_icon = ImageTk.PhotoImage(logo.resize((256, 256), Image.Resampling.LANCZOS), master=root)
    root.iconphoto(True, app.window_icon)
    icon = tk.Label(header, image=app.logo_image, bd=0)
    icon.pack(side='left', padx=(0, 15))
    app.icon = icon
    titles = ttk.Frame(header)
    titles.pack(side='left', fill='x', expand=True)
    ttk.Label(titles, text='ND TranskripThor', style='Title.TLabel').pack(anchor='w')
    ttk.Label(titles, text='Lokálne spracovanie • bez minútových kvót • TXT a SRT', style='Muted.TLabel').pack(anchor='w', pady=(3, 0))
    app.theme_button = ttk.Button(header, text='Svetlý režim', command=lambda: apply_theme(app, 'light' if app.theme == 'dark' else 'dark'))
    app.theme_button.pack(side='right')
    ttk.Button(header, text='Pomoc', command=lambda: messagebox.showinfo('Pomoc', 'Pridajte nahrávky, vyberte jazyk a model a spustite prepis.\n\nPri prvom použití sa vybraný model stiahne z internetu. KInIT je samostatná voľba iba pre slovenčinu (približne 6,2 GB). Pre ostatné jazyky použite Small, Medium, Large v3 alebo Tiny. Nahrávky sa nikam neodosielajú. Potom môžete používať režim Iba offline.\n\nVýsledky sa ukladajú do TXT a SRT. Zastavenie počká na aktuálny krok a zachová rozpracovaný text.')).pack(side='right', padx=8)

    workspace = ttk.Notebook(outer)
    workspace.pack(fill='both', expand=True)
    app.workspace_tabs = workspace
    processing = ttk.Frame(workspace, padding=(0, 8, 0, 0))
    workspace.add(processing, text='Fronta a spracovanie')
    log_page = ttk.Frame(workspace, padding=(0, 8, 0, 0))
    workspace.add(log_page, text='Náhľad a správy')

    def card():
        frame = ttk.Frame(processing, style='Panel.TFrame', padding=10)
        frame.pack(fill='x', pady=(0, 8))
        return frame

    files = card()
    files.pack_configure(fill='both', expand=True)
    toolbar = ttk.Frame(files, style='Card.TFrame')
    toolbar.pack(fill='x')
    app.add = ttk.Button(toolbar, text='＋  Pridať nahrávky', style='Accent.TButton', command=app.add_files)
    app.add.pack(side='left')
    app.remove = ttk.Button(toolbar, text='Odobrať vybrané', command=app.remove_files)
    app.remove.pack(side='left', padx=10)
    ttk.Button(toolbar, text='↑', width=3, command=lambda: app.move_item(-1)).pack(side='left')
    ttk.Button(toolbar, text='↓', width=3, command=lambda: app.move_item(1)).pack(side='left', padx=3)
    ttk.Button(toolbar, text='Editor výsledku', command=app.open_editor).pack(side='left', padx=6)
    ttk.Button(toolbar, text='Modely', command=app.manage_models).pack(side='left')
    app.file_count = tk.StringVar(value='0 nahrávok')
    ttk.Label(toolbar, textvariable=app.file_count, style='CardMuted.TLabel').pack(side='right')
    area = ttk.Frame(files, style='Field.TFrame', padding=1)
    area.pack(fill='both', expand=True, pady=(12, 0))
    app.file_area = area
    app.listbox = tk.Listbox(area, selectmode='extended', height=2, font=(app.font, 10), relief='flat', bd=0, highlightthickness=0, activestyle='none')
    app.listbox.bind('<Double-Button-1>', lambda event: app.open_editor())
    app.empty = ttk.Frame(area, style='Field.TFrame', padding=5)
    app.empty.pack(fill='both', expand=True)
    ttk.Label(app.empty, text='Pridajte zvukové súbory', style='Empty.TLabel').pack(pady=(5, 5))
    ttk.Label(app.empty, text='Pretiahnite súbory do okna alebo kliknite na „Pridať nahrávky“', style='FieldMuted.TLabel').pack()


    options = card()
    options.columnconfigure(0, weight=1)
    options.columnconfigure(1, weight=1)
    options.columnconfigure(2, weight=2)
    ttk.Label(options, text='Jazyk nahrávky', style='CardBold.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 6))
    ttk.Label(options, text='Model', style='CardBold.TLabel').grid(row=0, column=1, sticky='w', padx=(14, 0), pady=(0, 6))
    app.language = tk.StringVar(value='Slovenčina')
    app.quality = tk.StringVar(value=next(iter(models)))
    app.lang_box = ttk.Combobox(options, textvariable=app.language, values=list(languages), state='readonly', width=18)
    app.lang_box.grid(row=1, column=0, sticky='ew')
    app.model_box = ttk.Combobox(options, textvariable=app.quality, values=list(models), state='readonly', width=29)
    app.model_box.grid(row=1, column=1, sticky='ew', padx=(14, 14))
    app.offline = tk.BooleanVar(value=False)
    app.offline_box = ttk.Checkbutton(options, text='Iba offline — už stiahnutý model', variable=app.offline)
    app.offline_box.grid(row=0, column=2, sticky='w')
    ttk.Label(options, text='Model sa pri prvom použití stiahne.\nZvukové súbory sa nikam neodosielajú.', style='Info.TLabel', padding=9).grid(row=1, column=2, sticky='ew')
    path = ttk.Frame(options, style='Card.TFrame')
    path.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(8, 0))
    ttk.Label(path, text='Uložiť do:', style='CardBold.TLabel').pack(side='left', padx=(0, 14))
    app.output = tk.StringVar(value=str(output))
    app.output_entry = ttk.Entry(path, textvariable=app.output)
    app.output_entry.pack(side='left', fill='x', expand=True)
    app.browse = ttk.Button(path, text='Vybrať…', command=app.choose_folder)
    app.browse.pack(side='left', padx=(10, 0))

    actions = ttk.Frame(processing)
    actions.pack(fill='x', pady=(0, 8))
    app.start_button = ttk.Button(actions, text='▶  Spustiť prepis', style='Accent.TButton', command=app.start)
    app.start_button.pack(side='left')
    app.stop_button = ttk.Button(actions, text='■  Zastaviť', command=app.cancel, state='disabled')
    app.stop_button.pack(side='left', padx=10)
    ttk.Button(actions, text='Opakovať / pokračovať', command=lambda: app.start('retry')).pack(side='left')
    ttk.Button(actions, text='Nový od začiatku', command=lambda: app.start('new')).pack(side='left', padx=6)
    ttk.Button(actions, text='Otvoriť výsledky', command=app.open_results).pack(side='right')
    status = card()
    app.status = tk.StringVar(value='Pridajte nahrávky a spustite prepis.')
    ttk.Label(status, textvariable=app.status, style='CardMuted.TLabel', wraplength=1400).pack(anchor='w', pady=(2, 4))
    progress_row = ttk.Frame(status, style='Card.TFrame')
    progress_row.pack(fill='x')
    app.progress = ttk.Progressbar(progress_row, maximum=100)
    app.progress.pack(side='left', fill='x', expand=True)
    app.percent = tk.StringVar(value='0 %')
    ttk.Label(progress_row, textvariable=app.percent, style='CardMuted.TLabel', width=6, anchor='e').pack(side='right', padx=(10, 0))
    app.batch_progress = ttk.Progressbar(status, maximum=100)
    app.batch_progress.pack(fill='x', pady=(6, 0))
    app.timing = tk.StringVar(value='Dávka: 0 % • Odhad času sa zobrazí po začiatku prepisu.')
    details = ttk.Frame(status, style='Card.TFrame')
    details.pack(fill='x')
    app.timing_label = ttk.Label(details, textvariable=app.timing, style='CardMuted.TLabel')
    app.timing_label.pack(side='left')
    app.device_status = tk.StringVar(value='Zariadenie: čaká na načítanie modelu')
    app.device_label = ttk.Label(details, textvariable=app.device_status, style='CardMuted.TLabel')
    app.device_label.pack(side='right')

    logs = ttk.Frame(log_page, style='Panel.TFrame', padding=10)
    logs.pack(fill='both', expand=True)
    log_toolbar = ttk.Frame(logs, style='Card.TFrame')
    log_toolbar.pack(fill='x', pady=(0, 6))
    ttk.Label(log_toolbar, text='Výsledky prepisu', style='CardBold.TLabel').pack(side='left')
    app.clear_button = ttk.Button(log_toolbar, text='Vymazať záznam', command=lambda: clear_logs(app))
    app.clear_button.pack(side='right')
    ttk.Button(log_toolbar, text='Predvolené nastavenia', command=app.reset_settings).pack(side='right', padx=6)
    tabs = ttk.Notebook(logs)
    app.result_tabs = tabs
    tabs.pack(fill='both', expand=True)
    for label, attr in [('Prepis — náhľad', 'preview'), ('Prevádzkové správy', 'activity')]:
        panel = ttk.Frame(tabs, style='Field.TFrame')
        tabs.add(panel, text=label)
        text = tk.Text(panel, wrap='word', height=4, font=(app.font, 10), state='disabled', relief='flat', padx=12, pady=10, highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel, command=text.yview)
        scrollbar.pack(side='right', fill='y')
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(fill='both', expand=True)
        setattr(app, attr, text)
        app.text_widgets.append(text)
    app.cache = cache
    apply_theme(app, 'dark')
    root.bind('<Map>', lambda event: root.after_idle(lambda: titlebar(root, app.theme == 'dark', PALETTES[app.theme]['bg'], PALETTES[app.theme]['text'])) if event.widget == root else None, add='+')
    root.update_idletasks()
    # Minimálna veľkosť odvodená od skutočných metrík písma a ovládania.
    root.minsize(min(root.winfo_screenwidth()-40, outer.winfo_reqwidth()),
                 min(root.winfo_screenheight()-80, outer.winfo_reqheight() + footer.winfo_reqheight()))
    minimum_width, minimum_height = root.minsize()
    root.geometry(f'{minimum_width}x{minimum_height}+20+20')
    root.protocol('WM_DELETE_WINDOW', app.close)
    root.after(100, app.poll)

def clear_logs(app):
    for widget in app.text_widgets:
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.configure(state='disabled')

def update_files(app):
    count = len(app.files)
    app.file_count.set(f'{count} ' + ('nahrávka' if count == 1 else 'nahrávky' if 2 <= count <= 4 else 'nahrávok'))
    if count:
        app.empty.pack_forget()
        app.listbox.pack(fill='both', expand=True)
    else:
        app.listbox.pack_forget()
        app.empty.pack(fill='both', expand=True)

def apply_theme(app, theme):
    app.theme = theme
    p = PALETTES[theme]
    s = app.style
    app.root.configure(bg=p['bg'])

    s.configure('.', font=(app.font, 10), background=p['bg'], foreground=p['text'], bordercolor=p['border'], troughcolor=p['field'])
    s.configure('TFrame', background=p['bg'])
    s.configure('Card.TFrame', background=p['card'], relief='flat', borderwidth=0)
    s.configure('Field.TFrame', background=p['field'])
    for name, bg, fg in [('TLabel', p['bg'], p['text']), ('Muted.TLabel', p['bg'], p['muted']), ('CardMuted.TLabel', p['card'], p['muted']), ('CardBold.TLabel', p['card'], p['text']), ('FieldMuted.TLabel', p['field'], p['muted']), ('Empty.TLabel', p['field'], p['text']), ('Info.TLabel', p['info'], p['muted']), ('Footer.TLabel', p['bg'], p['muted'])]:
        s.configure(name, background=bg, foreground=fg)
    s.configure('Title.TLabel', font=(app.font, 25, 'bold'))
    s.configure('CardBold.TLabel', font=(app.font, 10, 'bold'))
    s.configure('Empty.TLabel', font=(app.font, 12, 'bold'))
    s.configure('Footer.TLabel', font=(app.font, 9))
    s.configure('TButton', padding=(12, 5), background=p['field'], foreground=p['text'], bordercolor=p['border'], focuscolor=p['blue'])
    s.map('TButton', background=[('disabled', p['disabled']), ('active', p['info'])], foreground=[('disabled', p['muted'])])
    s.configure('Accent.TButton', background=p['blue'], foreground='white', font=(app.font, 10, 'bold'))
    s.map('Accent.TButton', background=[('disabled', p['disabled']), ('active', '#1568ce')], foreground=[('disabled', p['muted']), ('!disabled', 'white')])
    for name in ['TEntry', 'TCombobox']:
        s.configure(name, fieldbackground=p['field'], foreground=p['text'], background=p['field'], arrowcolor=p['muted'], padding=4, insertcolor=p['text'])
        s.map(name, fieldbackground=[('disabled', p['card']), ('readonly', p['field'])], foreground=[('disabled', p['muted']), ('readonly', p['text'])])
    s.configure('TCheckbutton', background=p['card'], foreground=p['text'])
    s.map('TCheckbutton', background=[('active', p['card'])], foreground=[('disabled', p['muted'])])
    s.configure('Horizontal.TProgressbar', background=p['blue'], troughcolor=p['field'], borderwidth=0, thickness=10)
    s.configure('TNotebook', background=p['card'], borderwidth=0)
    s.configure('TNotebook.Tab', background=p['card'], foreground=p['muted'], padding=(14, 8))
    s.configure('Treeview', background=p['field'], fieldbackground=p['field'], foreground=p['text'], rowheight=round(24 * app.root.winfo_fpixels('1i') / 96))
    s.configure('Treeview.Heading', background=p['card'], foreground=p['text'])
    s.map('Treeview', background=[('selected', p['blue'])], foreground=[('selected', 'white')])
    s.map('TNotebook.Tab', background=[('selected', p['field'])], foreground=[('selected', p['blue'])])
    app.root.option_add('*TCombobox*Listbox.background', p['field'])
    app.root.option_add('*TCombobox*Listbox.foreground', p['text'])
    for widget in [app.listbox] + app.text_widgets:
        widget.configure(bg=p['field'], fg=p['text'], selectbackground=p['blue'], selectforeground='white')
    app.icon.configure(bg=p['bg'])
    app.theme_button.configure(text='Svetlý režim' if theme == 'dark' else 'Tmavý režim')
    rounded_styles(app, p)
    app.root.after_idle(lambda: titlebar(app.root, app.theme == 'dark', PALETTES[app.theme]['bg'], PALETTES[app.theme]['text']))
    for editor in getattr(app, 'editors', []):
        if editor.window.winfo_exists():
            editor.apply_theme()
    if hasattr(app, 'persist_timer'):
        app.schedule_save()

