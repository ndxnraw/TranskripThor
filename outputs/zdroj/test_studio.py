import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from prepis import App
from editor import Editor
from jobs import job_settings
from project import Project
from ui import apply_theme


def destroy_window(root):
    root.update_idletasks()
    def descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from descendants(child)
    widgets = list(descendants(root))
    for timer in root.tk.splitlist(root.tk.call('after', 'info')):
        command = root.tk.call('after', 'info', timer)[0]
        owner = next((widget for widget in widgets if command in (widget._tclCommands or [])), root)
        owner.after_cancel(timer)
    root.destroy()


class StudioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, self.folder/'state')

    def tearDown(self):
        destroy_window(self.root)
        self.temp.cleanup()

    def recording(self):
        path = self.folder/'ukážka.wav'
        path.write_bytes(b'audio')
        self.app.accept_files([str(path)])
        self.app.listbox.selection_set(0)
        return self.app.items[0]

    def project(self, count=85):
        folder = self.folder/'project'
        with Project(folder, create=True) as project:
            project.initialize(self.folder/'ukážka.wav', {}, job_settings('medium', 'cs-sk'), [], count*32000)
            project.commit_chunk(0, [dict(start=i*2, end=i*2+1, text=f'Text {i}.', words=[dict(start=i*2,end=i*2+1,word='Text')], speaker='', language='cs' if i%2 else 'sk') for i in range(count)], 'sk')
        return str(folder)

    def test_new_requires_selection(self):
        self.recording()
        self.app.listbox.selection_clear()
        with patch('prepis.threading.Thread') as thread, patch('prepis.messagebox.showinfo'):
            self.app.start('new')
        thread.assert_not_called()

    def test_resume_uses_project_settings_without_changing_new_job_settings(self):
        item = self.recording()
        item.update(state='prerušené', project=self.project())
        with patch('prepis.threading.Thread') as thread:
            self.app.context_action()
        self.assertEqual(thread.call_args.kwargs['args'][2:4], ('cs-sk', 'medium'))
        self.assertEqual(self.app.language.get(), 'Slovenčina')
        self.assertEqual(self.app.quality.get(), 'Small – vyvážený')
        self.assertEqual(self.app.resume_settings['segmentation'], job_settings('medium','cs-sk')['segmentation'])

    def test_offline_missing_model_does_not_start_worker(self):
        self.recording()
        self.app.cache = self.folder/'no-models'
        self.app.offline.set(True)
        with patch('prepis.threading.Thread') as thread, patch('prepis.messagebox.showinfo') as info:
            self.app.start()
        self.assertFalse(self.app.busy)
        thread.assert_not_called()
        info.assert_called_once()
        self.assertEqual(self.app.workspace_tabs.select(), str(self.app.models_page))

    def test_queue_selection_survives_updates(self):
        item = self.recording()
        item.update(state='prerušené', project=self.project())
        self.app.refresh_queue()
        self.assertEqual(self.app.listbox.curselection(), (0,))
        self.assertEqual(self.app.context_button['text'], 'Pokračovať')
        self.assertEqual(self.app.listbox.item(item['id'], 'values')[1], 'Prerušené')

    def test_autoplay_preference_persists_and_resets(self):
        self.app.autoplay.set(True)
        self.app.save_state()
        self.app.autoplay.set(False)
        self.app.restore_settings()
        self.assertTrue(self.app.autoplay.get())
        self.app.reset_settings()
        self.assertFalse(self.app.autoplay.get())

    def test_download_indicator_does_not_change_transcription_progress(self):
        self.app.events.put(('download_state', True))
        self.app.events.put(('status', 'Sťahujem model: cache rastie'))
        self.app.poll()
        self.assertEqual(str(self.app.progress['mode']), 'indeterminate')
        self.assertEqual(self.app.percent.get(), '…')
        self.assertEqual(self.app.file_progress, 0)
        self.app.events.put(('download_state', False))
        self.app.poll()
        self.assertEqual(str(self.app.progress['mode']), 'determinate')
        self.assertEqual(self.app.percent.get(), '0 %')

    @patch('editor.Editor.load_audio')
    def test_inline_edits_paging_search_theme_and_explicit_playback(self, _load):
        editor = Editor(self.app, self.project(), parent=self.app.editor_page)
        self.app.editors.append(editor)
        self.app.workspace_tabs.select(self.app.editor_page)
        editor.player.audio = object()
        editor.tree.selection_set('0')
        with patch.object(editor, 'play_segment') as play:
            editor.select()
            play.assert_not_called()
            self.app.autoplay.set(True)
            editor.select()
            play.assert_called_once()
        editor.text.delete('1.0','end')
        editor.text.insert('1.0','Opravené slová.')
        editor.change_page(1)
        self.assertTrue(editor.dirty)
        self.assertEqual(editor.segments[0]['words'], [])
        for theme in ('light','dark'):
            apply_theme(self.app, theme)
        editor.query.set('Text 8')
        editor.search()
        self.assertIn(84, editor.matches)
        editor.next_match()
        self.assertEqual(editor.current, 8)
        editor.next_match()
        self.assertEqual(editor.current, 80)
        self.assertTrue(editor.save())
        with Project(editor.folder) as project:
            rows = project.segments()
        self.assertEqual(len(rows),85)
        self.assertEqual(rows[0]['text'],'Opravené slová.')
        self.assertEqual((rows[0]['start'],rows[0]['end']),(0,1))
        editor.player.audio = None
        editor.close()

    @patch('model_dialog.inventory', return_value=[])
    def test_model_delete_is_blocked_while_transcribing(self, _inventory):
        from model_dialog import ModelDialog
        with patch('model_dialog.threading.Thread'):
            dialog = ModelDialog(self.app, parent=self.app.models_page)
        dialog.busy = False
        dialog.tree.insert('', 'end', iid='small', text='Small')
        dialog.tree.selection_set('small')
        self.app.busy = True
        with patch('model_dialog.remove_model') as remove, patch('model_dialog.messagebox.askyesno') as ask:
            dialog.remove()
        remove.assert_not_called()
        ask.assert_not_called()
        self.assertIn('používa', dialog.status.get())


