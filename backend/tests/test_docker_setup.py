"""Deployment initialization must never invalidate existing encrypted data."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('init_docker', Path(__file__).resolve().parents[2] / 'scripts/init_docker.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_setup_keeps_existing_key_and_custom_env(tmp_path):
    from cryptography.fernet import Fernet
    (tmp_path / '.env.example').write_text('EPROOF_PORT=8000\n')
    module.initialize(tmp_path)
    key = (tmp_path / 'secrets/ai_secret_key').read_bytes().strip()
    ciphertext = Fernet(key).encrypt(b'example API credential')
    (tmp_path / '.env').write_text('EPROOF_PORT=8002\n')
    (tmp_path / 'data/library.sqlite3').write_bytes(b'existing data')
    module.initialize(tmp_path)
    assert Fernet((tmp_path / 'secrets/ai_secret_key').read_bytes().strip()).decrypt(ciphertext) == b'example API credential'
    assert (tmp_path / '.env').read_text() == 'EPROOF_PORT=8002\n'
    assert (tmp_path / 'data/library.sqlite3').read_bytes() == b'existing data'


def test_migration_without_original_key_is_rejected(tmp_path):
    (tmp_path / '.env.example').write_text('')
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/library.sqlite3').write_bytes(b'existing data')
    with pytest.raises(ValueError, match='original key'):
        module.initialize(tmp_path)
    assert not (tmp_path / 'secrets/ai_secret_key').exists()


def test_invalid_existing_key_is_not_replaced(tmp_path):
    (tmp_path / 'secrets').mkdir()
    key = tmp_path / 'secrets/ai_secret_key'
    key.write_text('invalid')
    with pytest.raises(ValueError):
        module.initialize(tmp_path)
    assert key.read_text() == 'invalid'


def test_image_setup_needs_no_env_example_and_keeps_original_key(tmp_path):
    module.initialize(tmp_path, write_env=False)
    key = (tmp_path / 'secrets/ai_secret_key').read_bytes()
    (tmp_path / 'data/library.sqlite3').write_bytes(b'persisted project')
    module.initialize(tmp_path, write_env=False)
    assert not (tmp_path / '.env').exists()
    assert (tmp_path / 'secrets/ai_secret_key').read_bytes() == key
    assert (tmp_path / 'data/library.sqlite3').read_bytes() == b'persisted project'


def test_local_key_setup_and_default_cipher(tmp_path,monkeypatch):
    import importlib.util
    from epub_proofreader.ai import engine_manager
    spec=importlib.util.spec_from_file_location('configure_local',Path(__file__).resolve().parents[2]/'scripts/configure_local.py')
    local=importlib.util.module_from_spec(spec);spec.loader.exec_module(local)
    monkeypatch.delenv('DATA_DIR',raising=False);monkeypatch.delenv('EPROOF_DATA_DIR',raising=False)
    monkeypatch.delenv('AI_SECRET_KEY',raising=False);monkeypatch.delenv('AI_SECRET_KEY_FILE',raising=False)
    local.configure(tmp_path);path=tmp_path/'secrets/ai_secret_key';before=path.read_bytes()
    local.configure(tmp_path);assert path.read_bytes()==before
    monkeypatch.setattr(engine_manager,'DEFAULT_SECRET_FILE',path)
    cipher=engine_manager.cipher();assert cipher.decrypt(cipher.encrypt(b'sample'))==b'sample'
