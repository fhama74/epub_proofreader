from types import SimpleNamespace
from pathlib import Path
from epub_proofreader import java_runtime as j


def test_macos_stub_is_rejected():
    assert not j.usable('/a/path/that/does/not/exist')


def test_java_version_probe(monkeypatch):
    for output, code, expected in [(b'openjdk version "21.0.1"',0,True),(b'java version "1.8.0_222"',0,False),(b'Unable to locate a Java Runtime.',1,False)]:
        monkeypatch.setattr(j.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=output,returncode=code))
        assert j.usable('java') is expected


def test_local_runtime_works_without_environment_and_skips_system_stub(monkeypatch,tmp_path):
    monkeypatch.delenv('JAVA_BIN',raising=False);monkeypatch.delenv('JAVA_HOME',raising=False)
    monkeypatch.setattr(j,'ROOT',tmp_path);monkeypatch.setattr(j.shutil,'which',lambda _: '/usr/bin/java')
    local=tmp_path/'.tools/java/bin/java'
    monkeypatch.setattr(j,'usable',lambda p:Path(p)==local)
    assert j.find_java()==str(local)


def test_explicit_runtime_is_not_silently_overridden(monkeypatch):
    monkeypatch.setenv('JAVA_BIN','configured-java');monkeypatch.setattr(j,'usable',lambda _:False)
    assert j.find_java() is None
