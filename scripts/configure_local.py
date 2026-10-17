"""Create the local API-key encryption key once, without replacing an existing key."""
import base64
import os
from pathlib import Path
import secrets
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def configure(root=ROOT):
    directory = root / 'secrets'
    key = directory / 'ai_secret_key'
    if key.exists():
        if len(base64.urlsafe_b64decode(key.read_bytes().strip())) != 32:
            raise ValueError('Existing encryption key is invalid; not replaced.')
        print('Existing encryption key kept (value hidden).')
        return
    data = Path(os.getenv('DATA_DIR', os.getenv('EPROOF_DATA_DIR', str(root / '.data'))))
    database = data / 'library.sqlite3'
    if database.exists():
        with sqlite3.connect('file:' + str(database.resolve()) + '?mode=ro', uri=True) as con:
            exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='ai_engines'").fetchone()
            if exists and con.execute("SELECT 1 FROM ai_engines WHERE key_cipher IS NOT NULL AND key_cipher != '' LIMIT 1").fetchone():
                raise ValueError('Encrypted API keys exist. Restore the original encryption key; no new key was created.')
    directory.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(base64.urlsafe_b64encode(secrets.token_bytes(32)) + b'\n')
    print('Encryption key created in secrets/ai_secret_key (value hidden).')
    print('The local app reads this file automatically. Keep a separate backup.')


if __name__ == '__main__':
    configure()
