import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from prepis import App
from file_drop import create_root, FileDrop


class FileDropTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.root = create_root()
        self.root.withdraw()
        self.app = App(self.root, self.folder/'state')
        self.paths = [self.folder/name for name in ('Prvá nahrávka č ď.wav', '音声 druhá.mp3')]
        for path in self.paths:
            path.write_bytes(b'fixture')

    def tearDown(self):
        self.root.update_idletasks()
        for timer in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(timer)
        self.root.destroy()
        self.tmp.cleanup()

    def data(self, paths):
        # Ask Tcl to serialize its own list, including escaping and Unicode.
        return self.root.tk.call('format', '%s', self.root.tk.call('list', *map(str, paths)))

    def drop(self, data, widget=None):
        return self.app.file_drop.drop(SimpleNamespace(data=data, widget=widget or self.app.empty))

    def test_tcl_paths_dedup_picker_and_invalid(self):
        self.assertEqual(self.drop(self.data(self.paths)), 'copy')
        self.assertEqual(len(self.app.items), 2)
        with patch('prepis.filedialog.askopenfilenames', return_value=[str(self.paths[0]).upper(), str(self.paths[1])]):
            self.app.add_files()
        self.assertEqual(len(self.app.items), 2)
        self.assertIn('duplicity: 2', self.app.status.get())
        self.assertEqual(self.drop(self.data([self.folder, self.folder/'missing.wav'])), 'refuse_drop')
        self.assertIn('2', self.app.status.get())
        self.assertFalse(self.app.busy)
        self.assertTrue(all(p.read_bytes() == b'fixture' for p in self.paths))

    def test_malformed_busy_and_handler_failure(self):
        for data in ('{broken', '', None, 123):
            self.assertEqual(self.drop(data), 'refuse_drop')
        self.app.busy = True
        self.assertEqual(self.drop(self.data(self.paths)), 'refuse_drop')
        self.assertIn('Počas prepisu', self.app.status.get())
        self.assertEqual(self.app.items, [])
        self.app.busy = False
        with patch.object(self.app, 'accept_files', side_effect=OSError('fixture')):
            self.assertEqual(self.drop(self.data(self.paths)), 'refuse_drop')

    def test_tcl_registered_targets_dispatch_exactly_once(self):
        self.assertTrue(self.root.tk.call('package', 'present', 'tkdnd'))
        self.assertNotIn(self.root, self.app.file_drop.targets)
        expected = [self.app.file_area, self.app.empty, self.app.listbox, *self.app.empty.winfo_children()]
        for widget in expected:
            self.assertIn(widget, self.app.file_drop.targets)
            self.assertIn('CF_HDROP', self.root.tk.call('bind', str(widget), '<<DropTargetTypes>>'))
            script = self.root.tk.call('bind', str(widget), '<<Drop>>')
            # Dispatch through the Tcl binding and tkinterdnd2's substitution
            # machinery. This is NOT a native Explorer/OLE drag test.
            command = self.root.tk.splitlist(script)[0]
            data = self.data(self.paths)
            with patch.object(self.app, 'accept_files', wraps=self.app.accept_files) as accept:
                result = self.root.tk.call(command, 'copy', 'copy', '1', '', '', '', '', data,
                    '<<Drop>>', '', '', '', 'DND_Files', 'DND_Files', '', str(widget), '1', '1')
                self.assertEqual(result, 'copy')
                accept.assert_called_once()
        self.assertEqual(len(self.app.items), 2)

    def test_missing_dnd_keeps_picker(self):
        self.root.dnd_failure = 'fixture tkdnd load failure'
        failed = FileDrop(self.app)
        self.assertEqual(failed.targets, [])
        self.assertIn('nie je dostupné', self.app.drop_hint.get())
        with patch('prepis.filedialog.askopenfilenames', return_value=list(map(str, self.paths))):
            self.app.add_files()
        self.assertEqual(len(self.app.items), 2)
        self.assertIn('fixture tkdnd', (self.folder/'state/dnd.log').read_text(encoding='utf-8'))

    def test_public_constructor_failure_falls_back_to_plain_tk(self):
        with patch('tkinterdnd2.TkinterDnD._require', side_effect=RuntimeError('DLL fixture')):
            fallback = create_root()
        try:
            self.assertTrue(fallback.winfo_exists())
            self.assertIn('DLL fixture', fallback.dnd_failure)
        finally:
            fallback.destroy()
