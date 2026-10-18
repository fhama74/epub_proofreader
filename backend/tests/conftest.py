import pytest


@pytest.fixture(autouse=True)
def storage_generation(request,monkeypatch):
    # Historical format/replay tests remain explicit coverage of the migration
    # input. Production and the new storage tests always use the unit database.
    from epub_proofreader import unit_store
    monkeypatch.setattr(unit_store,'USE_NEW_STORAGE',request.module.__name__.startswith('test_unit_store'))