class StudioScalingTest(unittest.TestCase):
    @patch('editor.Editor.load_audio')
    def test_editor_settings_models_fit_both_themes_and_scales(self, _load):
        from tkinter import ttk
        from model_dialog import ModelDialog
        for scale in (1,1.25,1.5,1.75,2):
            with tempfile.TemporaryDirectory() as folder:
                root = tk.Tk()
                try:
                    root.tk.call('tk','scaling',96/72*scale)
                    app = App(root, folder)
                    target = Path(folder)/'project'
                    with Project(target, create=True) as project:
                        project.initialize('ukážka.wav',{}, {}, [], 32000)
                        project.commit_chunk(0,[dict(start=0,end=1,text='Čitateľný úsek. '*20,words=[],speaker='',language='sk')],'sk')
                    editor = Editor(app, str(target), parent=app.editor_page)
                    app.editors.append(editor)
                    with patch('model_dialog.threading.Thread'):
                        app.model_dialog = ModelDialog(app, parent=app.models_page)
                    editor.tree.selection_set('0')
                    editor.select()
                    editor.toggle_details()
                    for theme in ('dark','light'):
                        apply_theme(app, theme)
                        for page in ('recordings','editor','models','settings','details'):
                            app.workspace_tabs.select(app.pages[page])
                            root.update()
                            def inspect(widget):
                                if isinstance(widget, ttk.Button):
                                    self.assertTrue(widget.winfo_ismapped(), (scale,page,widget['text']))
                                    self.assertGreaterEqual(widget.winfo_width()+2,widget.winfo_reqwidth(),(scale,page,widget['text']))
                                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),root.winfo_rooty()+root.winfo_height(),(scale,page,widget['text']))
                                for child in widget.winfo_children():
                                    inspect(child)
                            inspect(app.pages[page])
                finally:
                    destroy_window(root)
