"""Natívna titulková lišta Windows; na Linuxe ju spravuje desktop."""
import sys
import ctypes

def titlebar(root, dark, background, foreground):
    if sys.platform != 'win32':
        return None
    from ctypes import wintypes
    user = ctypes.windll.user32
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    hwnd = user.GetAncestor(root.winfo_id(), 2)
    signature = (hwnd, dark, background, foreground)
    if getattr(root, '_titlebar_signature', None) == signature:
        return 0
    set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute
    set_attr.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    set_attr.restype = ctypes.c_long
    enabled = ctypes.c_int(int(dark))
    result = set_attr(hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
    if result != 0:
        result = set_attr(hwnd, 19, ctypes.byref(enabled), ctypes.sizeof(enabled))
    for attribute, color in [(35, background), (36, foreground)]:
        value = ctypes.c_uint(int(color[1:3], 16) | int(color[3:5], 16) << 8 | int(color[5:7], 16) << 16)
        set_attr(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    if result == 0:
        root._titlebar_signature = signature
    return result

def rounded_styles(app, palette):
    """Zaoblené deväťdielne pozadia; text zostáva natívny a ostrý."""
    from PIL import Image, ImageDraw, ImageTk
    s = app.style
    if not hasattr(app, 'round_images'):
        app.round_images = []
        for theme in ('dark', 'light'):
            from ui import PALETTES
            p = PALETTES[theme]
            def tile(fill, border):
                im = Image.new('RGBA', (64, 64))
                draw = ImageDraw.Draw(im)
                draw.rounded_rectangle((1, 1, 62, 62), radius=15, fill=fill, outline=border, width=2)
                im = im.resize((32, 32), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                app.round_images.append(photo)
                return photo
            for name, fill in [('Button', p['field']), ('Accent', p['blue']), ('Entry', p['field'])]:
                normal = tile(fill, p['border'] if name != 'Accent' else p['blue'])
                active = tile(p['info'] if name != 'Accent' else '#1568ce', p['blue'])
                disabled = tile(p['disabled'], p['border'])
                s.element_create(f'{theme}.{name}.round', 'image', normal, ('disabled', disabled), ('active', active), border=6, sticky='nsew')
    theme = app.theme
    for style, name in [('TButton', 'Button'), ('Accent.TButton', 'Accent')]:
        s.layout(style, [(f'{theme}.{name}.round', {'sticky':'nsew', 'children': [('Button.focus', {'sticky':'nsew', 'children':[('Button.padding', {'sticky':'nsew', 'children':[('Button.label', {'sticky':'nsew'})]})]})]})])
    s.layout('TEntry', [(f'{theme}.Entry.round', {'sticky':'nsew', 'children':[('Entry.padding', {'sticky':'nsew', 'children':[('Entry.textarea', {'sticky':'nsew'})]})]})])
    s.layout('TCombobox', [(f'{theme}.Entry.round', {'sticky':'nsew', 'children':[('Combobox.downarrow', {'side':'right','sticky':'ns'}), ('Combobox.padding', {'sticky':'nsew', 'children':[('Combobox.textarea', {'sticky':'nsew'})]})]})])
    # Veľké panely vykresľuje Tk natívne; bez dlaždicovania alfa obrázkov.
    s.layout('Panel.TFrame', [('Frame.border', {'sticky': 'nsew'})])
    s.configure('Panel.TFrame', background=palette['card'], relief='flat', borderwidth=0)

