"""Small local HTTP fixtures exercise the real Hub HTTP stream inside a child."""
import hashlib
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from download_transport import supervise, DownloadLimits
from download_worker import safe_error, verify_file, IntegrityError
from model_catalog import cached_path, cache_folder, SLOVAK_MODEL, SPEAKER_MODEL, complete_snapshot


def fixture_worker(cache,model,connection):
    # Test-only metadata routing; the underlying HTTP stream, locks, integrity
    # validation, process watchdog and on-disk resume are production code.
    from huggingface_hub import file_download as fd
    import huggingface_hub as hub
    from download_worker import run_download
    spec=json.loads((Path(cache)/'fixture.json').read_text())
    files={name:bytes.fromhex(data) for name,data in spec['files'].items()}
    sha='a'*40
    siblings=[SimpleNamespace(rfilename=name,size=len(data),blob_id=hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest(),lfs=SimpleNamespace(sha256=hashlib.sha256(data).hexdigest()) if not name.endswith('.json') else None) for name,data in files.items()]
    class Api:
        def model_info(self,*args,**kwargs):return SimpleNamespace(sha=sha,siblings=siblings)
    def get(repo,name,**kwargs):
        from huggingface_hub import constants
        assert constants.HF_HUB_DISABLE_XET and not constants.HF_HUB_ENABLE_HF_TRANSFER
        root=cache_folder(cache,model)
        dest=root/'snapshots'/sha/name
        if dest.exists():return str(dest)
        blob=root/'blobs'/hashlib.sha256(files[name]).hexdigest()
        blob.parent.mkdir(parents=True,exist_ok=True)
        with fd.WeakFileLock(str(blob)+'.lock'):
            if not blob.exists():
                partial=blob.with_suffix('.incomplete')
                with partial.open('ab') as stream:
                    fd.http_get(spec['url']+'/'+name,stream,resume_size=stream.tell(),expected_size=len(files[name]),displayed_filename=name)
                fd._chmod_and_move(partial,blob)
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(blob,dest)
        return str(dest)
    with patch.object(hub,'HfApi',Api),patch.object(hub,'hf_hub_download',get):
        run_download(cache,model,connection)


def stuck_worker(cache,model,connection):
    connection.send(dict(kind='progress',phase=model,file='fixture.bin',bytes=0,total=100))
    while True:
        connection.send(dict(kind='progress',phase=model,file='fixture.bin',bytes=0,total=100))
        time.sleep(.1)


def verifying_worker(cache,model,connection):
    for i in range(10):
        connection.send(dict(kind='progress',phase='verify',file='fixture.bin',bytes=i,total=10))
        time.sleep(.15)
    connection.send(dict(kind='complete'))
    connection.close()


class TransferTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cache=Path(self.temp.name)
        self.events=[]
        self.stop=threading.Event()
        self.files={'config.json':b'{}','tokenizer.json':b'{}','model.bin':b'01234567'*131072}
        self.requests=[]
        self.mode='normal'
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                name=self.path.lstrip('/')
                data=owner.files[name]
                start=int(self.headers.get('Range','bytes=0-').split('=')[1].split('-')[0])
                owner.requests.append((name,start))
                self.send_response(206 if start else 200)
                self.send_header('Content-Length',str(len(data)-start))
                if start:self.send_header('Content-Range',f'bytes {start}-{len(data)-1}/{len(data)}')
                self.end_headers()
                mode=owner.mode if name.endswith(('.bin','.safetensors','.onnx')) else 'normal'
                if mode=='stall':
                    time.sleep(8)
                    return
                if mode=='drop':
                    owner.mode='normal'
                    self.wfile.write(data[start:start+524288]);self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                try:
                    for offset in range(start,len(data),65536):
                        self.wfile.write(data[offset:offset+65536]);self.wfile.flush()
                        if mode=='slow':time.sleep(.12)
                except (OSError,ConnectionError):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.temp.cleanup()

    def run_transfer(self,model='small',limits=None,emit=None):
        (self.cache/'fixture.json').write_text(json.dumps(dict(url=f'http://127.0.0.1:{self.server.server_port}',files={k:v.hex() for k,v in self.files.items()})))
        with patch.dict(os.environ,{'HF_HUB_DISABLE_XET':'0','HF_HUB_ENABLE_HF_TRANSFER':'1','NO_PROXY':'127.0.0.1,localhost'}):
            supervise(self.cache,model,emit or (lambda k,v:self.events.append((k,v))),self.stop,limits or DownloadLimits(idle=5,verification_idle=5,attempts=2,backoff=.1),fixture_worker)

    def test_all_model_routes_and_completed_cache_are_reused(self):
        for model in ('tiny','small','medium','large-v3',SLOVAK_MODEL,SPEAKER_MODEL):
            with self.subTest(model=model):
                if model==SLOVAK_MODEL:
                    self.files={'config.json':b'{}','tokenizer.json':b'{}','preprocessor_config.json':b'{}','model.safetensors':b'w'*524288}
                elif model==SPEAKER_MODEL:
                    self.files={'voxceleb_resnet34_LM.onnx':b'w'*524288}
                self.run_transfer(model)
                path=cached_path(self.cache,model)
                self.assertIsNotNone(path)
                before=len(self.requests)
                self.run_transfer(model)
                self.assertEqual(len(self.requests),before)
                self.assertTrue(json.loads((path/'.nd-verified.json').read_text())['complete'])

    def test_disconnect_resumes_partial_with_range(self):
        self.mode='drop'
        self.run_transfer()
        self.assertTrue(any(name=='model.bin' and offset>0 for name,offset in self.requests))
        self.assertIsNotNone(cached_path(self.cache,'small'))

    def test_existing_partial_preserved_and_resumed(self):
        partial=cache_folder(self.cache,'small')/'blobs'/hashlib.sha256(self.files['model.bin']).hexdigest()
        partial.parent.mkdir(parents=True)
        partial.with_suffix('.incomplete').write_bytes(self.files['model.bin'][:262144])
        self.run_transfer()
        self.assertIn(('model.bin',262144),self.requests)

    def test_cancel_active_transfer_then_resume(self):
        self.mode='slow'
        def emit(k,v):
            self.events.append((k,v))
            if k=='status' and 'Sťahujem: model.bin' in v and '0.0/' not in v:
                self.stop.set()
        with self.assertRaises(InterruptedError):self.run_transfer(emit=emit)
        self.assertTrue(list(cache_folder(self.cache,'small').rglob('*.incomplete')))
        self.assertIsNone(cached_path(self.cache,'small'))
        self.stop.clear();self.mode='normal'
        self.run_transfer()
        self.assertTrue(any(name=='model.bin' and offset>0 for name,offset in self.requests))

    def test_silent_connection_has_finite_retry_budget(self):
        self.mode='stall'
        with self.assertRaisesRegex(RuntimeError,'Časový limit'):
            self.run_transfer(limits=DownloadLimits(idle=2,attempts=2,backoff=.1))
        self.assertLessEqual(sum(name=='model.bin' for name,_ in self.requests),2)
        self.assertEqual(self.events[-1],('download_state',False))

    def test_real_lock_is_bounded_and_reusable_after_release(self):
        from filelock import FileLock
        folder=cache_folder(self.cache,'small')
        folder.mkdir(parents=True)
        with FileLock(str(folder/'.nd-download.lock')):
            with self.assertRaisesRegex(RuntimeError,'Časový limit'):
                self.run_transfer(limits=DownloadLimits(idle=2,attempts=1))
        self.run_transfer()
        self.assertIsNotNone(cached_path(self.cache,'small'))

    def test_corrupt_complete_file_quarantined_without_losing_other_files(self):
        self.run_transfer()
        snapshot=cached_path(self.cache,'small')
        (snapshot/'model.bin').write_bytes(b'bad')
        before=sum(name=='config.json' for name,_ in self.requests)
        self.run_transfer()
        self.assertEqual(sum(name=='config.json' for name,_ in self.requests),before)
        self.assertTrue(list(snapshot.glob('*.invalid-*')))
        self.assertIsNotNone(cached_path(self.cache,'small'))

    def test_sharded_kinit_validation(self):
        self.files={'config.json':b'{}','tokenizer.json':b'{}','preprocessor_config.json':b'{}','model.safetensors.index.json':json.dumps({'weight_map':{'a':'part1.safetensors','b':'part2.safetensors'}}).encode(),'part1.safetensors':b'a'*32,'part2.safetensors':b'b'*32}
        self.run_transfer(SLOVAK_MODEL)
        snapshot=cached_path(self.cache,SLOVAK_MODEL)
        self.assertIsNotNone(snapshot)
        (snapshot/'part2.safetensors').unlink()
        self.assertFalse(complete_snapshot(snapshot,SLOVAK_MODEL))


class WatchdogTest(unittest.TestCase):
    def test_duplicate_heartbeat_does_not_reset_idle_watchdog(self):
        with tempfile.TemporaryDirectory() as folder:
            for phase in ('connect','lock','transfer','finalize'):
                with self.subTest(phase=phase),self.assertRaisesRegex(RuntimeError,'Časový limit'):
                    supervise(folder,phase,lambda *_:None,threading.Event(),DownloadLimits(idle=1,verification_idle=1,attempts=1),stuck_worker)

    def test_verification_progress_without_network_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            supervise(folder,'small',lambda *_:None,threading.Event(),DownloadLimits(idle=2,verification_idle=.5,attempts=1),verifying_worker)

    def test_error_messages_never_leak_urls_or_tokens(self):
        import requests
        for exc in (requests.ConnectionError('https://host?token=SECRET'),requests.exceptions.SSLError('SECRET'),ValueError('SECRET')):
            self.assertNotIn('SECRET',str(safe_error(exc)))

    def test_zero_byte_and_missing_shards_not_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'voxceleb_resnet34_LM.onnx').write_bytes(b'')
            self.assertFalse(complete_snapshot(path,SPEAKER_MODEL))
            for name in ('config.json','tokenizer.json','preprocessor_config.json'):(path/name).write_text('{}')
            (path/'model.safetensors').write_bytes(b'')
            self.assertFalse(complete_snapshot(path,SLOVAK_MODEL))
