"""One disposable, HTTP-only Hub process; version-bound instrumentation is local."""
import errno
import fnmatch
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

HUB_VERSION = '0.36.2'
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 20
LOCK_TIMEOUT = 30


def safe_error(exc):
    # Never forward exception strings: requests errors contain signed URLs/tokens.
    status = getattr(getattr(exc,'response',None),'status_code',None)
    name = type(exc).__name__
    if isinstance(exc, IntegrityError):
        return 'integrity', 'Kontrolný súčet súboru nesúhlasí. Poškodený súbor bol odložený; zopakujem iba tento súbor.', True
    if isinstance(exc, TimeoutError) or name in ('Timeout','ReadTimeout','ConnectTimeout'):
        return 'timeout', 'Vypršal čas spojenia alebo čakania na zámok cache. Skontrolujte sieť a zatvorte druhú kópiu aplikácie.', True
    if name in ('SSLError','TLSFailure'):
        return 'tls', 'Nepodarilo sa overiť TLS certifikát servera. Skontrolujte dátum, certifikáty a nastavenia firemnej siete; TLS zostáva zapnuté.', False
    if status:
        return f'http_{status}', f'Server vrátil HTTP {status}. Skontrolujte prístup k Hugging Face a dostupnosť modelu; potom skúste znova.', status in (408,429) or status >= 500
    if isinstance(exc,OSError) and exc.errno in (errno.ENOSPC,errno.EACCES,errno.EPERM):
        return f'os_{exc.errno}', 'Do cache nemožno zapisovať. Skontrolujte voľné miesto a oprávnenie priečinka modelov.', False
    if name in ('ConnectionError','ProxyError','LocalEntryNotFoundError','ChunkedEncodingError','ContentDecodingError','TransferFailure'):
        return 'connection', 'Spojenie so serverom zlyhalo. Skontrolujte internet alebo proxy a skúste znova.', True
    if isinstance(exc,OSError) and exc.errno is None:
        return 'incomplete', 'Prenos súboru je neúplný alebo má nesprávnu veľkosť. Skontrolujte spojenie a skúste znova; cache zostáva zachovaná.', True
    if isinstance(exc, ValueError):
        return 'metadata', 'Metadáta alebo štruktúra modelu nie sú platné. Aktualizujte aplikáciu alebo skontrolujte dostupnosť modelu.', False
    return 'internal_'+name, 'Sťahovanie zlyhalo ('+name+'). Skúste znova; diagnostika je v model-download.log v priečinku cache.', False


class IntegrityError(ValueError):
    pass


class TransferFailure(RuntimeError):
    """Escape Hub's internal retry loop; the supervisor owns the budget."""


class TLSFailure(RuntimeError):
    pass


def checked_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe filename')
    return name


def verify_file(path, size, digest, send, name):
    if not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',digest):
        raise ValueError('Missing checksum')
    sha = hashlib.sha256() if len(digest)==64 else hashlib.sha1()
    if len(digest)==40:
        sha.update(f'blob {size}\0'.encode())
    read, last = 0, 0
    send(dict(kind='progress',phase='verify',file=name,bytes=0,total=size))
    with Path(path).open('rb') as stream:
        while block := stream.read(1024*1024):
            sha.update(block)
            read += len(block)
            if time.monotonic()-last >= .25:
                send(dict(kind='progress',phase='verify',file=name,bytes=read,total=size))
                last = time.monotonic()
    if read != size or sha.hexdigest() != digest:
        raise IntegrityError('Checksum mismatch')
    send(dict(kind='progress',phase='verify',file=name,bytes=read,total=size))


def run_download(cache, model, connection):
    try:
        download_files(cache,model,connection.send)
        connection.send(dict(kind='complete'))
    except Exception as exc:
        code, message, retry = safe_error(exc)
        connection.send(dict(kind='error',code=code,message=message,retry=retry))
    finally:
        connection.close()


