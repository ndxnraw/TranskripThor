import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import mixed_language as ml
from speech_models import ModelManager


def segment(language, score=-0.2):
    return SimpleNamespace(start=0.1, end=1.5, text=language, avg_logprob=score,
        tokens=[1, 2], words=[SimpleNamespace(start=0.2, end=1.2, word=language, probability=0.9)])


class MixedTest(unittest.TestCase):
    def run_audio(self, probs, durations=None, scores=None, gaps=None, stop=None):
        durations = durations or [6] * len(probs)
        gaps = gaps or [1] * len(probs)
        spans, cursor = [], 0
        for duration, gap in zip(durations, gaps):
            spans.append(dict(start=round(cursor * ml.SAMPLE_RATE),
                              end=round((cursor + duration) * ml.SAMPLE_RATE)))
            cursor += duration + gap
        audio = np.zeros(round(cursor * ml.SAMPLE_RATE), dtype=np.float32)
        model = Mock()
        model.detect_language.side_effect = [('pl', 0.99, list(p.items())) for p in probs]
        def transcribe(chunk, **kwargs):
            index = model.detect_language.call_count - 1
            language = kwargs['language']
            value = scores[index][language] if scores else -0.2
            return iter([segment(language, value)]), None
        model.transcribe.side_effect = transcribe
        with patch('faster_whisper.audio.decode_audio', return_value=audio), \
             patch('faster_whisper.vad.get_speech_timestamps', return_value=spans):
            result, info = ml.transcribe_mixed(model, 'fixture.wav', stop or threading.Event(),
                                             word_timestamps=True)
            result = list(result)
        for call in model.transcribe.call_args_list:
            self.assertEqual(call.kwargs['task'], 'transcribe')
            self.assertFalse(call.kwargs['vad_filter'])
            self.assertFalse(call.kwargs['condition_on_previous_text'])
            self.assertTrue(np.shares_memory(audio, call.args[0]))
        return result, model, info

    def test_monolingual_and_switching(self):
        for languages in [('cs', 'cs'), ('sk', 'sk'), ('cs', 'sk'), ('sk', 'cs'), ('cs', 'sk', 'cs')]:
            with self.subTest(languages=languages):
                probs = [{language: 0.9, ('sk' if language == 'cs' else 'cs'): 0.05} for language in languages]
                result, model, _ = self.run_audio(probs)
                self.assertEqual([s.language for s in result], list(languages))
                self.assertEqual([s.text for s in result], list(languages))
                self.assertEqual(model.detect_language.call_count, len(languages))
                self.assertEqual(model.transcribe.call_count, len(languages))

    def test_ambiguous_double_pass_and_other_language_ignored(self):
        result, model, _ = self.run_audio([{'cs': 0.48, 'sk': 0.46}],
                                        scores=[{'cs': -0.7, 'sk': -0.2}])
        self.assertEqual(result[0].language, 'sk')
        self.assertEqual(result[0].language_confidence, 0.46)
        self.assertEqual(model.transcribe.call_count, 2)

    def test_low_confidence_triggers_double_pass(self):
        _, model, _ = self.run_audio([{'cs': 0.4, 'sk': 0.01}])
        self.assertEqual(model.transcribe.call_count, 2)

    def test_short_tie_uses_previous_but_clear_switch_wins(self):
        result, _, _ = self.run_audio([{'sk': 0.9, 'cs': 0.05},
            {'cs': 0.48, 'sk': 0.46}, {'cs': 0.95, 'sk': 0.02}], durations=[6, 2, 2])
        self.assertEqual([s.language for s in result], ['sk', 'sk', 'cs'])

    def test_short_fallback_strong_score_overrides_previous(self):
        result, _, _ = self.run_audio([{'sk': 0.9}, {'cs': 0.48, 'sk': 0.46}],
            durations=[6, 2], scores=[{'sk': -0.2}, {'cs': -0.1, 'sk': -0.8}])
        self.assertEqual([s.language for s in result], ['sk', 'cs'])

    def test_silence_and_word_timestamp_offsets(self):
        result, _, info = self.run_audio([{'cs': 0.9}, {'sk': 0.9}], gaps=[119.4, 0])
        self.assertAlmostEqual(result[1].start, 125.5)
        self.assertAlmostEqual(result[1].end, 126.9)
        self.assertAlmostEqual(result[1].words[0].start, 125.6)
        self.assertAlmostEqual(result[1].words[0].end, 126.6)
        self.assertAlmostEqual(info.duration, 131.4)
        self.assertEqual([s.id for s in result], [0, 1])

    def test_segmentation_merge_split_no_overlap(self):
        spans = [dict(start=0, end=2*16000), dict(start=round(2.2*16000), end=6*16000),
                 dict(start=10*16000, end=71*16000)]
        chunks = list(ml.speech_chunks(spans, 71*16000, ml.MixedConfig()))
        self.assertEqual(chunks[0], (0, 6*16000))
        self.assertEqual(chunks[-1][1], 71*16000)
        self.assertTrue(all(5 <= (b-a)/16000 <= 25 for a, b in chunks))
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(chunks, chunks[1:])))

    def test_empty_silence_and_cancellation(self):
        result, model, _ = self.run_audio([])
        self.assertEqual(result, [])
        model.detect_language.assert_not_called()
        stop = threading.Event()
        stop.set()
        result, model, _ = self.run_audio([{'cs': 0.9}], stop=stop)
        self.assertEqual(result, [])
        model.transcribe.assert_not_called()

    def test_nonempty_silent_audio(self):
        model = Mock()
        with patch('faster_whisper.audio.decode_audio', return_value=np.zeros(16000)), \
             patch('faster_whisper.vad.get_speech_timestamps', return_value=[]):
            segments, _ = ml.transcribe_mixed(model, 'silence.wav', threading.Event())
            self.assertEqual(list(segments), [])
        model.detect_language.assert_not_called()

    def test_offsets_do_not_mutate_candidates(self):
        original = segment('sk')
        result = ml.offset_segment(original, 125.4, 6, 'sk', 0.91)
        self.assertEqual(original.start, 0.1)
        self.assertEqual(original.words[0].start, 0.2)
        self.assertAlmostEqual(result.start, 125.5)

    @patch('speech_models.release_memory')
    @patch('speech_models.device', return_value='cpu')
    @patch('speech_models.load_backend')
    def test_model_reused_in_mixed_mode(self, load, *_):
        manager = ModelManager()
        args = ('small', 'cache', True, Mock(), threading.Event())
        model = manager.get('sk', *args)
        self.assertIs(manager.get(ml.MIXED_LANGUAGE, *args), model)
        self.assertIs(manager.get(ml.MIXED_LANGUAGE, *args), model)
        load.assert_called_once()

    def test_invalid_config_and_score(self):
        for kwargs in [dict(max_speech_segment_duration=31), dict(language_confidence_threshold=2),
                       dict(score_tie_threshold=float('nan'))]:
            with self.assertRaises(ValueError):
                ml.MixedConfig(**kwargs)
        self.assertEqual(ml.transcription_score([]), float('-inf'))


if __name__ == '__main__':
    unittest.main()
