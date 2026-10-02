import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tkinter as tk
import prepis
from speech_models import SLOVAK_MODEL


class InterfaceTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = prepis.App(self.root, self.state.name)
        self.app.files = ['recording.wav']

    def tearDown(self):
        self.root.update_idletasks()
        for identifier in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(identifier)
        self.root.destroy()
        self.state.cleanup()

    @patch('prepis.threading.Thread')
    def test_hungarian_uses_selected_multilingual_model(self, thread):
        self.assertEqual(self.root.title(), 'ND TranskripThor')
        self.app.language.set('Maďarčina')
        self.app.start()
        self.assertEqual(thread.call_args.kwargs['args'][2:4], ('hu', 'small'))

    @patch('prepis.threading.Thread')
    def test_mixed_mode_uses_selected_model(self, thread):
        self.app.language.set('Čeština + slovenčina')
        self.app.start()
        self.assertEqual(thread.call_args.kwargs['args'][2:4], ('cs-sk', 'small'))

    @patch('prepis.threading.Thread')
    def test_slovak_does_not_force_kinit(self, thread):
        self.app.start()
        self.assertEqual(thread.call_args.kwargs['args'][2:4], ('sk', 'small'))

    @patch('prepis.messagebox.showinfo')
    @patch('prepis.threading.Thread')
    def test_kinit_language_validation_before_start(self, thread, dialog):
        self.app.quality.set(next(k for k, v in prepis.MODELS.items() if v == SLOVAK_MODEL))
        self.app.language.set('Maďarčina')
        self.app.start()
        thread.assert_not_called()
        dialog.assert_called_once()
        self.assertFalse(self.app.busy)
        self.app.language.set('Slovenčina')
        self.app.start()
        self.assertEqual(thread.call_args.kwargs['args'][2:4], ('sk', SLOVAK_MODEL))


class ExportTest(unittest.TestCase):
    @patch('prepis.transcribe_mixed')
    def test_mixed_export_keeps_languages_and_timestamps(self, mixed):
        mixed.return_value = (iter([SimpleNamespace(text='Zítra.', start=0, end=2),
            SimpleNamespace(text='Dobre.', start=127.5, end=131.1)]),
            SimpleNamespace(language='cs-sk', duration=140))
        model = Mock()
        with tempfile.TemporaryDirectory() as folder:
            target, complete = prepis.transcribe_file(model, 'audio.wav', folder, 'cs-sk',
                                                      threading.Event(), Mock())
            self.assertTrue(complete)
            self.assertEqual((target / 'prepis.txt').read_text(encoding='utf-8-sig'), 'Zítra.\nDobre.\n')
            self.assertIn('00:02:07,500 --> 00:02:11,100',
                          (target / 'titulky.srt').read_text(encoding='utf-8-sig'))
        model.transcribe.assert_not_called()

    def test_decode_failure_preserves_partial_output(self):
        def segments():
            yield SimpleNamespace(text='Prvá veta.', start=0, end=1)
            raise RuntimeError('Poškodená nahrávka')
        model = Mock()
        model.transcribe.return_value = (segments(), SimpleNamespace(language='sk', duration=2))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, 'Poškodená'):
                prepis.transcribe_file(model, 'audio.wav', folder, 'sk', threading.Event(), lambda *a: None)
            partial = next(Path(folder).rglob('prepis.partial.txt'))
            self.assertIn('Prvá veta.', partial.read_text(encoding='utf-8-sig'))
            self.assertFalse(list(Path(folder).rglob('prepis.txt')))


if __name__ == '__main__':
    unittest.main()
