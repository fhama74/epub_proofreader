"""Find a real Java runtime; macOS /usr/bin/java may only be an installer stub."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def usable(path):
    try:
        result = subprocess.run([str(path), '-version'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5, check=False)
        version = re.search(r'version\s+"(?:1\.)?(\d+)', result.stdout.decode(errors='replace'))
        return result.returncode == 0 and bool(version) and int(version[1]) >= 11
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_java():
    explicit = os.getenv('JAVA_BIN')
    if explicit:
        return explicit if usable(explicit) else None
    binary = 'java.exe' if sys.platform == 'win32' else 'java'
    candidates = [ROOT / '.tools/java/bin' / binary]
    if os.getenv('JAVA_HOME'):
        candidates.append(Path(os.environ['JAVA_HOME']) / 'bin' / binary)
    if found := shutil.which('java'):
        candidates.append(Path(found))
    for candidate in candidates:
        if usable(candidate):
            return str(candidate)
    if sys.platform == 'darwin':
        try:
            home = subprocess.run(['/usr/libexec/java_home', '-v', '11+'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
            candidate = Path(home.stdout.decode().strip()) / 'bin/java'
            if home.returncode == 0 and usable(candidate):
                return str(candidate)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None
