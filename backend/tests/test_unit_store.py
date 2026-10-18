import io
import sqlite3
import zipfile
import json
import pytest
from fastapi.testclient import TestClient
from epub_proofreader import app as module, unit_store
from epub_proofreader.epub import Book
from test_editing import SAMPLE, P1, P2


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'DATA_DIR',tmp_path)
    module.load_book.cache_clear()
    c=TestClient(module.app)
    c.headers['X-Edit-Owner']='test-browser'
    yield c
    c.close()


def create(client,data=None):
    r=client.post('/api/books',files={'file':('本.epub',data or SAMPLE.read_bytes())})
    assert r.status_code==200,r.text
    return '/api/books/'+r.json()['id'],r.json()


def detail(client,root,pid=P2):
    r=client.get(root+'/paragraphs/'+pid)
    assert r.status_code==200,r.text
    return r.json()


def test_import_roundtrip_preview(client):
    root,b=create(client)
    assert b['storage_mode']=='units'
    for chapter in b['chapters']:
        r=client.get(root+'/chapters/'+chapter['id'])
        assert r.status_code==200,r.text
    r=client.get(root+'/export');assert r.status_code==200,r.text
    assert Book(r.content).files==Book(SAMPLE.read_bytes()).files


def test_leaf_update_and_conflict(client):
    root,b=create(client);d=detail(client,root)
    request=dict(revision=0,expected_token=d['token'],text=d['editor_text'].replace('天汽','天気'))
    r=client.patch(root+'/paragraphs/'+P2,json=request)
    assert r.status_code==200,r.text
    assert r.json()['kind']=='unit_patch'
    assert r.json()['paragraph']['unit_version']==2
    assert r.json()['paragraph']['review_state']['body']['confirmed']
    assert client.patch(root+'/paragraphs/'+P2,json=request).status_code==409
    assert detail(client,root,P1)['unit_version']==1
    output=client.get(root+'/export');assert output.status_code==200,output.text
    original=Book(SAMPLE.read_bytes());edited=Book(output.content)
    assert '天気' in edited.chapters[0]['paragraphs'][1]['text']
    for path,value in original.files.items():
        if path!='EPUB/chapter1.xhtml':assert edited.files[path]==value


def test_order_keys():
    left='0000000000018';right='0000000000028'
    for _ in range(500):
        mid=unit_store.key_between(left,right)
        assert left<mid<right
        right=mid


def change(client,root,pid,text):
    d=detail(client,root,pid)
    r=client.patch(root+'/paragraphs/'+pid,json=dict(revision=d['revision'],expected_token=d['token'],text=text))
    assert r.status_code==200,r.text
    return r.json()


def structure(client,root,action,pid=P2,**kw):
    d=detail(client,root,pid)
    r=client.post(root+'/structure',json=dict(action=action,paragraph_id=pid,revision=d['revision'],expected_token=d['token'],expected_chapter_token=d['chapter_token'],**kw))
    assert r.status_code==200,r.text
    return r.json()


def test_split_merge_stable_ids_and_versions(client):
    root,b=create(client);before=detail(client,root)
    b=structure(client,root,'split',offset=before['editor_text'].index('。')+1)
    new=b['focus_paragraph_id'];assert new!=P2
    left=detail(client,root);right=detail(client,root,new)
    assert left['editor_text']+right['editor_text']==before['editor_text']
    assert left['unit_version']==2 and right['unit_version']==1
    b=structure(client,root,'merge',pid=new)
    assert b['focus_paragraph_id']==P2
    assert detail(client,root)['editor_text']==before['editor_text']
    assert detail(client,root)['unit_version']==3
    assert client.get(root+'/paragraphs/'+new).status_code==422
    with module.database() as con:
        assert con.execute('SELECT active,version FROM unit_nodes WHERE id=?',(new,)).fetchone()==(0,2)


def test_chapter_same_file_and_heading_update_backup(client):
    root,b=create(client);before=Book(client.get(root+'/export').content);d=detail(client,root)
    r=client.post(root+'/chapters/split',json=dict(paragraph_id=P2,revision=d['revision'],expected_token=d['token'],expected_chapter_token=d['chapter_token'],title='新しい章',level=2))
    assert r.status_code==200,r.text
    b=r.json();assert len(b['chapters'])==3
    h=b['focus_paragraph_id'];assert any(c['title']=='新しい章' and c['path']=='EPUB/chapter1.xhtml' for c in b['chapters'])
    change(client,root,h,'変更した章')
    out=client.get(root+'/export');assert out.status_code==200,out.text
    after=Book(out.content)
    assert set(after.files)==set(before.files)
    assert any(t['label']=='変更した章' for t in after.toc)
    archive=client.get(root+'/project/export');assert archive.status_code==200,archive.text
    r=client.post('/api/projects/import',files={'file':('本.eproof',archive.content)})
    assert r.status_code==200,r.text
    imported='/api/books/'+r.json()['id']
    assert Book(client.get(imported+'/export').content).files==after.files
    assert detail(client,imported,h)['unit_version']==detail(client,root,h)['unit_version']
    assert detail(client,imported,h)['review_state']['body']['confirmed']


