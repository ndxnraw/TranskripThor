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
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = prepis.App(self.root)
        self.app.files = ['recording.wav']

    def tearDown(self):
        self.root.destroy()

    @patch('prepis.threading.Thread')
    def test_hungarian_uses_selected_multilingual_model(self, thread):
        self.assertEqual(self.root.title(), 'ND TranskripThor')
        self.app.language.set('Maďarčina')
        self.app.start()
        self.assertEqual(thread.call_args.kwargs['args'][2:4], ('hu', 'small'))

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
