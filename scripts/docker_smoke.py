"""Local/CI container checks using only the synthetic sample; no AI requests."""
import argparse
import json
from pathlib import Path
import re
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import uuid


def check(base, state, create):
    def request(path, data=None, content_type=None):
        headers = {'Content-Type': content_type} if content_type else {}
        with urlopen(Request(base.rstrip('/') + path, data=data, headers=headers), timeout=90) as response:
            return response.read()
    for attempt in range(60):
        try:
            assert json.loads(request('/api/health'))['status'] == 'ok'
            break
        except (URLError, TimeoutError, AssertionError):
            if attempt == 59:
                raise
            time.sleep(1)
    html = request('/').decode()
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert assets, 'Built UI missing'
    for asset in assets:
        assert request(asset), f'Missing UI asset: {asset}'
    for asset in ['/pdfjs/wasm/openjpeg.wasm', '/pdfjs/cmaps/UniJIS-UTF16-H.bcmap']:
        assert request(asset), f'Missing PDF asset: {asset}'
    if create:
        sample = Path(__file__).resolve().parents[1] / 'samples/book.epub'
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="docker-smoke.epub"\r\nContent-Type: application/epub+zip\r\n\r\n'.encode() + sample.read_bytes() + f'\r\n--{boundary}--\r\n'.encode())
        book = json.loads(request('/api/books', body, f'multipart/form-data; boundary={boundary}'))
        state.write_text(json.dumps({'id': book['id']}))
    book = json.loads(request('/api/books/' + json.loads(state.read_text())['id']))
    assert book['chapters'], 'Persisted book missing'
    validation = json.loads(request('/api/books/' + book['id'] + '/validate', json.dumps({'revision': book['edit_state']['revision']}).encode(), 'application/json'))
    assert validation['epubcheck']['status'] == 'passed', validation['epubcheck']
    print('PASS: health, UI, PDF assets, stored project and real EPUBCheck; no AI called.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--create', action='store_true')
    args = parser.parse_args()
    check(args.url, args.state, args.create)