def test_locks_expiry_and_granular_concurrency(client):
    root,b=create(client);a=detail(client,root,P1);b=detail(client,root,P2)
    assert client.post(root+'/paragraphs/'+P1+'/lock').status_code==200
    headers={'X-Edit-Owner':'other-browser'}
    assert client.post(root+'/paragraphs/'+P1+'/lock',headers=headers).status_code==409
    # A different paragraph may save using an older book revision.
    r=client.patch(root+'/paragraphs/'+P2,headers=headers,json=dict(revision=b['revision'],expected_token=b['token'],text=b['editor_text']+'追記。'))
    assert r.status_code==200,r.text
    r=client.patch(root+'/paragraphs/'+P1,json=dict(revision=a['revision'],expected_token=a['token'],text=a['editor_text']+'追記。'))
    assert r.status_code==200,r.text
    with module.database() as con:con.execute('UPDATE unit_locks SET expires=0')
    assert client.post(root+'/paragraphs/'+P1+'/lock',headers=headers).status_code==200


def test_confirmation_only_and_no_reassembly_on_save(client,monkeypatch):
    root,b=create(client);d=detail(client,root)
    def forbidden(*a,**kw):raise AssertionError('ordinary saves must not rebuild book/EPUB')
    monkeypatch.setattr(unit_store,'state',forbidden)
    r=client.post(root+'/paragraphs/'+P2+'/review',json=dict(expected_token=d['token'],compact=True))
    assert r.status_code==200,r.text
    assert detail(client,root)['unit_version']==1
    change(client,root,P2,d['editor_text']+'追記。')
    left=None;right='8'
    for _ in range(500):
        mid=unit_store.key_between(left,right)
        assert mid<right
        right=mid


def test_ai_reads_latest_and_binds_version(client,monkeypatch):
    from test_ai import job,finish,state,parse_prompt,hit
    from epub_proofreader.ai.providers import PROVIDERS
    from epub_proofreader.ai.providers.base import Reply
    root,b=create(client);calls=[]
    def generate(cfg,system,prompt):
        p=parse_prompt(prompt);calls.append(p)
        findings=[hit(p,'汽','気')] if p['query_type']=='body' and '汽' in p['target'] else []
        return Reply(json.dumps({'findings':findings} if p['query_type']=='body' else {'suggestions':[]}),10,2)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    ident=job(client,root)
    before=detail(client,root)['editor_text'];change(client,root,P2,before+'最新の追記。')
    finish(ident)
    assert calls and '最新の追記。' in calls[0]['target']
    results=state(client,root)['results'];assert len(results)==1 and not results[0]['stale']
    with module.database() as con:
        assert con.execute('SELECT unit_id,version FROM ai_result_units').fetchone()==(P2,2)
    r=client.post(root+'/ai/results/'+results[0]['id']+'/decision',json={'action':'approve','revision':1})
    assert r.status_code==200,r.text
    assert '天気' in detail(client,root)['editor_text']
    assert detail(client,root)['unit_version']==3


def test_ai_edited_during_response_requeues_without_stale_result(client,monkeypatch):
    from test_ai import job,run,state,parse_prompt,hit,finish
    from epub_proofreader.ai.providers import PROVIDERS
    from epub_proofreader.ai.providers.base import Reply
    root,b=create(client);calls=[]
    def generate(cfg,system,prompt):
        p=parse_prompt(prompt);calls.append(p)
        if len(calls)==1:change(client,root,P2,detail(client,root)['editor_text']+'応答待ち中の変更。')
        return Reply(json.dumps({'findings':[hit(p)]}),10,2)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    ident=job(client,root);run(ident)
    assert not state(client,root)['results']
    with module.database() as con:assert con.execute('SELECT status FROM ai_items WHERE job_id=?',(ident,)).fetchone()[0]=='pending'
    finish(ident)
    assert '応答待ち中の変更。' in calls[-1]['target']
    assert not state(client,root)['results'][0]['stale']


