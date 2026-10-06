"""Model inventory and explicit, local-cache-only management."""
import json
import shutil
from pathlib import Path
from speech_models import SLOVAK_MODEL

SPEAKER_MODEL = 'Wespeaker/wespeaker-voxceleb-resnet34-LM'
SPEAKER_REVISION = 'f0c48c298fd835726c27956a5d617bad7115627e'
DESCRIPTIONS = {
    'tiny': 'Rýchla skúška; nižšia presnosť.', 'small': 'Vyvážená rýchlosť a pamäť.',
    'medium': 'Vyššia presnosť, viac RAM.', 'large-v3': 'Najvyššie nároky; vhodný aj na CZ/SK.',
    SLOVAK_MODEL: 'Iba slovenčina; približne 6,2 GB váh, vysoké nároky na RAM.',
    SPEAKER_MODEL: 'Voliteľné hlasy, CPU; CC BY 4.0; bez tokenu. Neurčuje identitu osoby.'}


def location(cache, model):
    if model not in DESCRIPTIONS:
        raise ValueError('Neznámy model.')
    repo = model if '/' in model else 'Systran/faster-whisper-' + model
    base = Path(cache) / 'huggingface' if model in (SLOVAK_MODEL, SPEAKER_MODEL) else Path(cache)
    revision = 'v2.0' if model == SLOVAK_MODEL else SPEAKER_REVISION if model == SPEAKER_MODEL else 'main'
    return base, repo, revision


def cache_folder(cache, model):
    base, repo, _ = location(cache, model)
    return base / ('models--' + repo.replace('/', '--'))


def complete_snapshot(path, model, verify_receipt=True):
    try:
        required = ['voxceleb_resnet34_LM.onnx'] if model == SPEAKER_MODEL else ['config.json', 'tokenizer.json']
        if model == SLOVAK_MODEL:
            required += ['preprocessor_config.json']
            if (path/'model.safetensors').is_file():
                required += ['model.safetensors']
            else:
                index=json.loads((path/'model.safetensors.index.json').read_text(encoding='utf-8'))
                shards=set(index['weight_map'].values())
                if not shards:
                    return False
                required += ['model.safetensors.index.json'] + list(shards)
        elif model != SPEAKER_MODEL:
            required += ['model.bin']
        for name in required:
            from download_worker import checked_name
            checked_name(name)
            file=path/name
            if not file.is_file() or file.stat().st_size <= 0:
                return False
            if name.endswith('.json'):
                if not isinstance(json.loads(file.read_text(encoding='utf-8')),dict):
                    return False
        receipt=path/'.nd-verified.json'
        if verify_receipt and receipt.exists():
            data=json.loads(receipt.read_text(encoding='utf-8'))
            if not data.get('complete') or not set(required) <= data['files'].keys():
                return False
            for name, meta in data['files'].items():
                checked_name(name)
                stat=(path/name).stat()
                if stat.st_size != meta['size'] or stat.st_mtime_ns != meta['mtime']:
                    return False
        return True
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return False


def cached_path(cache, model):
    folder = cache_folder(cache, model)
    _, _, revision = location(cache, model)
    ref = folder / 'refs' / revision
    commit = ref.read_text().strip() if ref.is_file() else revision
    if not commit or '/' in commit or '\\' in commit or ':' in commit or commit in ('.','..'):
        return None
    path = folder / 'snapshots' / commit
    return path if complete_snapshot(path, model) else None


def inventory(cache):
    result = []
    for model, description in DESCRIPTIONS.items():
        folder = cache_folder(cache, model)
        # Count physical files once when snapshots use symlinks.
        seen, size = set(), 0
        for path in folder.rglob('*') if folder.exists() else []:
            if path.is_file():
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    size += path.stat().st_size
        result.append(dict(model=model, available=cached_path(cache, model) is not None,
                           size=size, description=description))
    return result


def download(cache, model, emit, stop):
    from download_transport import supervise
    supervise(cache, model, emit, stop)


def ensure_model(cache, model, offline, emit, stop):
    if cached_path(cache, model):
        return
    if offline:
        raise ValueError('Vybraný model nie je úplne dostupný lokálne. Vypnite Iba offline a stiahnite ho v Správcovi modelov.')
    download(cache, model, emit, stop)


def remove_model(cache, model):
    target = cache_folder(cache, model).resolve()
    root = Path(cache).resolve()
    if target == root or root not in target.parents or target.name != cache_folder(cache, model).name:
        raise ValueError('Neplatná cesta modelu; odstránenie odmietnuté.')
    if target.exists():
        shutil.rmtree(target)
