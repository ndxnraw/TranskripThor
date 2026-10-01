"""Voliteľné predbežné stiahnutie KInIT do používateľskej cache aplikácie."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path,
        default=Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'LokalnyPrepis' / 'models')
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    from speech_models import SLOVAK_MODEL
    snapshot_download(SLOVAK_MODEL, revision='v2.0', cache_dir=str(args.cache / 'huggingface'),
        allow_patterns=['*.json', '*.safetensors', '*.txt', 'README.md'], max_workers=2)
    print(f'Model pripravený v cache: {args.cache}')


if __name__ == '__main__':
    main()
