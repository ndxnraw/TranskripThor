import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from speech_models import ModelManager, GPUError, DEVICES, load_backend
from jobs import job_settings, transcribe_job
from project import Project
from state import StateStore


class DeviceTest(unittest.TestCase):
    def test_setting_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StateStore(folder)
            for value in (None, 'auto', [], 'cpu', 'cuda'):
                store.save('settings.json', {'device': value})
                self.assertEqual(store.settings([], []).get('device', 'cpu'), value if value in ('cpu', 'cuda') else 'cpu')

    @patch('speech_models.release_memory')
    @patch('speech_models.device', return_value='cuda')
    @patch('speech_models.load_backend', side_effect=lambda *a: object())
    def test_cpu_default_gpu_success_switch_and_reuse(self, load, detect, _):
        manager = ModelManager()
        args = ('sk', 'tiny', 'cache', True, Mock(), threading.Event())
        cpu = manager.get(*args)
        detect.assert_not_called()
        self.assertEqual(load.call_args.args[3], 'cpu')
        gpu = manager.get(*args, 'cuda')
        self.assertIsNot(cpu, gpu)
        self.assertIs(gpu, manager.get(*args, 'cuda'))
        manager.get(*args, 'cpu')
        self.assertEqual([c.args[3] for c in load.call_args_list], ['cpu', 'cuda', 'cpu'])

    @patch('speech_models.release_memory')
    def test_unavailable_and_load_dll_failure_never_auto_fallback(self, _):
        for available, error in [('cpu', None), ('cuda', RuntimeError('Library cublas64_12.dll is not found'))]:
            with patch('speech_models.device', return_value=available), patch('speech_models.load_backend', side_effect=error) as load:
                manager = ModelManager()
                with self.assertRaises(GPUError):
                    manager.get('sk', 'tiny', 'cache', True, Mock(), threading.Event(), 'cuda')
                self.assertIsNone(manager.model)
                self.assertEqual(load.call_count, int(available == 'cuda'))

    def test_faster_whisper_compute_types(self):
        with patch('faster_whisper.WhisperModel') as load:
            for device, dtype in [('cpu', 'int8'), ('cuda', 'float16')]:
                load_backend('tiny', 'cache', True, device, Mock(), threading.Event())
                self.assertEqual(load.call_args.kwargs['compute_type'], dtype)
                self.assertEqual(load.call_args.kwargs['device'], device)

    def test_lazy_failure_retry_only_unfinished_chunk_and_cancel_resume(self):
        for mixed in (False, True):
            for accepted in (True, False):
                with self.subTest(mixed=mixed, accepted=accepted), tempfile.TemporaryDirectory() as folder:
                    source, target = Path(folder)/'a.wav', Path(folder)/'out'
                    source.write_bytes(b'audio')
                    stop, emit = threading.Event(), Mock()
                    gpu, cpu = Mock(), Mock()
                    for model in (gpu, cpu):
                        model.detect_language.return_value = ('sk', .95, [('sk', .95), ('cs', .05)])
                    calls = []
                    def segments(text):
                        yield SimpleNamespace(text=text, start=.1, end=1, words=[], language='sk')
                    def failed():
                        yield from segments('NEULOŽIŤ')
                        raise RuntimeError('Library cublas64_12.dll is not found')
                    def infer(model, *args, **kwargs):
                        calls.append(model)
                        items = segments('Prvý' if len(calls) == 1 else 'Druhý') if model is cpu or len(calls) == 1 else failed()
                        return items, SimpleNamespace(language='sk')
                    gpu.transcribe.side_effect = lambda *a, **k: infer(gpu, *a, **k)
                    cpu.transcribe.side_effect = lambda *a, **k: infer(cpu, *a, **k)
                    def recover(exc):
                        self.assertIn('cublas64_12.dll', str(exc))
                        if not accepted:
                            raise InterruptedError('Zrušené')
                        return cpu
                    settings = job_settings('tiny', 'cs-sk' if mixed else 'sk')
                    with patch('faster_whisper.audio.decode_audio', return_value=np.zeros(20*16000)), \
                         patch('faster_whisper.vad.get_speech_timestamps', return_value=[dict(start=0,end=6*16000),dict(start=10*16000,end=16*16000)]):
                        args = (gpu, source, target, settings, stop, emit)
                        if accepted:
                            self.assertTrue(transcribe_job(*args, recover_gpu=recover, selected_device='cuda'))
                        else:
                            with self.assertRaises(InterruptedError):
                                transcribe_job(*args, recover_gpu=recover, selected_device='cuda')
                            with Project(target) as project:
                                self.assertEqual(project.get('next_chunk'), 1)
                                self.assertEqual([s['text'] for s in project.segments()], ['Prvý'])
                            self.assertTrue(transcribe_job(cpu, source, target, settings, stop, emit, resume=True, selected_device='cpu'))
                    self.assertEqual(calls, [gpu, gpu, cpu])
                    with Project(target) as project:
                        self.assertEqual([s['text'] for s in project.segments()], ['Prvý', 'Druhý'])
                        self.assertAlmostEqual(project.segments()[1]['start'], 10.1)
                    self.assertEqual((target/'prepis.txt').read_text(encoding='utf-8-sig'), 'Prvý\nDruhý\n')


