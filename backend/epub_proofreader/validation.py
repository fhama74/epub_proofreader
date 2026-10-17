"""Optional local EPUBCheck CLI. Never upload books to a validation service."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
from .java_runtime import find_java

def epubcheck(data: bytes):
    bundled = Path(__file__).resolve().parents[2] / '.tools' / 'epubcheck-5.4.0' / 'epubcheck.jar'
    jar = os.getenv('EPUBCHECK_JAR') or (str(bundled) if bundled.is_file() else None)
    command = None
    if jar:
        java = find_java()
        if not java or not Path(jar).is_file():
            return {'status':'unavailable','message':'Java 11以上の実行環境またはEPUBCHECK_JARを確認してください。.tools/java/bin/java、JAVA_HOME、JAVA_BINを利用できます。'}
        command = [java, '-jar', str(Path(jar).resolve())]
    elif executable := shutil.which('epubcheck'):
        command = [executable]
    if command is None:
        return {'status':'unavailable','message':'EPUBCheckが未設定です。EPUBCHECK_JARとJavaを設定してください。内部構造検証は実行できます。'}
    with tempfile.TemporaryDirectory(prefix='eproof-check-') as directory:
        root = Path(directory)
        book = root / 'book.epub'; book.write_bytes(data)
        report = root / 'report.json'
        try:
            result = subprocess.run([*command, '--json', str(report), str(book)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False)
        except subprocess.TimeoutExpired:
            return {'status':'timeout','message':'EPUBCheckの実行が60秒でタイムアウトしました。'}
        except OSError as exc:
            return {'status':'unavailable','message':f'EPUBCheckを起動できません: {exc}'}
        output = result.stdout.decode('utf-8',errors='replace')[-12000:]
        if not report.exists():
            return {'status':'unavailable','message':'EPUBCheckの検証レポートが生成されませんでした。Javaの設定を確認してください。','output':output}
        try:
            parsed = json.loads(report.read_text(encoding='utf-8'))
        except (ValueError,OSError):
            return {'status':'error','message':'EPUBCheckのレポートを読み込めませんでした。','output':output}
        return {'status':'passed' if result.returncode == 0 else 'failed','exit_code':result.returncode,'report':parsed,'output':output}