def test_migrate_existing_edited_database(client,monkeypatch,tmp_path):
    import hashlib
    from epub_proofreader import editing,projects
    monkeypatch.setattr(unit_store,'USE_NEW_STORAGE',False)
    root,b=create(client)
    d=detail(client,root)
    r=client.patch(root+'/paragraphs/'+P2,json={'revision':0,'text':d['editor_text']+'保存済みの変更。'})
    assert r.status_code==200,r.text
    expected=Book(client.get(root+'/export').content).files
    pdf=b'%PDF-1.7\nsynthetic attachment'
    assert client.post(root+'/pdf',files={'file':('test.pdf',pdf)}).status_code==200
    legacy=tmp_path/'library.sqlite3';digest=hashlib.sha256(legacy.read_bytes()).hexdigest()
    monkeypatch.setattr(unit_store,'USE_NEW_STORAGE',True);module.load_book.cache_clear()
    b=client.get(root);assert b.status_code==200,b.text
    assert b.json()['storage_mode']=='units'
    assert b.json()['catalog']['uploaded_at'] is not None
    assert Book(client.get(root+'/export').content).files==expected
    assert client.get(root+'/pdf').content==pdf
    assert not detail(client,root)['review_state']['body']['confirmed']
    assert (tmp_path/unit_store.DB_NAME).exists()
    assert hashlib.sha256(legacy.read_bytes()).hexdigest()==digest


def test_preserve_noneditable_xml_and_ruby_operations(client):
    from test_epub import changed
    from epub_proofreader.epub import NS,xml
    document='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<!--before--><?keep before?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:z="urn:custom"><head><title>題</title><meta name="custom" content="keep"/></head><body id="body"><section class="kept"><!--middle--><p id="p1">先頭<ruby>漢字<rt>かんじ</rt></ruby>末尾。</p><div z:a="value"><p>ここを更新。</p></div><figure><img src="images/sample.png" alt="image"/></figure><table><tr><td>表の文字</td></tr></table><z:unknown x="1">残す</z:unknown></section></body></html><!--after--><?keep after?>'''
    root,b=create(client,changed({'EPUB/chapter1.xhtml':document.encode()}))
    d=detail(client,root,P1)
    r=client.patch(root+'/paragraphs/'+P1+'/rubies/0',json={'revision':0,'expected_token':d['token'],'base':'漢字','reading':'カンジ'})
    assert r.status_code==200,r.text
    d=detail(client,root,P1)
    r=client.post(root+'/paragraphs/'+P1+'/ruby-structure',json={'action':'delete','index':0,'expected_token':d['token'],'revision':d['revision']})
    assert r.status_code==200,r.text
    d=detail(client,root,P1);assert d['editor_text']=='先頭漢字末尾。'
    r=client.post(root+'/paragraphs/'+P1+'/ruby-structure',json={'action':'add','start':2,'end':4,'reading':'かんじ','expected_token':d['token'],'revision':d['revision']})
    assert r.status_code==200,r.text
    change(client,root,P2,'ここを校正。')
    out=client.get(root+'/export');assert out.status_code==200,out.text
    saved=Book(out.content).get('EPUB/chapter1.xhtml')
    for part in (b'<!--before-->',b'<!--after-->',b'<?keep before?>',b'<?keep after?>',b'<!DOCTYPE html>',b'<!--middle-->',b'standalone=\'yes\''):
        assert part in saved
    parsed=xml(saved)
    assert parsed.xpath('string(//z:unknown)',namespaces={'z':'urn:custom'})=='残す'
    assert parsed.xpath('string(//x:td)',namespaces=NS)=='表の文字'
    assert parsed.xpath('string(//x:ruby/x:rt)',namespaces=NS)=='かんじ'


def test_delete_heading_joins_across_original_files_without_file_changes(client):
    root,b=create(client);second=b['chapters'][1];h=second['headings'][0]['id']
    original=Book(client.get(root+'/export').content)
    b=structure(client,root,'chapter_merge',pid=h)
    assert len(b['chapters'])==1
    assert b['chapters'][0]['paragraph_count']==6
    assert b['chapters'][0]['parts']==['EPUB/chapter1.xhtml','EPUB/chapter2.xhtml']
    preview=client.get(root+'/chapters/'+b['chapters'][0]['id'])
    assert preview.status_code==200,preview.text
    assert P1 in preview.json()['html'] and 'chapter0002-p00003' in preview.json()['html']
    out=client.get(root+'/export');assert out.status_code==200,out.text
    assert set(Book(out.content).files)==set(original.files)
    archive=client.get(root+'/project/export')
    r=client.post('/api/projects/import',files={'file':('joined.eproof',archive.content)})
    assert r.status_code==200,r.text
    assert len(r.json()['chapters'])==1


