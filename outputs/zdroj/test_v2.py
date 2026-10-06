import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np

from state import StateStore, ProgressClock, queue_item
from project import Project, fingerprint
from jobs import transcribe_job, job_settings
from subtitles import SubtitleOptions, cues, render_srt, normalized


class PersistenceTest(unittest.TestCase):
    def test_process_crash_rolls_back_partial_checkpoint(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            with Project(folder,create=True) as project:
                project.initialize('audio',{}, {}, [[0,10],[10,20]],20)
                project.commit_chunk(0,[dict(start=0,end=1,text='Bezpečné.')],'sk')
            code = ('import sqlite3,sys,os; c=sqlite3.connect(sys.argv[1]); '
                    'c.execute("BEGIN IMMEDIATE"); '
                    'c.execute("INSERT INTO segments VALUES (99, ?)",(\'{"text":"neúplné"}\',)); '
                    'c.execute("UPDATE metadata SET value=\'2\' WHERE key=\'next_chunk\'"); os._exit(7)')
            completed = subprocess.run([sys.executable,'-c',code,str(Path(folder)/'projekt.sqlite3')],capture_output=True)
            self.assertEqual(completed.returncode,7,completed.stderr)
            with Project(folder) as project:
                self.assertEqual(project.get('next_chunk'),1)
                self.assertEqual([s['text'] for s in project.segments()],['Bezpečné.'])

    def test_settings_corruption_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StateStore(folder)
            self.assertEqual(store.settings(['sk'], ['small']), {})
            store.save('settings.json', dict(language='sk', model='small', theme='light', offline=True, geometry='1200x800+10+10'))
            self.assertEqual(store.settings(['sk'], ['small'])['theme'], 'light')
            (Path(folder)/'settings.json').write_text('{broken')
            self.assertEqual(store.settings(['sk'], ['small']), {})
            self.assertTrue(store.warning)
            self.assertTrue(list(Path(folder).glob('*.damaged-*')))
            store.save('settings.json', dict(language=[], theme=0, offline='false'))
            self.assertEqual(store.settings(['sk'], ['small']), {})

    def test_queue_restart_order_states(self):
        with tempfile.TemporaryDirectory() as folder:
            store = StateStore(folder)
            items = [queue_item('a.wav'), queue_item('b.wav')]
            items[0]['state'] = 'spracúva sa'
            items[1]['state'] = 'hotovo'
            store.save('queue.json', items)
            restored = StateStore(folder).queue()
            self.assertEqual([i['id'] for i in restored], [i['id'] for i in items])
            self.assertEqual([i['state'] for i in restored], ['prerušené', 'hotovo'])

    def test_eta_requires_real_samples(self):
        clock = ProgressClock(0)
        clock.update(0, 30)
        clock.update(.1, 35)
        self.assertIsNone(clock.remaining(35))
        clock.update(.2, 40)
        self.assertAlmostEqual(clock.remaining(40), 40)

    def test_atomic_checkpoint_and_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'a.wav'
            source.write_bytes(b'original')
            digest = fingerprint(source)
            with Project(Path(folder)/'out', create=True) as project:
                project.initialize(source, digest, {'model':'small'}, [[0,16000]], 16000)
                project.commit_chunk(0, [dict(start=0,end=1,text='Ahoj.',words=[])], 'sk')
                with self.assertRaises(ValueError):
                    project.commit_chunk(0, [], 'sk')
            with Project(Path(folder)/'out') as project:
                self.assertEqual(project.get('next_chunk'), 1)
                self.assertEqual(len(project.segments()), 1)
                project.verify(digest, {'model':'small'})
                with self.assertRaises(ValueError):
                    project.verify(digest, {'model':'tiny'})
                source.write_bytes(b'changed!')
                with self.assertRaises(ValueError):
                    project.verify(fingerprint(source), {'model':'small'})


class ResumeTest(unittest.TestCase):
    def test_stop_resume_no_duplicate_or_missing_chunk(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'audio.wav'
            source.write_bytes(b'fixture')
            out = Path(folder)/'result'
            stop = threading.Event()
            model = Mock()
            model.transcribe.return_value = (iter([]), SimpleNamespace(language='cs'))
            calls = []
            def infer(audio, **kwargs):
                calls.append(len(audio))
                return iter([SimpleNamespace(start=.1,end=1,text='Zítra.', words=[], language='cs')]), SimpleNamespace(language='cs')
            model.transcribe.side_effect = infer
            def emit(kind, value):
                if kind == 'segment':
                    stop.set()
            audio = np.zeros(20*16000, dtype=np.float32)
            spans = [dict(start=0,end=6*16000),dict(start=10*16000,end=16*16000)]
            settings = job_settings('small','cs')
            with patch('faster_whisper.audio.decode_audio', return_value=audio), \
                 patch('faster_whisper.vad.get_speech_timestamps', return_value=spans):
                self.assertFalse(transcribe_job(model, source, out, settings, stop, emit))
                stop.clear()
                self.assertTrue(transcribe_job(model, source, out, settings, stop, Mock(), resume=True))
            self.assertEqual(len(calls), 2)
            with Project(out) as project:
                segments = project.segments()
                self.assertEqual(len(segments), 2)
                self.assertAlmostEqual(segments[1]['start'], 10.1)
                self.assertTrue(project.get('complete'))
            self.assertIn('00:00:10,100', (out/'titulky.srt').read_text(encoding='utf-8-sig'))

    def test_decoder_failure_does_not_commit_partial_chunk(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'audio.wav'
            source.write_bytes(b'a')
            out = Path(folder)/'out'
            def failed():
                yield SimpleNamespace(start=0,end=1,text='Nesmie zostať.',words=[])
                raise RuntimeError('decoder failed')
            model = Mock()
            model.transcribe.return_value = (failed(), SimpleNamespace(language='sk'))
            with patch('faster_whisper.audio.decode_audio', return_value=np.zeros(6*16000)), \
                 patch('faster_whisper.vad.get_speech_timestamps', return_value=[dict(start=0,end=6*16000)]):
                with self.assertRaisesRegex(RuntimeError, 'decoder failed'):
                    transcribe_job(model, source, out, job_settings('small','sk'), threading.Event(), Mock())
            with Project(out) as project:
                self.assertEqual(project.get('next_chunk'), 0)
                self.assertEqual(project.segments(), [])


class SubtitleTest(unittest.TestCase):
    def test_split_preserves_every_word_and_nonoverlap(self):
        text = 'Toto je prvá veta. Potom príde ďalšia dlhšia veta.'
        words = [dict(start=i, end=i+.8, word=word) for i, word in enumerate(text.split())]
        result, _ = cues([dict(start=0,end=len(words),text=text,words=words)], SubtitleOptions(16,1,.5,3))
        self.assertEqual(normalized(' '.join(c['text'] for c in result)), text)
        self.assertTrue(all(a['end'] <= b['start'] for a,b in zip(result,result[1:])))
        self.assertTrue(all(c['start'] < c['end'] for c in result))

    def test_no_word_alignment_keeps_original_times(self):
        text = 'Dlhý text bez časových značiek slov zostáva celý a nestráca žiadne slová.'
        result, warnings = cues([dict(start=10,end=30,text=text,words=[])], SubtitleOptions(15,1,1,5))
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['start'], result[0]['end']), (10,30))
        self.assertEqual(normalized(result[0]['text']), text)
        self.assertTrue(warnings)

    def test_invalid_and_fully_overlapping_intervals_rejected(self):
        for segments in [[dict(start=2,end=1,text='x')],
                         [dict(start=0,end=4,text='a'),dict(start=1,end=2,text='b')]]:
            with self.assertRaises(ValueError):
                render_srt(segments)

    def test_editor_save_preserves_timestamps_and_original_export(self):
        with tempfile.TemporaryDirectory() as folder:
            with Project(folder,create=True) as project:
                project.initialize('a.wav',{}, {}, [[0,100]],100)
                project.commit_chunk(0,[dict(start=1,end=3,text='Pôvodné.',words=[])],'sk')
                project.finish()
                project.export()
                edited = project.segments()
                edited[0]['text'] = 'Opravené.'
                project.edit(edited)
                project.export(corrected=True)
            self.assertIn('Pôvodné.', (Path(folder)/'prepis.txt').read_text(encoding='utf-8-sig'))
            self.assertIn('00:00:01,000 --> 00:00:03,000', (Path(folder)/'titulky.opravene.srt').read_text(encoding='utf-8-sig'))


class OptionalAndModelTest(unittest.TestCase):
    def test_voice_clustering_has_no_language_dependency(self):
        from speakers import cluster
        labels = cluster([np.array([1.,0.]), np.array([0.,1.]), np.array([1.,0.]), None])
        self.assertEqual(labels,['Hovoriaci 1','Hovoriaci 2','Hovoriaci 1','Neurčený hovoriaci'])

    def test_evaluation_reports_errors_and_language_time(self):
        from evaluate_mixed import metrics
        reference = [dict(start=0,end=2,text='Zítra to pošleme.',language='cs'),
                     dict(start=2,end=4,text='Dobre potom.',language='sk')]
        hypothesis = [dict(start=0,end=2,text='Zítra pošleme.',language='cs'),
                      dict(start=2,end=4,text='Dobre potom.',language='cs')]
        result = metrics(reference,hypothesis,8,4)
        self.assertEqual(result['wer'], .2)
        self.assertEqual(result['language_time_accuracy'], .5)
        self.assertEqual(result['real_time_factor'], 2)

    def test_cache_validation_and_offline_error(self):
        from model_catalog import cached_path, cache_folder, ensure_model, remove_model
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'offline'):
                ensure_model(folder,'small',True,Mock(),threading.Event())
            base = cache_folder(folder,'small')
            snapshot = base/'snapshots'/'abc'
            snapshot.mkdir(parents=True)
            (base/'refs').mkdir()
            (base/'refs'/'main').write_text('abc')
            for name in ['config.json','model.bin','tokenizer.json']:
                (snapshot/name).write_bytes(b'{}' if name.endswith('.json') else b'test')
            self.assertEqual(cached_path(folder,'small'),snapshot)
            remove_model(folder,'small')
            self.assertFalse(base.exists())
            with self.assertRaises(ValueError):
                remove_model(folder,'../../unsafe')

    def test_pause_seek_and_playback_callback(self):
        from playback import Player
        import sys
        audio = np.ones(16000,dtype=np.float32)
        player = Player()
        player.audio = audio
        device = Mock()
        class Stop(Exception):
            pass
        device.CallbackStop = Stop
        with patch.dict(sys.modules, sounddevice=device):
            player.play(.5,.6)
            callback = device.OutputStream.call_args.kwargs['callback']
            output = np.zeros((800,1),dtype=np.float32)
            callback(output,800,None,None)
            self.assertEqual(player.position,8800)
            self.assertTrue(np.all(output==1))
            player.pause()
            device.OutputStream.return_value.close.assert_called_once()
        player.close()
        self.assertIsNone(player.audio)
