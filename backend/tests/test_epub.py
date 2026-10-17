import hashlib
import io
import zipfile
from pathlib import Path
import pytest
from lxml import etree
from fastapi.testclient import TestClient
from epub_proofreader.epub import Book, EpubError
from epub_proofreader import app as module

SAMPLES = Path(__file__).resolve().parents[2] / 'samples'

def changed(updates):
    out = io.BytesIO()
    with zipfile.ZipFile(SAMPLES / 'book.epub') as source, zipfile.ZipFile(out, 'w') as target:
        for entry in source.infolist():
            if updates.get(entry.filename, b'') is None: continue
            target.writestr(entry, updates.get(entry.filename, source.read(entry)))
        for name, data in updates.items():
            if name not in source.namelist() and data is not None: target.writestr(name, data)
    return out.getvalue()

def test_parse_and_preserve_original():
    data = (SAMPLES / 'book.epub').read_bytes()
    before = hashlib.sha256(data).hexdigest()
    book = Book(data)
    assert book.opf_path == 'EPUB/package.opf'
    assert book.direction == 'rtl'
    assert len(book.spine) == 2
    assert len(book.chapters) == 2
    assert len(book.chapters[0]['paragraphs']) == 3
    assert len(book.toc) == 2
    paragraph = book.chapters[0]['paragraphs'][0]
    assert paragraph['text'] == '吾輩は猫である。名前はまだない。'
    assert paragraph['rubies'][0]['readings'] == ['わがはい']
    assert paragraph['rubies'][0]['editable']
    assert not book.chapters[1]['paragraphs'][1]['rubies'][0]['editable']
    preview = book.preview('chapter0001', 'test')
    assert '<ruby' in preview and '<rt>わがはい</rt>' in preview and '<rp>' in preview
    assert 'original-p1' not in preview
    assert 'data-paragraph="chapter0001-p00001"' in preview
    assert '/assets/EPUB/leaf.png' in preview
    assert book.original == data
    assert hashlib.sha256((SAMPLES / 'book.epub').read_bytes()).hexdigest() == before
    with zipfile.ZipFile(io.BytesIO(book.original)) as archive:
        assert archive.read('EPUB/style.css') == book.files['EPUB/style.css']
        assert archive.read('EPUB/chapter1.xhtml') == book.files['EPUB/chapter1.xhtml']
        assert '<ruby' in archive.read('EPUB/chapter1.xhtml').decode()

@pytest.mark.parametrize('data', [b'garbage', changed({'mimetype':b'wrong'}), changed({'EPUB/chapter1.xhtml':b'<html>'}), changed({'EPUB/style.css':None}), changed({'../evil':b'bad'}), changed({'/absolute':b'bad'}), changed({'C:/file':b'bad'}), changed({'EPUB/chapter1.xhtml':b'<!DOCTYPE html [<!ENTITY x SYSTEM "file:///etc/passwd">]><html>&x;</html>'})])
def test_invalid_epubs(data):
    with pytest.raises(EpubError): Book(data)

def test_bad_spine_and_external_manifest():
    with zipfile.ZipFile(SAMPLES / 'book.epub') as z: opf = z.read('EPUB/package.opf')
    with pytest.raises(EpubError): Book(changed({'EPUB/package.opf':opf.replace(b'idref="c1"', b'idref="missing"')}))
    with pytest.raises(EpubError): Book(changed({'EPUB/package.opf':opf.replace(b'href="style.css"', b'href="https://example.com/style.css"')}))

def test_preview_strips_active_content():
    content = b'''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Test</title></head><body><p onpointerdown="evil()" onclick="evil()" style="background:url(https://example.com)">text<script>evil()</script><iframe src="https://example.com/frame"/><object data="https://example.com/plugin"/><form action="https://example.com/send"><input name="secret"/></form><svg xmlns="http://www.w3.org/2000/svg" onload="evil()"><script>evil()</script></svg><a href="javascript:evil()">link</a><img src="https://example.com/track.png"/></p></body></html>'''
    book = Book(changed({'EPUB/chapter1.xhtml':content}))
    preview = book.preview('chapter0001', 'test')
    assert 'evil' not in preview and 'example.com' not in preview and 'onclick' not in preview
    assert all(tag not in preview for tag in ('<script','<iframe','<object','<form','<input','<svg','style=','onpointerdown='))

def test_zip_limits(monkeypatch):
    import epub_proofreader.epub as mod
    monkeypatch.setattr(mod, 'MAX_EXPANDED', 50)
    with pytest.raises(EpubError): Book((SAMPLES / 'book.epub').read_bytes())

