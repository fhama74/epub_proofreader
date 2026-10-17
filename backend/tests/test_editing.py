from pathlib import Path
import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from epub_proofreader import app as module
from epub_proofreader.epub import Book, NS
from test_epub import changed

SAMPLE = Path(__file__).resolve().parents[2] / 'samples/book.epub'
P1='chapter0001-p00001'; P2='chapter0001-p00002'; P3='chapter0001-p00003'

@pytest.fixture
def session(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    module.load_book.cache_clear()
    client=TestClient(module.app)
    def create(data=None):
        response=client.post('/api/books',files={'file':('本.epub',data or SAMPLE.read_bytes())})
        assert response.status_code==200,response.text
        return '/api/books/'+response.json()['id']
    return client,create

def details(client,root,paragraph=P2):
    response=client.get(root+'/paragraphs/'+paragraph)
    assert response.status_code==200,response.text
    return response.json()

def edit(client,root,paragraph,text,revision=0):
    return client.patch(root+'/paragraphs/'+paragraph,json={'revision':revision,'text':text,'reason':'原本照合'})

def test_edit_export_structure_and_immutable_original(session):
    client,create=session; root=create()
    before=details(client,root)
    response=edit(client,root,P2,before['editor_text'].replace('天汽','天気'))
    assert response.status_code==200,response.text
    summary=response.json()
    assert summary['edit_state']['revision']==1
    assert summary['edit_state']['can_undo']
    paragraph=summary['chapters'][0]['paragraphs'][1]
    assert paragraph['edited'] and '天汽' in paragraph['original_text'] and '天気' in paragraph['text']
    assert client.get(root+'/original').content==SAMPLE.read_bytes()
    output=client.get(root+'/export')
    assert output.status_code==200,output.text
    assert "filename*=UTF-8''" in output.headers['content-disposition']
    exported=Book(output.content); original=Book(SAMPLE.read_bytes())
    assert exported.chapters[0]['paragraphs'][1]['text']==before['editor_text'].replace('天汽','天気')
    assert set(exported.files)==set(original.files)
    for path,content in original.files.items():
        if path!='EPUB/chapter1.xhtml':assert exported.files[path]==content
    assert exported.metadata==original.metadata and exported.toc==original.toc
    assert exported.direction=='rtl'
    assert exported.chapters[0]['paragraphs'][0]['rubies']==original.chapters[0]['paragraphs'][0]['rubies']
    with zipfile.ZipFile(io.BytesIO(output.content)) as archive:
        assert archive.infolist()[0].filename=='mimetype'
        assert archive.infolist()[0].compress_type==zipfile.ZIP_STORED
    events=client.get(root+'/history').json()
    assert events['schema_version']==2 and events['original_sha256']==original.fingerprint
    assert events['events'][0]['reason']=='原本照合'
    assert events['events'][0]['state']=='approved'

def test_ruby_edit_preserves_rp_and_plain_rb(session):
    client,create=session;root=create()
    response=client.patch(root+f'/paragraphs/{P1}/rubies/0',json={'revision':0,'base':'我輩','reading':'わがはい'})
    assert response.status_code==200,response.text
    book=Book(client.get(root+'/export').content)
    ruby=book.trees['EPUB/chapter1.xhtml'].xpath('//x:ruby',namespaces=NS)[0]
    assert ruby.text=='我輩'
    assert [n.text for n in ruby.findall('x:rp',NS)]==['（','）']
    response=client.patch(root+'/paragraphs/chapter0002-p00003/rubies/0',json={'revision':1,'base':'確認','reading':'かくにん'})
    assert response.status_code==200,response.text
    book=Book(client.get(root+'/export').content)
    ruby=book.trees['EPUB/chapter2.xhtml'].xpath('//x:ruby',namespaces=NS)[1]
    assert ruby.find('x:rb',NS).text=='確認' and ruby.find('x:rt',NS).text=='かくにん'

def test_complex_ruby_and_cross_ruby_text_are_protected(session):
    client,create=session;root=create()
    response=client.patch(root+'/paragraphs/chapter0002-p00002/rubies/0',json={'revision':0,'base':'大阪','reading':'おおさか'})
    assert response.status_code==422
    d=details(client,root,P1)
    assert edit(client,root,P1,d['editor_text'].replace('吾輩','我輩')).status_code==422
    assert client.get(root).json()['edit_state']['revision']==0
    # Text outside a complex ruby is editable, with its XML preserved.
    d=details(client,root,'chapter0002-p00002')
    response=edit(client,root,'chapter0002-p00002',d['editor_text'].replace('明日の旅','翌日の旅'))
    assert response.status_code==200,response.text
    book=Book(client.get(root+'/export').content)
    assert book.chapters[1]['paragraphs'][1]['rubies']==Book(SAMPLE.read_bytes()).chapters[1]['paragraphs'][1]['rubies']

def test_undo_redo_branch_and_restart(session):
    client,create=session;root=create(); d=details(client,root)
    edit(client,root,P2,d['editor_text'].replace('天汽','天気'))
    assert client.post(root+'/undo',json={'revision':1}).status_code==200
    assert details(client,root)['editor_text']==d['editor_text']
    assert Book(client.get(root+'/export').content).files==Book(SAMPLE.read_bytes()).files
    assert client.post(root+'/redo',json={'revision':2}).status_code==200
    assert '天気' in details(client,root)['editor_text']
    assert client.post(root+'/undo',json={'revision':3}).status_code==200
    response=edit(client,root,P2,d['editor_text']+'追記。',revision=4)
    assert not response.json()['edit_state']['can_redo']
    assert client.post(root+'/redo',json={'revision':5}).status_code==422
    module.load_book.cache_clear()
    assert details(client,root)['editor_text'].endswith('追記。')
    assert len(client.get(root+'/history').json()['events'])==5

def test_conflict_and_xml_invalid_char_atomicity(session):
    client,create=session;root=create();d=details(client,root)
    edit(client,root,P2,d['editor_text']+'追記。')
    assert edit(client,root,P2,'古い上書き',0).status_code==409
    assert edit(client,root,P2,'不正\x00文字',1).status_code==422
    assert details(client,root)['revision']==1
    assert details(client,root)['editor_text'].endswith('追記。')

def test_insert_delete_across_inline_preserves_markup(session):
    client,create=session;root=create();d=details(client,root,P3)
    value=d['editor_text'].replace('、書物を','、古い本を')+'\n追記。'
    response=edit(client,root,P3,value)
    assert response.status_code==200,response.text
    book=Book(client.get(root+'/export').content)
    paragraph=book.trees['EPUB/chapter1.xhtml'].xpath('//x:p',namespaces=NS)[2]
    assert len(paragraph.findall('x:em',NS))==1
    assert details(client,root,P3)['editor_text']==value
    assert edit(client,root,P3,'',1).status_code==200
    assert client.post(root+'/undo',json={'revision':2}).status_code==200
    assert details(client,root,P3)['editor_text']==value

def test_replace_is_atomic_undoable_and_skips_ruby(session):
    client,create=session;root=create()
    response=client.post(root+'/replace',json={'revision':0,'target':'吾輩','replacement':'我輩'})
    assert response.status_code==200 and response.json()['edit_state']['revision']==0
    response=client.post(root+'/replace',json={'revision':0,'target':'天汽','replacement':'天気'})
    assert response.status_code==200 and '天気' in details(client,root)['editor_text']
    assert client.post(root+'/undo',json={'revision':1}).status_code==200
    assert '天汽' in details(client,root)['editor_text']

def test_doctype_and_xml_prolog_preserved_on_edit(session):
    client,create=session
    with zipfile.ZipFile(SAMPLE) as archive:source=archive.read('EPUB/chapter1.xhtml')
    root=create(changed({'EPUB/chapter1.xhtml':b'<?xml version="1.0"?>\n<?keep original?>\n<!DOCTYPE html>\n'+source}))
    d=details(client,root); response=edit(client,root,P2,d['editor_text'].replace('天汽','天気'))
    assert response.status_code==200,response.text
    book=Book(client.get(root+'/export').content)
    assert b'<!DOCTYPE html>' in book.files['EPUB/chapter1.xhtml']
    assert b'<?keep original?>' in book.files['EPUB/chapter1.xhtml']

def test_validation_unavailable_is_explicit(session,monkeypatch):
    client,create=session;root=create()
    monkeypatch.delenv('EPUBCHECK_JAR',raising=False)
    monkeypatch.delenv('JAVA_BIN',raising=False)
    monkeypatch.setattr('epub_proofreader.validation.shutil.which',lambda name:None)
    monkeypatch.setattr('epub_proofreader.validation.find_java',lambda:None)
    response=client.post(root+'/validate',json={'revision':0})
    assert response.status_code==200,response.text
    assert response.json()['internal']['status']=='passed'
    assert response.json()['epubcheck']['status']=='unavailable'

def test_text_markup_is_escaped_not_injected(session):
    client,create=session;root=create()
    response=edit(client,root,P2,'本文 <script>alert(1)</script> & 終わり')
    assert response.status_code==200,response.text
    book=Book(client.get(root+'/export').content)
    assert not book.trees['EPUB/chapter1.xhtml'].xpath('//x:script',namespaces=NS)
    assert '&lt;script&gt;' in book.files['EPUB/chapter1.xhtml'].decode()

def test_export_revision_and_atomic_multi_paragraph_replace(session):
    client,create=session
    with zipfile.ZipFile(SAMPLE) as archive:source=archive.read('EPUB/chapter2.xhtml')
    root=create(changed({'EPUB/chapter2.xhtml':source.replace('朝の光'.encode(),'天汽の光'.encode())}))
    response=client.post(root+'/replace',json={'revision':0,'target':'天汽','replacement':'天気'})
    assert response.status_code==200,response.text
    assert len(client.get(root+'/history').json()['events'][0]['paragraph_ids'])==2
    assert client.get(root+'/export?revision=0').status_code==409
    assert client.get(root+'/export?revision=1').status_code==200
    assert client.post(root+'/undo',json={'revision':1}).status_code==200
    assert '天汽' in details(client,root)['editor_text']
    assert '天汽' in details(client,root,'chapter0002-p00001')['editor_text']

def test_real_epubcheck_after_text_and_ruby_edit(session):
    import os
    if not os.getenv('EPUBCHECK_JAR'):
        pytest.skip('EPUBCheck integration requires EPUBCHECK_JAR and Java')
    client,create=session;root=create();d=details(client,root)
    edit(client,root,P2,d['editor_text'].replace('天汽','天気'))
    response=client.patch(root+f'/paragraphs/{P1}/rubies/0',json={'revision':1,'base':'我輩','reading':'わがはい'})
    assert response.status_code==200,response.text
    response=client.post(root+'/validate',json={'revision':2})
    assert response.status_code==200,response.text
    assert response.json()['epubcheck']['status']=='passed',response.json()['epubcheck']

def test_visible_heading_edit_preview_undo_export_and_project_replay(session):
    client,create=session;root=create()
    before=client.get(root).json();chapter=before['chapters'][0];heading=chapter['headings'][0];pid=heading['id']
    original=details(client,root,pid)['editor_text']
    assert not heading['structure_editable']
    preview=client.get(root+'/chapters/'+chapter['id']).json()['html']
    assert f'data-paragraph="{pid}"' in preview
    response=edit(client,root,pid,original+'（改訂）')
    assert response.status_code==200,response.text
    current=response.json()['chapters'][0]
    assert current['headings'][0]['edited']
    assert current['headings'][0]['original_text']==heading['text']
    assert current['paragraph_count']==chapter['paragraph_count']
    assert current['proof_units']==chapter['proof_units']
    assert '（改訂）' in current['title']
    output=client.get(root+'/export');assert output.status_code==200,output.text
    assert Book(output.content).chapters[0]['headings'][0]['text']==original+'（改訂）'
    assert client.get(root+'/original').content==SAMPLE.read_bytes()
    response=client.post(root+'/undo',json={'revision':1});assert response.status_code==200,response.text
    assert response.json()['chapters'][0]['headings'][0]['text']==heading['text']
    response=client.post(root+'/redo',json={'revision':2});assert response.status_code==200,response.text
    assert response.json()['chapters'][0]['headings'][0]['edited']
    archive=client.get(root+'/project/export');assert archive.status_code==200,archive.text
    restored=client.post('/api/projects/import',files={'file':('見出し.eproof',archive.content)})
    assert restored.status_code==200,restored.text
    assert restored.json()['chapters'][0]['headings'][0]['text']==original+'（改訂）'
