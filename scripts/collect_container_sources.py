"""Collect matching copyleft sources from the exact built Debian image for release.

Run in a disposable container, never in the running user's application container.
The source archive is published alongside the image, not added to the runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen


def collect(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    packages = subprocess.check_output([
        'dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n'
    ], text=True)
    (output / 'debian-packages.tsv').write_text(packages)
    sources = set()
    notices = output / 'licenses'
    notices.mkdir(exist_ok=True)
    for line in packages.splitlines():
        binary, version, source, source_version = line.split('\t')
        name = binary.split(':')[0]
        copyright = Path('/usr/share/doc') / name / 'copyright'
        if not copyright.exists():
            raise RuntimeError(f'Missing Debian copyright file: {binary}')
        content = copyright.read_bytes()
        (notices / (name + '.txt')).write_bytes(content)
        # Include LGPL and GPL, including packages referring to common-licenses.
        if re.search(rb'GPL|General Public License', content, re.I):
            sources.add((source, source_version))
    for file in Path('/etc/apt/sources.list.d').glob('*.sources'):
        text = file.read_text()
        file.write_text(re.sub(r'^Types: deb$', 'Types: deb deb-src', text, flags=re.M))
    subprocess.run(['apt-get', 'update'], check=True)
    debian = output / 'debian-sources'
    debian.mkdir(exist_ok=True)
    for name, version in sorted(sources):
        subprocess.run(['apt-get', 'source', '--download-only', f'{name}={version}'], cwd=debian, check=True)
    (output / 'debian-sources.json').write_text(json.dumps(sorted(sources), indent=2) + '\n')
    # Saxon is the MPL-licensed binary dependency in EPUBCheck 5.4.0.
    jars = list(Path('/app/.tools/epubcheck-5.4.0/lib').glob('Saxon-HE-*.jar'))
    if [p.name for p in jars] != ['Saxon-HE-11.4.jar']:
        raise RuntimeError('Review Saxon version and source URL before publishing.')
    url = 'https://repo.maven.apache.org/maven2/net/sf/saxon/Saxon-HE/11.4/Saxon-HE-11.4-sources.jar'
    with urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != '3855cb7c56c64c22a194f1abbf590693b3db7fa76da7a9ffff148420043c96c4':
        raise RuntimeError('Saxon source checksum mismatch')
    (output / 'Saxon-HE-11.4-sources.jar').write_bytes(data)
    (output / 'README.txt').write_text(
        'Corresponding sources for this container build. Debian source archives include\n'
        'upstream sources, Debian patches and build instructions. Package versions and\n'
        'copyright notices are included. Saxon sources are included under MPL-2.0.\n'
        'certifi source is installed as Python source in the image. Original application\n'
        'sources and Docker build scripts are at the exact release commit on GitHub.\n'
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    collect(parser.parse_args().output)