def test_sentence_boundary_empty_insert_and_last_paragraph_delete(client):
    from test_epub import changed
    text='長い本文を確認する。'*32
    document='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head><body><h1>T</h1><p>'+text+'</p>段落外の末尾</body></html>'
    root,b=create(client,changed({'EPUB/chapter1.xhtml':document.encode()}));pid=P1
    d=detail(client,root,pid);assert d['unit_mode']=='sentence'
    unit_count=len(d['sentences'])
    b=structure(client,root,'insert_boundary',pid=pid,sentence_index=1,position='after',text='')
    parts=b['chapters'][0]['paragraphs'];assert len(parts)==2 and all(p['text'] for p in parts)
    assert ''.join(p['text'] for p in parts)==text
    out=Book(client.get(root+'/export').content).get('EPUB/chapter1.xhtml').decode()
    assert out.index('段落外の末尾')>out.rindex('</p>')
    b=structure(client,root,'insert_boundary',pid=parts[0]['id'],position='after',text='')
    assert b['chapters'][0]['paragraphs'][1]['text']==''


def test_new_export_passes_real_epubcheck(client):
    import os
    if not os.getenv('EPUBCHECK_JAR'):pytest.skip('requires EPUBCheck')
    from epub_proofreader.validation import epubcheck
    root,b=create(client);d=detail(client,root)
    r=client.post(root+'/chapters/split',json=dict(paragraph_id=P2,revision=d['revision'],expected_token=d['token'],expected_chapter_token=d['chapter_token'],title='新しい章',level=2))
    assert r.status_code==200,r.text
    change(client,root,P2,d['editor_text'].replace('天汽','天気'))
    output=client.get(root+'/export');assert output.status_code==200,output.text
    check=epubcheck(output.content)
    assert check['status']=='passed',check


def test_identical_text_is_replaced_only_at_selected_unit_and_sentence(client):
    from test_epub import changed
    repeated='今日も同じ文を読む。'*40
    document='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head><body><h1>T</h1><p>'+repeated+'</p><p>'+repeated+'</p></body></html>'
    root,b=create(client,changed({'EPUB/chapter1.xhtml':document.encode()}));d=detail(client,root)
    s=d['sentences'][25];new='ここだけ訂正した。'
    r=client.patch(root+'/paragraphs/'+P2,json=dict(revision=0,expected_token=d['token'],sentence_index=25,expected_sentence=s['text'],text=new))
    assert r.status_code==200,r.text
    assert detail(client,root,P1)['editor_text']==repeated
    assert detail(client,root,P2)['editor_text']==repeated[:s['start']]+new+repeated[s['end']:]


def test_review_reset_and_atomic_merge_lock_conflict(client):
    root,b=create(client);d=detail(client,root)
    r=client.post(root+'/paragraphs/'+P2+'/review',json=dict(expected_token=d['token'],compact=True));assert r.status_code==200
    assert detail(client,root)['review_state']['body']['confirmed']
    r=client.post(root+'/review/reset',json={'scope':'paragraph','paragraph_id':P2,'target':'body'})
    assert r.status_code==200,r.text
    assert not detail(client,root)['review_state']['body']['confirmed']
    with module.database() as con:assert not con.execute('SELECT 1 FROM unit_reviews').fetchall()
    assert client.post(root+'/paragraphs/'+P1+'/lock',headers={'X-Edit-Owner':'other'}).status_code==200
    before=client.get(root+'/export').content
    d=detail(client,root)
    r=client.post(root+'/structure',json=dict(action='merge',paragraph_id=P2,revision=d['revision'],expected_token=d['token'],expected_chapter_token=d['chapter_token']))
    assert r.status_code==409,r.text
    assert Book(client.get(root+'/export').content).files==Book(before).files


def test_nested_lists_are_preserved_and_preview_as_one_editable_unit(client):
    from test_epub import changed
    doc='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>T</title></head><body><h1>T</h1><ul><li>親項目<ul><li>子項目。</li></ul></li></ul><p>本文。</p></body></html>'
    root,b=create(client,changed({'EPUB/chapter1.xhtml':doc.encode()}))
    r=client.get(root+'/chapters/'+b['chapters'][0]['id'])
    assert r.status_code==200,r.text
    assert '子項目' in r.json()['html']
    assert client.get(root+'/export').status_code==200


def test_merge_invalidates_prior_confirmation_and_project_status_is_version_bound(client):
    root,b=create(client);d=detail(client,root,P1)
    r=client.post(root+'/paragraphs/'+P1+'/review',json=dict(expected_token=d['token'],compact=True));assert r.status_code==200
    structure(client,root,'merge',pid=P2)
    assert not detail(client,root,P1)['review_state']['body']['confirmed']
    assert client.get(root+'/project').json()['statuses'][P1]=='unchecked'
    meta=client.get(root+'/project').json()
    r=client.patch(root+'/project',json={'version':meta['version'],'statuses':{P1:'human_checked'}})
    assert r.status_code==200,r.text
    assert detail(client,root,P1)['review_state']['body']['confirmed']
    r=client.patch(root+'/project',json={'version':r.json()['version'],'statuses':{P1:'unchecked'}})
    assert r.status_code==200,r.text
    assert not detail(client,root,P1)['review_state']['body']['confirmed']
