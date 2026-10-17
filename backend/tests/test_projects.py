import copy,io,json,zipfile
import pytest
from test_editing import session,details,edit,SAMPLE,P1,P2
from test_structure import operation,undo
from epub_proofreader import app as module
from epub_proofreader.epub import Book

def project(client,root):return client.get(root+'/project').json()
def patch(client,root,**changes):
    p=project(client,root);r=client.patch(root+'/project',json={'version':p['version'],**changes});assert r.status_code==200,r.text;return r.json()
def exported(client,root):
    r=client.get(root+'/project/export');assert r.status_code==200,r.text;return r.content
def imported(client,data):return client.post('/api/projects/import',files={'file':('作業.eproof',data)})
def rewrite(data,name,value,rehash=False):
    from hashlib import sha256
    with zipfile.ZipFile(io.BytesIO(data)) as z:files={n:z.read(n) for n in z.namelist()}
    files[name]=value
    if rehash:
        manifest=json.loads(files['manifest.json']);manifest['files'][name]=sha256(value).hexdigest();files['manifest.json']=json.dumps(manifest).encode()
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in files.items():z.writestr(name,value)
    return out.getvalue()

def test_combined_text_ruby_is_atomic_and_single_undo(session):
    client,create=session;root=create();d=details(client,root,P1)
    r=client.patch(root+'/paragraphs/'+P1+'/edit',json={'revision':0,'text':d['editor_text'].replace('名前','名まえ'),'rubies':[{'index':0,'base':'我輩','reading':'わがはい'}]})
    assert r.status_code==200,r.text
    now=details(client,root,P1);assert now['editor_text']=='我輩は猫である。名まえはまだない。'
    assert client.get(root+'/history').json()['events'][0]['action']=='combined'
    undo(client,root,1);assert details(client,root,P1)['editor_text']==d['editor_text']
    assert client.post(root+'/redo',json={'revision':2}).status_code==200
    before=client.get(root+'/export').content
    r=client.patch(root+'/paragraphs/'+P1+'/edit',json={'revision':3,'text':'我輩は猫である。名まえはまだない。追加。','rubies':[{'index':0,'base':'猫','reading':'\u0000'}]})
    assert r.status_code==422
    assert client.get(root+'/export').content==before

def test_project_full_roundtrip_pdf_status_mapping_draft_view_undo(session):
    client,create=session;root=create();d=details(client,root,P1)
    assert client.patch(root+'/paragraphs/'+P1+'/edit',json={'revision':0,'text':d['editor_text']+'追記。','rubies':[{'index':0,'base':'我輩','reading':'わがはい'}]}).status_code==200
    result=operation(client,root,'insert',P2,1,text='補完。');created=result['focus_paragraph_id']
    undo(client,root,2) # Preserve a redo branch in the portable project.
    pdf=(SAMPLE.parent/'original.pdf').read_bytes()
    r=client.post(root+'/pdf',files={'file':('原本.pdf',pdf)});assert r.status_code==200,r.text
    meta=r.json();digest=meta['pdf']['sha256']
    draft={'revision':3,'text':'未確定本文','rubies':{},'reason':'確認中','paragraphId':P2,'before':'元の本文'}
    patch(client,root,statuses={P1:'human_checked'},mappings={P1:[{'page':2,'rectangle':[.1,.2,.8,.9],'pdf_sha256':digest}]},drafts={P2+':all':draft},view={'chapterId':'chapter0001','paragraphId':P2,'sentenceIndex':None,'fontSize':24,'left':31,'right':29,'epubScroll':-123,'pdf':{'page':2,'mode':'custom','zoom':1.5,'scrollLeft':10,'scrollTop':20}})
    data=exported(client,root);r=imported(client,data);assert r.status_code==200,r.text
    new='/api/books/'+r.json()['id'];assert new!=root
    assert client.get(new+'/original').content==SAMPLE.read_bytes()
    assert client.get(new+'/export').content==client.get(root+'/export').content
    assert client.get(new+'/pdf').content==pdf
    restored=project(client,new);assert restored['drafts'][P2+':all']==draft
    assert restored['view']['pdf']['page']==2 and restored['mappings'][P1][0]['rectangle']==[.1,.2,.8,.9]
    assert restored['progress']['human_checked']==1 and restored['progress']['total']==6
    assert client.post(new+'/redo',json={'revision':3}).status_code==200
    assert details(client,new,created)['editor_text']=='補完。'
    module.load_book.cache_clear();assert project(client,new)['view']['fontSize']==24

