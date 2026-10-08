"""Spoločné moderné rozhranie pre Windows a Linux."""
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk
from tkinter import ttk, messagebox
from window_style import titlebar, rounded_styles

VERSION = '2.1.3b'
AUTHOR = 'Created by Daniel Návojský using Codex | 2026'
PALETTES = {
    'dark': dict(bg='#11151d', card='#191f2a', field='#151b25', text='#eef2fa', muted='#b0bacb', border='#333e50', blue='#92b5ff', accent_text='#111d36', info='#263955', disabled='#30394a'),
    'light': dict(bg='#f4f6fa', card='#ffffff', field='#ffffff', text='#202838', muted='#526076', border='#d7deea', blue='#245bdb', accent_text='#ffffff', info='#e7efff', disabled='#e0e5ee'),
}

from ui_layout import build_ui

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
        app.queue_scroll.pack(side='right', fill='y')
        app.listbox.pack(fill='both', expand=True)
    else:
        app.listbox.pack_forget()
        app.queue_scroll.pack_forget()
        app.empty.pack(fill='both', expand=True)

def apply_theme(app, theme):
    app.theme = theme
    p = PALETTES[theme]
    s = app.style
    app.root.configure(bg=p['bg'])

    s.configure('.', font=(app.font, 10), background=p['bg'], foreground=p['text'], bordercolor=p['border'], lightcolor=p['border'], darkcolor=p['border'], troughcolor=p['field'])
    s.configure('TFrame', background=p['bg'])
    s.configure('Card.TFrame', background=p['card'], relief='flat', borderwidth=0)
    s.configure('Field.TFrame', background=p['field'])
    s.configure('Selected.TFrame', background=p['card'], bordercolor=p['blue'], lightcolor=p['blue'], darkcolor=p['blue'], relief='solid', borderwidth=1)
    for name, bg, fg in [('TLabel', p['bg'], p['text']), ('Muted.TLabel', p['bg'], p['muted']), ('CardMuted.TLabel', p['card'], p['muted']), ('CardBold.TLabel', p['card'], p['text']), ('FieldMuted.TLabel', p['field'], p['muted']), ('Empty.TLabel', p['field'], p['text']), ('Info.TLabel', p['info'], p['muted']), ('Footer.TLabel', p['bg'], p['muted'])]:
        s.configure(name, background=bg, foreground=fg)
    s.configure('Title.TLabel', font=(app.font, 18, 'bold'))
    s.configure('CardBold.TLabel', font=(app.font, 10, 'bold'))
    s.configure('Transcript.TLabel', font=(app.font, 11), background=p['card'], foreground=p['text'])
    s.configure('Empty.TLabel', font=(app.font, 12, 'bold'))
    s.configure('Footer.TLabel', font=(app.font, 9))
    s.configure('TButton', padding=(12, 5), background=p['field'], foreground=p['text'], bordercolor=p['border'], focuscolor=p['blue'])
    s.map('TButton', background=[('disabled', p['disabled']), ('active', p['info'])], foreground=[('disabled', p['muted'])])
    s.configure('Accent.TButton', background=p['blue'], foreground=p['accent_text'], font=(app.font, 10, 'bold'))
    s.map('Accent.TButton', foreground=[('disabled', p['muted']), ('!disabled', p['accent_text'])])
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
    s.map('Treeview', background=[('selected', p['info'])], foreground=[('selected', p['text'])])
    s.map('TNotebook.Tab', background=[('selected', p['field'])], foreground=[('selected', p['blue'])])
    app.root.option_add('*TCombobox*Listbox.background', p['field'])
    app.root.option_add('*TCombobox*Listbox.foreground', p['text'])
    for widget in app.text_widgets:
        widget.configure(bg=p['field'], fg=p['text'], selectbackground=p['blue'], selectforeground='white')
    app.icon.configure(bg=p['bg'])
    app.theme_button.configure(text='Svetlý režim' if theme == 'dark' else 'Tmavý režim')
    rounded_styles(app, p)
    app.root.after_idle(lambda: titlebar(app.root, app.theme == 'dark', PALETTES[app.theme]['bg'], PALETTES[app.theme]['text']))
    for editor in getattr(app, 'editors', []):
        if editor.window.winfo_exists():
            editor.apply_theme()
    if app.model_dialog and app.model_dialog.window.winfo_exists():
        app.model_dialog.window.configure(bg=p['bg'])
    if hasattr(app, 'persist_timer'):
        app.schedule_save()

