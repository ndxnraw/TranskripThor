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


def complete_snapshot(path, model):
    if model == SPEAKER_MODEL:
        return (path / 'voxceleb_resnet34_LM.onnx').is_file()
    required = ['config.json', 'tokenizer.json']
    if model == SLOVAK_MODEL:
        required += ['preprocessor_config.json']
        if not (path / 'model.safetensors').is_file():
            try:
                required += list(set(json.loads((path / 'model.safetensors.index.json').read_text())['weight_map'].values()))
            except (OSError, ValueError, KeyError):
                return False
    else:
        required += ['model.bin']
    return all((path / name).is_file() and (path / name).stat().st_size > 0 for name in required)


def cached_path(cache, model):
    folder = cache_folder(cache, model)
    _, _, revision = location(cache, model)
    ref = folder / 'refs' / revision
    commit = ref.read_text().strip() if ref.is_file() else revision
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
    from huggingface_hub import snapshot_download
    from tqdm.auto import tqdm
    base, repo, revision = location(cache, model)
    patterns = ['*.json', '*.safetensors', 'merges.txt', 'vocab.json'] if model == SLOVAK_MODEL else \
        ['voxceleb_resnet34_LM.onnx', 'README.md'] if model == SPEAKER_MODEL else \
        ['config.json', 'preprocessor_config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*']
    class DownloadProgress(tqdm):
        def __init__(self, *args, **kwargs):
            kwargs['disable'] = False
            super().__init__(*args, **kwargs)
        def display(self, *args, **kwargs):
            if stop.is_set():
                raise InterruptedError('Sťahovanie zastavené; už stiahnuté dáta zostávajú v cache.')
            unit = 'súborov' if self.unit == 'it' else self.unit
            emit('status', f'Sťahujem {model}: {self.n:g}/{self.total:g} {unit}' if self.total else f'Sťahujem {model}…')
    if stop.is_set():
        raise InterruptedError('Sťahovanie zastavené.')
    emit('status', f'Sťahujem model {model}… Čakám na údaje servera.')
    snapshot_download(repo, revision=revision, cache_dir=str(base), allow_patterns=patterns,
                      tqdm_class=DownloadProgress, max_workers=2)
    if stop.is_set():
        raise InterruptedError('Sťahovanie zastavené.')
    if not cached_path(cache, model):
        raise RuntimeError('Model nie je úplný. Skúste sťahovanie zopakovať.')


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