def test_project_replays_split_merge_replace_and_ruby_history(session):
    client,create=session;root=create()
    result=operation(client,root,'split',P1,offset=8)
    operation(client,root,'merge',result['focus_paragraph_id'],1)
    assert client.post(root+'/replace',json={'revision':2,'target':'天汽','replacement':'天気'}).status_code==200
    assert client.patch(root+'/paragraphs/'+P1+'/rubies/0',json={'revision':3,'base':'我輩','reading':'わがはい'}).status_code==200
    r=imported(client,exported(client,root));assert r.status_code==200,r.text
    assert client.get('/api/books/'+r.json()['id']+'/export').content==client.get(root+'/export').content

def test_history_import_to_copy_and_reject_wrong_original(session):
    client,create=session;root=create();d=details(client,root)
    edit(client,root,P2,d['editor_text'].replace('天汽','天気'))
    history=client.get(root+'/history').json()
    r=client.post(root+'/history/import',files={'file':('history.json',json.dumps(history).encode())});assert r.status_code==200,r.text
    assert r.json()['id']!=root.rsplit('/',1)[1]
    history['original_sha256']='0'*64
    assert client.post(root+'/history/import',files={'file':('history.json',json.dumps(history).encode())}).status_code==422
    assert details(client,root)['revision']==1

@pytest.mark.parametrize('rehash',[False,True])
def test_project_tamper_rejected_atomically(session,rehash):
    client,create=session;root=create();d=details(client,root);edit(client,root,P2,d['editor_text']+'追加。')
    data=exported(client,root)
    with zipfile.ZipFile(io.BytesIO(data)) as z:state=json.loads(z.read('editing.json'))
    state['commands'][0]['changes'][0]['xpath']='/*/*[1]/*[1]'
    corrupted=rewrite(data,'editing.json',json.dumps(state).encode(),rehash)
    assert imported(client,corrupted).status_code==422
    assert client.get(root+'/original').content==SAMPLE.read_bytes()

def test_project_schema_zip_and_bad_pdf_rejected(session):
    client,create=session;root=create();data=exported(client,root)
    assert imported(client,b'not zip').status_code==422
    with zipfile.ZipFile(io.BytesIO(data)) as z:manifest=json.loads(z.read('manifest.json'))
    manifest['schema_version']=100
    assert imported(client,rewrite(data,'manifest.json',json.dumps(manifest).encode())).status_code==422
    assert client.post(root+'/pdf',files={'file':('wrong.pdf',b'not pdf')}).status_code==422
    assert project(client,root)['pdf'] is None

def test_metadata_conflict_validation_and_invalidation(session):
    client,create=session;root=create();meta=patch(client,root,statuses={P2:'human_checked'})
    assert client.patch(root+'/project',json={'version':0,'statuses':{P2:'review'}}).status_code==409
    assert client.patch(root+'/project',json={'version':meta['version'],'mappings':{P2:[{'page':1,'rectangle':[.9,.1,.2,.8],'pdf_sha256':'0'*64}]}}).status_code==422
    assert project(client,root)['version']==meta['version']
    edit(client,root,P2,details(client,root)['editor_text']+'変更。')
    assert project(client,root)['statuses'][P2]=='review'
    assert client.get(root).json()['chapters'][0]['paragraphs'][1]['status']=='review'
    assert project(client,root)['progress']['review']==1