def test_duplicate_entries():
    data = io.BytesIO((SAMPLES / 'book.epub').read_bytes())
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(data, 'a') as z: z.writestr('mimetype', b'application/epub+zip')
    with pytest.raises(EpubError): Book(data.getvalue())

def test_api_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA_DIR', tmp_path)
    module.load_book.cache_clear()
    client = TestClient(module.app)
    data = (SAMPLES / 'book.epub').read_bytes()
    response = client.post('/api/books', files={'file':('test.epub', data, 'application/epub+zip')})
    assert response.status_code == 200, response.text
    book = response.json(); ident = book['id']
    assert client.get(f'/api/books/{ident}').json()['fingerprint'] == hashlib.sha256(data).hexdigest()
    assert client.get(f'/api/books/{ident}/original').content == data
    assert '<ruby' in client.get(f'/api/books/{ident}/chapters/chapter0001').json()['html']
    assert client.get(f'/api/books/{ident}/assets/EPUB/leaf.png').headers['content-type'] == 'image/png'
    assert client.get(f'/api/books/{ident}/assets/EPUB/package.opf').status_code == 404
    assert client.get('/api/books/not-an-id').status_code == 404
    assert client.post('/api/books', files={'file':('x.pdf', data)}).status_code == 415
    assert client.post('/api/books', files={'file':('x.epub', b'invalid')}).status_code == 422
    assert client.get('/api/samples/original.pdf').content.startswith(b'%PDF-')
    # Persisted book survives cache loss (representing a backend restart).
    module.load_book.cache_clear()
    assert client.get(f'/api/books/{ident}').status_code == 200

@pytest.mark.parametrize('doctype', [
    '<!DOCTYPE html>',
    '<!DOCTYPE html SYSTEM "https://example.invalid/never-fetch.dtd">',
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
    '<!DOCTYPE html SYSTEM "file:///definitely-not-a-real-file.dtd">',
])
def test_doctype_without_entities_is_allowed_and_not_loaded(doctype, monkeypatch):
    from epub_proofreader.epub import NoExternalXML
    calls = []
    def resolver(self, url, public_id, context):
        calls.append(url)
        raise AssertionError('External DTD must never be loaded')
    monkeypatch.setattr(NoExternalXML, 'resolve', resolver)
    with zipfile.ZipFile(SAMPLES / 'book.epub') as z:
        source = z.read('EPUB/chapter1.xhtml')
    original = changed({'EPUB/chapter1.xhtml': doctype.encode() + source})
    book = Book(original)
    assert book.chapters[0]['paragraphs'][0]['rubies'][0]['readings'] == ['わがはい']
    assert '<ruby' in book.preview('chapter0001', 'test')
    assert book.original == original
    assert book.get('EPUB/chapter1.xhtml').startswith(doctype.encode())
    assert calls == []

@pytest.mark.parametrize('declaration, body', [
    ('<!ENTITY secret SYSTEM "file:///etc/passwd">', '&secret;'),
    ('<!ENTITY remote SYSTEM "https://example.invalid/entity">', '&remote;'),
    ('<!ENTITY unused "unused">', '普通の本文'),
    ('<!ENTITY % remote SYSTEM "https://example.invalid/parameter">%remote;', '本文'),
])
def test_declared_entities_remain_blocked(declaration, body):
    from epub_proofreader.epub import xml
    content = f'<!DOCTYPE html [{declaration}]><html><p>{body}</p></html>'.encode()
    with pytest.raises(EpubError): xml(content)

def test_utf16_doctype_and_builtin_references():
    from epub_proofreader.epub import xml
    data = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE html><html><p>本文 &amp; &#x732b;</p></html>'.encode('utf-16')
    assert xml(data).find('p').text == '本文 & 猫'

@pytest.mark.parametrize('reference', ['&#oops;', '&#xZZ;', '&#;', '&#0;'])
def test_invalid_character_reference_reports_file_and_location(reference, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA_DIR', tmp_path)
    bad_xml = ('<html xmlns="http://www.w3.org/1999/xhtml">\n<head><title>Test</title></head>\n<body><p>' + reference + '</p></body></html>').encode()
    original = changed({'EPUB/chapter2.xhtml': bad_xml})
    with pytest.raises(EpubError) as error:
        Book(original)
    assert 'EPUB/chapter2.xhtml（3行、' in str(error.value)
    assert 'CharRef' in str(error.value)
    assert '数値文字参照' in str(error.value)
    response = TestClient(module.app).post('/api/books', files={'file':('invalid.epub', original)})
    assert response.status_code == 422
    assert 'EPUB/chapter2.xhtml' in response.json()['detail']
    # Reject without saving or silently repairing the invalid input.
    assert not (tmp_path / 'library.sqlite3').exists()
