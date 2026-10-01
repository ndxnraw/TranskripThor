import os
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import speech_models as sm

class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.messages = []
        self.emit = lambda *a: self.messages.append(a)

    def test_routing(self):
        self.assertEqual(sm.route('sk', 'tiny'), 'tiny')
        self.assertEqual(sm.route('cs', 'tiny'), 'tiny')
        self.assertEqual(sm.route('en', 'small'), 'small')
        self.assertEqual(sm.route(None, 'medium'), 'medium')

    @patch('speech_models.release_memory')
    @patch('speech_models.device', return_value='cpu')
    @patch('speech_models.load_backend')
    def test_reuse_and_language_switch(self, load, *_):
        manager = sm.ModelManager()
        first = manager.get('sk', 'tiny', 'cache', True, self.emit, self.stop)
        self.assertIs(first, manager.get('sk', 'tiny', 'cache', True, self.emit, self.stop))
        self.assertEqual(load.call_count, 1)
        manager.get('cs', 'tiny', 'cache', True, self.emit, self.stop)
        self.assertEqual(load.call_count, 1)
        manager.get('hu', 'small', 'cache', True, self.emit, self.stop)
        self.assertEqual(load.call_count, 2)
        self.assertEqual(load.call_args.args[0], 'small')
        self.assertTrue(load.call_args.args[2])

    @patch('speech_models.release_memory')
    @patch('speech_models.device', return_value='cuda')
    @patch('speech_models.load_backend')
    def test_cuda_load_retry_cpu(self, load, *_):
        load.side_effect = [RuntimeError('CUDA out of memory'), object()]
        sm.ModelManager().get('sk', sm.SLOVAK_MODEL, 'cache', True, self.emit, self.stop)
        self.assertEqual([x.args[3] for x in load.call_args_list], ['cuda', 'cpu'])
        self.assertEqual([x.args[0] for x in load.call_args_list], [sm.SLOVAK_MODEL]*2)

    @patch('speech_models.release_memory')
    @patch('speech_models.device', return_value='cpu')
    @patch('speech_models.load_backend', side_effect=ImportError('torch missing'))
    def test_failed_explicit_selection_does_not_switch_model(self, load, *_):
        with self.assertRaisesRegex(RuntimeError, 'Vybraný model'):
            sm.ModelManager().get('sk', sm.SLOVAK_MODEL, 'cache', True, self.emit, self.stop)
        load.assert_called_once()
        self.assertEqual(load.call_args.args[0], sm.SLOVAK_MODEL)

    @patch('speech_models.release_memory')
    @patch('speech_models.device', return_value='cpu')
    @patch('speech_models.load_backend', side_effect=OSError('not cached'))
    def test_no_model_gives_actionable_error(self, *_):
        with self.assertRaisesRegex(RuntimeError, 'cache.*RAM/VRAM'):
            sm.ModelManager().get('cs', 'tiny', 'cache', True, self.emit, self.stop)

    def test_timestamp_offsets_and_validation(self):
        result = sm.checked_segments([dict(text='Ahoj', start=1, end=3)], 28, 5)
        self.assertEqual((result[0].start, result[0].end), (29, 31))
        for start, end in [(None, 2), (float('nan'), 2), (3, 1)]:
            with self.assertRaises(RuntimeError):
                sm.checked_segments([dict(text='text', start=start, end=end)], 0, 5)

    def test_whisper_offline_arguments(self):
        torch = Mock(float16='fp16', float32='fp32')
        transformers = Mock()
        adapter = sm.SlovakWhisper.__new__(sm.SlovakWhisper)
        adapter.cache, adapter.offline, adapter.model_id, adapter.device = Path('cache'), True, sm.SLOVAK_MODEL, 'cpu'
        with patch.dict(sys.modules, torch=torch, transformers=transformers):
            adapter.load()
        kwargs = transformers.AutoModelForSpeechSeq2Seq.from_pretrained.call_args.kwargs
        self.assertEqual(kwargs['revision'], 'v2.0')
        self.assertEqual(transformers.AutoModelForSpeechSeq2Seq.from_pretrained.call_args.args[0], sm.SLOVAK_MODEL)
        self.assertTrue(kwargs['local_files_only'])
        self.assertFalse(kwargs['trust_remote_code'])
        self.assertEqual(kwargs['torch_dtype'], 'fp32')
        self.assertTrue(transformers.AutoProcessor.from_pretrained.call_args.kwargs['local_files_only'])

    def test_adapter_chunks_cancel_gpu_retry(self):
        import numpy as np
        from faster_whisper import audio, vad
        adapter = sm.LocalAdapter.__new__(sm.LocalAdapter)
        adapter.stop, adapter.device, adapter.model_id = self.stop, 'cuda', sm.SLOVAK_MODEL
        adapter.infer = Mock(side_effect=[RuntimeError('CUDA out of memory'), [dict(text='one', start=0, end=1)], [dict(text='two', start=0, end=1)]])
        adapter.on_cpu = Mock(side_effect=lambda: setattr(adapter, 'device', 'cpu'))
        with patch.object(audio, 'decode_audio', return_value=np.zeros(30*16000, dtype=np.float32)), patch.object(vad, 'get_speech_timestamps', return_value=[{'start':0, 'end':30*16000}]):
            segments, info = adapter.transcribe('file.wav', language='sk')
            result = list(segments)
        self.assertEqual([s.start for s in result], [0, 28])
        self.assertEqual(info.duration, 30)
        adapter.on_cpu.assert_called_once()
        self.assertEqual(adapter.infer.call_count, 3)
        self.stop.set()
        with patch.object(audio, 'decode_audio', return_value=np.zeros(16000)), patch.object(vad, 'get_speech_timestamps') as get_vad:
            self.assertEqual(list(adapter.transcribe('file.wav', language='sk')[0]), [])
            get_vad.assert_not_called()

    def test_explicit_kinit_requires_slovak(self):
        self.assertEqual(sm.route('sk', sm.SLOVAK_MODEL), sm.SLOVAK_MODEL)
        for language in ('hu', 'cs', 'en', None):
            with self.assertRaises(ValueError):
                sm.route(language, sm.SLOVAK_MODEL)
        self.assertEqual(sm.route('hu', 'small'), 'small')

    @patch('speech_models.release_memory')
    @patch('speech_models.device', return_value='cpu')
    @patch('speech_models.load_backend')
    def test_cancel_during_load_is_not_cached(self, load, *_):
        def loaded(*args):
            self.stop.set()
            return object()
        load.side_effect = loaded
        manager = sm.ModelManager()
        with self.assertRaises(InterruptedError):
            manager.get('hu', 'tiny', 'cache', True, self.emit, self.stop)
        self.assertIsNone(manager.model)
        self.assertIsNone(manager.key)

    def test_whisper_word_alignment_preserves_sentence_boundaries(self):
        from contextlib import nullcontext
        adapter = sm.SlovakWhisper.__new__(sm.SlovakWhisper)
        adapter.pipe = Mock(return_value={'text': 'Dobrý deň. Skúška.', 'chunks': [
            {'text': ' Dobrý', 'timestamp': (0.1, 0.6)},
            {'text': ' deň.', 'timestamp': (0.6, 1.2)},
            {'text': ' Skúška.', 'timestamp': (1.4, 2.0)}]})
        with patch.dict(sys.modules, torch=SimpleNamespace(inference_mode=nullcontext)):
            result = adapter.infer([0.] * (3 * sm.SAMPLE_RATE))
        self.assertEqual(result, [dict(text='Dobrý deň.', start=0.1, end=1.2),
                                  dict(text='Skúška.', start=1.4, end=2.0)])
        self.assertEqual(adapter.pipe.call_args.kwargs['return_timestamps'], 'word')

if __name__ == '__main__':
    unittest.main()
