"""Prepare a fresh Docker deployment without replacing any existing key or data."""
import argparse
import base64
import os
from pathlib import Path
import secrets


def initialize(root: Path, write_env=True):
    root = root.resolve()
    (root / 'data').mkdir(exist_ok=True)
    private = root / 'secrets'
    private.mkdir(mode=0o700, exist_ok=True)
    key = private / 'ai_secret_key'
    if key.exists():
        try:
            raw = base64.urlsafe_b64decode(key.read_bytes().strip())
        except (ValueError, OSError) as exc:
            raise ValueError('Existing key cannot be read; it was not replaced.') from exc
        if len(raw) != 32:
            raise ValueError('Existing key is invalid; it was not replaced.')
        print('Existing encryption key kept.')
    else:
        # A migrated database must use its original encryption key.
        if any((root / 'data').iterdir()):
            raise ValueError('Data already exists. Restore its original key before initializing.')
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(base64.urlsafe_b64encode(secrets.token_bytes(32)) + b'\n')
        print('New encryption key created in secrets/ai_secret_key (value hidden).')
    env = root / '.env'
    if write_env and not env.exists():
        with env.open('x') as out:
            out.write((root / '.env.example').read_text())
        print('.env created from the example.')
    print('Ready: docker compose up --build -d')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--no-env', action='store_true', help='Initialize only storage and the key (prebuilt image).')
    args = parser.parse_args()
    initialize(args.root, write_env=not args.no_env)
