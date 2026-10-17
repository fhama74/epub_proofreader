import uuid,io,json,zipfile,os
import pytest
from test_editing import session,details,edit,SAMPLE,P2
from epub_proofreader import app as module,library
from epub_proofreader.epub import Book,NS,xml

def publish(client,root,revision=0,version=0,token=None):
    return client.post(root+'/publish',json={'revision':revision,'expected_version':version,'request_id':token or str(uuid.uuid4())})

@pytest.fixture(autouse=True)
def checker(monkeypatch,request):
    if 'real' not in request.node.name:monkeypatch.setattr('epub_proofreader.project_api.epubcheck',lambda data:{'status':'passed'})

def test_catalog_uploads_duplicate_names_optional_pdf_and_restart(session):
    client,create=session;one=create();two=create()
    items=client.get('/api/projects').json();assert len(items['projects'])==2
    assert all(p['filename']=='本.epub' and p['uploaded_at'].endswith('+00:00') for p in items['projects'])
    assert all(not p['pdf_attached'] and p['published_version']==0 for p in items['projects'])
    assert items['storage']['used_bytes']>=len(SAMPLE.read_bytes())*2
    module.load_book.cache_clear();assert client.get(one).status_code==200 and client.get(two).status_code==200

def test_publish_counter_embedded_metadata_idempotence_and_immutable_archive(session):
    client,create=session;root=create();token=str(uuid.uuid4());first=publish(client,root,token=token)
    assert first.status_code==200,first.text
    assert first.json()['publication']['version']==1
    data=client.get(root+'/publications/1/epub').content
    assert library.embedded_version(Book(data))==1
    assert publish(client,root,token=token).json()['publication']['version']==1
    assert publish(client,root).status_code==409
    d=details(client,root);edit(client,root,P2,d['editor_text']+'校正。')
    second=publish(client,root,revision=1,version=1)
    assert second.status_code==200,second.text
    assert second.json()['publication']['version']==2
    assert client.get(root+'/publications/1/epub').content==data
    assert len(client.get(root+'/publications').json()['publications'])==2
    assert client.get(root+'/original').content==SAMPLE.read_bytes()
    first_book=Book(data);source=Book(SAMPLE.read_bytes())
    assert first_book.metadata['identifier']==source.metadata['identifier']
    assert all(first_book.files[path]==value for path,value in source.files.items() if path!=source.opf_path)
    assert first_book.manifest==source.manifest and first_book.toc==source.toc
    assert 'v001.epub' in client.get(root+'/publications/1/epub').headers['content-disposition']
    module.load_book.cache_clear();assert client.get(root).json()['catalog']['published_version']==2

def test_publish_validation_failure_and_concurrent_edit_do_not_count(session,monkeypatch):
    client,create=session;root=create()
    monkeypatch.setattr('epub_proofreader.project_api.epubcheck',lambda data:{'status':'failed'})
    assert publish(client,root).status_code==422
    assert client.get(root).json()['catalog']['published_version']==0
    def changed_during_validation(data):
        edit(client,root,P2,details(client,root)['editor_text']+'別の編集。')
        return {'status':'passed'}
    monkeypatch.setattr('epub_proofreader.project_api.epubcheck',changed_during_validation)
    assert publish(client,root).status_code==409
    assert client.get(root+'/publications').json()['publications']==[]

def test_published_epub_upload_and_work_backup_continue_version(session):
    client,create=session;root=create();r=publish(client,root);assert r.status_code==200,r.text
    data=client.get(root+'/publications/1/epub').content
    new=create(data);assert client.get(new).json()['catalog']['published_version']==1
    assert publish(client,new,version=1).json()['publication']['version']==2
    backup=client.get(root+'/project/export').content
    r=client.post('/api/projects/import',files={'file':('保存.eproof',backup)});assert r.status_code==200,r.text
    restored='/api/books/'+r.json()['id']
    assert r.json()['catalog']['published_version']==1
    assert client.get(restored+'/publications').json()['publications']==[]
    assert publish(client,restored,version=1).json()['publication']['version']==2

def test_explicit_deletion_removes_only_target_project(session):
    client,create=session;root=create();other=create();publish(client,root)
    assert client.post(root+'/delete',json={'filename':'wrong.epub','revision':0,'published_version':1}).status_code==409
    r=client.post(root+'/delete',json={'filename':'本.epub','revision':0,'published_version':1});assert r.status_code==200,r.text
    assert client.get(root).status_code==404 and client.get(root+'/publications/1/epub').status_code==404
    assert client.get(other).status_code==200
    assert len(client.get('/api/projects').json()['projects'])==1

@pytest.mark.skipif(not os.getenv('EPUBCHECK_JAR'),reason='requires EPUBCheck')
def test_real_versioned_publication_passes_epubcheck(session):
    client,create=session;root=create();r=publish(client,root)
    assert r.status_code==200,r.text
    assert r.json()['publication']['validation']['epubcheck']['status']=='passed'

def test_existing_database_migrates_without_inventing_upload_time(tmp_path,monkeypatch):
    import sqlite3
    from fastapi.testclient import TestClient
    monkeypatch.setattr(module,'DATA_DIR',tmp_path);module.load_book.cache_clear();identifier=str(uuid.uuid4())
    with sqlite3.connect(tmp_path/'library.sqlite3') as con:
        con.execute('CREATE TABLE books(id TEXT PRIMARY KEY,name TEXT NOT NULL,original BLOB NOT NULL)')
        con.execute('INSERT INTO books VALUES (?,?,?)',(identifier,'以前の本.epub',SAMPLE.read_bytes()))
    client=TestClient(module.app);item=client.get('/api/projects').json()['projects'][0]
    assert item['uploaded_at'] is None and item['filename']=='以前の本.epub'
    assert client.get('/api/books/'+identifier+'/original').content==SAMPLE.read_bytes()

def test_simultaneous_publish_requests_only_create_one_version(session,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    client,create=session;root=create();barrier=threading.Barrier(2)
    def check(data):barrier.wait(timeout=5);return {'status':'passed'}
    monkeypatch.setattr('epub_proofreader.project_api.epubcheck',check)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:publish(client,root),range(2)))
    assert sorted(r.status_code for r in results)==[200,409]
    assert len(client.get(root+'/publications').json()['publications'])==1

def test_custom_prefix_collision_is_preserved(session):
    from test_epub import changed
    client,create=session
    with zipfile.ZipFile(SAMPLE) as z:opf=z.read('EPUB/package.opf')
    root=xml(opf);root.set('prefix','eproof: urn:other:')
    from lxml import etree
    n=etree.SubElement(root.find('opf:metadata',NS),'{'+NS['opf']+'}meta',property='eproof:version');n.text='別の属性'
    project=create(changed({'EPUB/package.opf':etree.tostring(root)}))
    result=publish(client,project);assert result.status_code==200,result.text
    output=Book(client.get(project+'/publications/1/epub').content);assert library.embedded_version(output)==1
    result_opf=xml(output.get(output.opf_path));assert result_opf.xpath('opf:metadata/opf:meta[@property="eproof:version"]/text()',namespaces=NS)==['別の属性']