def test_sentence_combined_edit_keeps_rubies_outside_sentence(session):
    from test_epub import changed
    client,create=session
    text='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>長い段落</title></head><body><p><ruby>漢字<rt>かんじ</rt></ruby>の文。'+('長い本文です。'*50)+'<ruby>最後<rt>さいご</rt></ruby>。</p></body></html>'
    root=create(changed({'EPUB/chapter1.xhtml':text.encode()}));d=details(client,root,P1)
    r=client.patch(root+'/paragraphs/'+P1+'/edit',json={'revision':0,'sentence_index':0,'expected_sentence':d['sentences'][0]['text'],'text':'漢字の文章。','rubies':[{'index':1,'base':'末尾','reading':'まつび'}]})
    assert r.status_code==422 and details(client,root,P1)['revision']==0
    r=client.patch(root+'/paragraphs/'+P1+'/edit',json={'revision':0,'sentence_index':0,'expected_sentence':d['sentences'][0]['text'],'text':'漢字の文章。','rubies':[{'index':0,'base':'文字','reading':'もじ'}]})
    assert r.status_code==200,r.text
    assert details(client,root,P1)['editor_text'].startswith('文字の文章。')
    assert details(client,root,P1)['rubies'][1]['base']=='最後'
    assert imported(client,exported(client,root)).status_code==200

@pytest.mark.parametrize('patch_value',[{'statuses':{P1:[]}}, {'view':{'pdf':{'page':0,'mode':'page','zoom':1}}}, {'view':{'epubScroll':float('inf')}}])
def test_malformed_metadata_is_rejected_without_mutation(session,patch_value):
    client,create=session;root=create();before=project(client,root)
    # httpx correctly disallows Infinity in normal JSON; send it explicitly to test the parser boundary.
    r=client.patch(root+'/project',content=json.dumps({'version':0,**patch_value}),headers={'Content-Type':'application/json'})
    assert r.status_code==422,r.text
    assert project(client,root)==before

@pytest.mark.skipif(not __import__('os').getenv('EPUBCHECK_JAR'),reason='requires EPUBCheck')
def test_combined_project_export_passes_epubcheck(session):
    client,create=session;root=create();d=details(client,root,P1)
    assert client.patch(root+'/paragraphs/'+P1+'/edit',json={'revision':0,'text':d['editor_text'].replace('名前','名まえ'),'rubies':[{'index':0,'base':'我輩','reading':'わがはい'}]}).status_code==200
    restored=imported(client,exported(client,root));assert restored.status_code==200,restored.text
    r=client.post('/api/books/'+restored.json()['id']+'/validate',json={'revision':1})
    assert r.status_code==200,r.text
    assert r.json()['epubcheck']['status']=='passed',r.json()

def test_pdf_follow_preference_survives_project_roundtrip_and_rejects_non_boolean(session):
    client,create=session;root=create()
    settings={'page':1,'zoom':1,'mode':'page','scrollLeft':0,'scrollTop':0,'followText':False}
    patch(client,root,view={'pdf':settings})
    restored=imported(client,exported(client,root));assert restored.status_code==200,restored.text
    assert restored.json()['project']['view']['pdf']['followText'] is False
    for value in ['true',1,None,{}]:
        meta=project(client,root)
        response=client.patch(root+'/project',json={'version':meta['version'],'view':{'pdf':{**settings,'followText':value}}})
        assert response.status_code==422,response.text
    assert project(client,root)['view']['pdf']['followText'] is False


def test_manual_update_then_confirmation_preserves_checked_flag_and_allows_heading(session):
    from test_editing import edit,details,P2
    c,create=session;root=create()
    r=edit(c,root,P2,details(c,root)['editor_text']+'校正。');assert r.status_code==200
    meta=c.get(root+'/project').json()
    r=c.patch(root+'/project',json={'version':meta['version'],'statuses':{P2:'human_checked'},'drafts':{'body:'+P2+':all':None}})
    assert r.status_code==200,r.text
    assert r.json()['statuses'][P2]=='human_checked' and r.json()['progress']['human_checked']==1
    book=c.get(root).json();assert book['chapters'][0]['paragraphs'][1]['status']=='human_checked'
    heading=book['chapters'][0]['headings'][0]['id']
    r=c.patch(root+'/project',json={'version':r.json()['version'],'statuses':{heading:'human_checked'}})
    assert r.status_code==200,r.text
    assert c.get(root).json()['chapters'][0]['headings'][0]['status']=='human_checked'