class DeviceInterfaceTest(unittest.TestCase):
    def test_loading_fallback_confirmation_and_cancel(self):
        from prepis import App
        for accepted in (True, False):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as folder:
                app = App.__new__(App)
                app.stop = threading.Event()
                app.cache = folder
                app.models = ModelManager()
                app.batch_ids = ['one']
                app.batch_mode = 'pending'
                app.resume_settings = None
                app.items = [dict(id='one', source='audio.wav', state='čaká', project='', error='')]
                records = []
                def receive(event):
                    kind, value = event
                    records.append(event)
                    if kind == 'cpu_request':
                        ack, answer = value
                        answer.append(accepted)
                        ack.set()
                    elif kind == 'job':
                        _, changes, ack, result = value
                        app.items[0].update(changes)
                        result.append(True)
                        ack.set()
                app.events = SimpleNamespace(put=receive)
                cpu = SimpleNamespace(model=SimpleNamespace(device='cpu'))
                with patch('model_catalog.ensure_model'), patch('model_catalog.cached_path', return_value=Path('revision')), \
                     patch('speech_models.device', return_value='cuda'), patch('speech_models.release_memory'), \
                     patch('speech_models.load_backend', side_effect=[RuntimeError('cublas64_12.dll missing'), cpu]) as load, \
                     patch('prepis.transcribe_job', return_value=True) as job:
                    app.work(['audio.wav'], folder, 'sk', 'tiny', True, 'cuda')
                self.assertEqual([c.args[3] for c in load.call_args_list], ['cuda', 'cpu'] if accepted else ['cuda'])
                self.assertEqual(job.call_count, int(accepted))
                self.assertEqual(app.stop.is_set(), not accepted)
                self.assertTrue(any(k == 'log' and 'cublas64_12.dll' in v for k, v in records))
                if accepted:
                    self.assertIn(('device', 'CPU'), records)

    def test_choice_persistence_no_load_and_disabled_during_work(self):
        import tkinter as tk
        from prepis import App
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            app = App(root, folder)
            try:
                self.assertEqual(DEVICES[app.device_choice.get()], 'cpu')
                with patch.object(app.models, 'get') as get, patch.object(app.models, 'close') as close:
                    app.device_choice.set(list(DEVICES)[1])
                    close.assert_called_once()
                    get.assert_not_called()
                app.save_state()
                app.restore_settings()
                self.assertEqual(DEVICES[app.device_choice.get()], 'cuda')
                app.files = ['a.wav']
                project_folder = Path(folder)/'project'
                with Project(project_folder, create=True) as project:
                    project.initialize('a.wav', {}, job_settings('tiny', 'cs'), [], 0)
                app.items[0].update(state='prerušené', project=str(project_folder))
                with patch('prepis.threading.Thread') as thread:
                    app.start('retry', identifiers=[app.items[0]['id']])
                    self.assertEqual(thread.call_args.kwargs['args'][-1], 'cuda')
                    self.assertEqual(thread.call_args.kwargs['args'][2:4], ('cs', 'tiny'))
                    self.assertEqual(str(app.device_box['state']), 'disabled')
                for accepted in (False, True):
                    app.stop.clear()
                    ack, answer = threading.Event(), []
                    app.events.put(('cpu_request', (ack, answer)))
                    with patch.object(app, 'confirm_cpu', return_value=accepted):
                        app.poll()
                    self.assertTrue(ack.is_set())
                    self.assertEqual(answer, [accepted])
                self.assertEqual(DEVICES[app.device_choice.get()], 'cpu')
                app.events.put(('finished', None))
                app.poll()
                self.assertEqual(str(app.device_box['state']), 'readonly')
            finally:
                for timer in root.tk.splitlist(root.tk.call('after', 'info')):
                    root.after_cancel(timer)
                root.destroy()
