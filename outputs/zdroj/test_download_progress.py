import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from download_progress import DownloadMonitor, cache_bytes
from model_catalog import download


class DownloadProgressTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder/'blobs').mkdir()
        self.now = 0
        self.events = []
        self.stop = threading.Event()
        self.monitor = DownloadMonitor(self.folder, 'large-v3', lambda k,v:self.events.append((k,v)), self.stop, lambda:self.now)

    def tearDown(self):
        self.temp.cleanup()

    def test_bytes_advance_while_file_counter_stays_three_of_five(self):
        self.monitor.file_count(3,5)
        (self.folder/'blobs/weights.incomplete').write_bytes(b'x'*1024**2)
        self.now = 2
        self.monitor.report()
        text = self.events[-1][1]
        self.assertIn('3/5',text)
        self.assertIn('1.0 MB',text)
        self.assertIn('Zápis 0.5 MB/s',text)
        self.assertNotIn('%',text)

    def test_waiting_does_not_claim_active_transfer(self):
        self.now = 35
        self.monitor.report()
        self.assertIn('Bez nových dát 35 s',self.events[-1][1])
        self.assertNotIn('Zápis',self.events[-1][1])

    def test_resumed_cache_is_not_newly_transferred(self):
        (self.folder/'blobs/weights.incomplete').write_bytes(b'x'*1024**2)
        monitor = DownloadMonitor(self.folder,'small',lambda k,v:self.events.append((k,v)),self.stop,lambda:self.now)
        self.now = 4
        monitor.report()
        self.assertIn('1.0 MB (+0.0 MB',self.events[-1][1])
        (self.folder/'blobs/weights.incomplete').rename(self.folder/'blobs/weights')
        self.assertEqual(cache_bytes(self.folder),1024**2)

    def test_stop_message_and_thread_cleanup_on_failure(self):
        with self.assertRaises(ValueError):
            with self.monitor:
                self.stop.set()
                self.monitor.report()
                raise ValueError('server failure')
        self.assertFalse(self.monitor.thread.is_alive())
        self.assertIn('Zastavujem',self.events[-2][1])
        self.assertEqual(self.events[-1],('download_state',False))

    def test_windows_cache_without_symlinks_keeps_completed_bytes(self):
        incomplete = self.folder/'blobs/weights.incomplete'
        incomplete.write_bytes(b'x'*1024)
        snapshot = self.folder/'snapshots/revision'
        snapshot.mkdir(parents=True)
        incomplete.rename(snapshot/'model.bin')
        self.assertEqual(cache_bytes(self.folder),1024)

    def test_catalog_uses_supervised_transport(self):
        with patch('download_transport.supervise') as worker:
            download(self.folder,'small',self.events.append,self.stop)
        worker.assert_called_once_with(self.folder,'small',self.events.append,self.stop)