def download_files(cache, model, send):
    # Set before import, and also set constants below: inherited environments or
    # frozen boot hooks must not silently reactivate a native transfer backend.
    os.environ['HF_HUB_DISABLE_XET']='1'
    os.environ['HF_HUB_ENABLE_HF_TRANSFER']='0'
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
    import huggingface_hub as hub
    from huggingface_hub import file_download as fd, constants
    from huggingface_hub.utils import disable_progress_bars
    from huggingface_hub import configure_http_backend
    from filelock import FileLock
    import requests
    from model_catalog import location, cache_folder, complete_snapshot
    if hub.__version__ != HUB_VERSION:
        raise ValueError('Unsupported Hub version')
    constants.HF_HUB_DISABLE_XET=True
    constants.HF_HUB_ENABLE_HF_TRANSFER=False
    constants.HF_HUB_DOWNLOAD_TIMEOUT=READ_TIMEOUT
    constants.HF_HUB_ETAG_TIMEOUT=CONNECT_TIMEOUT
    constants.DOWNLOAD_CHUNK_SIZE=256*1024
    disable_progress_bars()
    # Library log records can include signed URLs; use only our safe diagnostics.
    import logging
    logging.getLogger('huggingface_hub').setLevel(logging.CRITICAL)
    logging.getLogger('urllib3').setLevel(logging.CRITICAL)
    class Session(requests.Session):
        def request(self,*args,**kwargs):
            kwargs['timeout']=(CONNECT_TIMEOUT,READ_TIMEOUT)
            try:
                response = super().request(*args,**kwargs)
            except requests.exceptions.SSLError:
                raise TLSFailure() from None
            except (requests.ConnectionError,requests.Timeout):
                raise TransferFailure() from None
            if response.status_code in (408,429) or response.status_code >= 500:
                response.close()
                raise requests.HTTPError(response=response)
            original_iter = response.iter_content
            def chunks(*args,**kwargs):
                try:
                    yield from original_iter(*args,**kwargs)
                except requests.exceptions.SSLError:
                    raise TLSFailure() from None
                except requests.RequestException:
                    raise TransferFailure() from None
            response.iter_content = chunks
            return response
    configure_http_backend(backend_factory=Session)
    base,repo,revision=location(cache,model)
    root=cache_folder(cache,model)
    root.mkdir(parents=True,exist_ok=True)
    send(dict(kind='progress',phase='lock',file=model))
    with FileLock(str(root/'.nd-download.lock'),timeout=LOCK_TIMEOUT):
        send(dict(kind='progress',phase='connect',file=model))
        info=hub.HfApi().model_info(repo,revision=revision,files_metadata=True,timeout=READ_TIMEOUT)
        if not re.fullmatch(r'[a-f0-9]{40}',info.sha):
            raise ValueError('Invalid revision')
        from speech_models import SLOVAK_MODEL
        from model_catalog import SPEAKER_MODEL
        patterns = ['*.json','*.safetensors','merges.txt','vocab.json'] if model==SLOVAK_MODEL else ['voxceleb_resnet34_LM.onnx','README.md'] if model==SPEAKER_MODEL else ['config.json','preprocessor_config.json','model.bin','tokenizer.json','vocabulary.*']
        files=[item for item in info.siblings if any(fnmatch.fnmatch(item.rfilename,p) for p in patterns)]
        if not files:
            raise ValueError('No files')
        # Per-file callbacks report transfer bytes, not size of a different cache.
        active = {'name': '', 'count': ''}
        class Progress:
            def __init__(self, **kwargs):
                self.n=kwargs.get('initial',0)
                self.total=kwargs.get('total')
                self.last=0
                self.report()
            def report(self):
                send(dict(kind='progress',phase='transfer',file=active['name'],bytes=self.n,total=self.total,count=active['count']))
                self.last=time.monotonic()
            def update(self,n):
                self.n+=n
                if time.monotonic()-self.last>=.25:
                    self.report()
            def reset(self,total=None):
                self.n=0
                self.total=total
                self.report()
            def __enter__(self):
                return self
            def __exit__(self,*_):
                self.report()
        @contextmanager
        def lock(path, **kwargs):
            send(dict(kind='progress',phase='lock',file=active['name'],count=active['count']))
            with FileLock(str(path),timeout=LOCK_TIMEOUT):
                send(dict(kind='progress',phase='connect',file=active['name'],count=active['count']))
                yield
        original_http, original_move = fd.http_get, fd._chmod_and_move
        def http(*args, **kwargs):
            kwargs['_nb_retries']=0  # Supervisor owns a finite retry budget.
            return original_http(*args,**kwargs)
        def move(*args, **kwargs):
            send(dict(kind='progress',phase='finalize',file=active['name'],count=active['count']))
            return original_move(*args,**kwargs)
        # Confined to this child; no monkeypatching of a running ASR process.
        fd._get_progress_bar_context=lambda **kwargs:Progress(**kwargs)
        fd.WeakFileLock=lock
        fd.http_get=http
        fd._chmod_and_move=move
        snapshot=root/'snapshots'/info.sha
        receipt_path=snapshot/'.nd-verified.json'
        try:
            receipt=json.loads(receipt_path.read_text(encoding='utf-8')).get('files',{})
        except (OSError,ValueError):
            receipt={}
        verified=dict(receipt)
        from state import atomic_text
        atomic_text(receipt_path,json.dumps(dict(complete=False,files=verified)))
        for i,item in enumerate(files,1):
            name=checked_name(item.rfilename)
            active.update(name=name,count=f'{i}/{len(files)}')
            size=item.size
            digest=item.lfs.sha256 if item.lfs else item.blob_id
            if not isinstance(size,int) or size <= 0:
                raise ValueError('Invalid size')
            send(dict(kind='progress',phase='connect',file=name,count=active['count']))
            path=Path(hub.hf_hub_download(repo,name,revision=info.sha,cache_dir=str(base),etag_timeout=CONNECT_TIMEOUT))
            stat=path.stat()
            saved=receipt.get(name,{})
            if saved != dict(size=size,digest=digest,mtime=stat.st_mtime_ns):
                try:
                    verify_file(path,size,digest,send,name)
                except IntegrityError:
                    # Keep evidence; only this corrupt file is moved, never a cache tree.
                    target=path.resolve()
                    if root.resolve() not in target.parents:
                        raise ValueError('Unsafe cache path')
                    target.rename(target.with_name(target.name+'.invalid-'+str(time.time_ns())))
                    raise
            verified[name]=dict(size=size,digest=digest,mtime=path.stat().st_mtime_ns)
            from state import atomic_text
            atomic_text(receipt_path,json.dumps(dict(complete=False,files=verified)))
        if not complete_snapshot(snapshot,model,verify_receipt=False):
            raise ValueError('Missing required files')
        from state import atomic_text
        send(dict(kind='progress',phase='finalize',file=model))
        atomic_text(receipt_path,json.dumps(dict(complete=True,files={item.rfilename:verified[item.rfilename] for item in files})))
        atomic_text(root/'refs'/revision,info.sha)
