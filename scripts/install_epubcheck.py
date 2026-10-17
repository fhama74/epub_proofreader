"""Install the official, version-pinned EPUBCheck locally; Java is separate."""
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import shutil
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '5.4.0'
URL = f'https://github.com/w3c/epubcheck/releases/download/v{VERSION}/epubcheck-{VERSION}.zip'
SHA256 = '33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c'

def install():
    target = ROOT / '.tools'
    target.mkdir(parents=True, exist_ok=True)
    jar = target / f'epubcheck-{VERSION}' / 'epubcheck.jar'
    if jar.exists():
        print(f'EPUBCheck is already installed: {jar}')
        return
    with tempfile.TemporaryDirectory(dir=target) as directory:
        archive = Path(directory) / 'epubcheck.zip'
        with urlopen(Request(URL,headers={'User-Agent':'EPUB-Proofreader'}),timeout=60) as response, archive.open('wb') as out:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 80 * 1024 * 1024:
                    raise ValueError('Download exceeds expected size')
                out.write(chunk)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise ValueError('EPUBCheck SHA-256 mismatch; installation aborted')
        with zipfile.ZipFile(archive) as source:
            for info in source.infolist():
                path = Path(info.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError('Unsafe path in EPUBCheck distribution')
            source.extractall(directory)
        shutil.move(str(Path(directory) / f'epubcheck-{VERSION}'),str(target / f'epubcheck-{VERSION}'))
    print(f'Installed EPUBCheck: {jar}')
    print('Java 11+ is required. Set JAVA_BIN if java is not available on PATH.')

if __name__ == '__main__':
    install()
