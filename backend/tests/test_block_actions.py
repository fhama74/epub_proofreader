import os
import pytest
from epub_proofreader.epub import Book,NS
from test_editing import session,details,SAMPLE,P1,P2,P3
from test_epub import changed

FIRST='あ'*110+'。'
SECOND='東京'+'い'*110+'。'
THIRD='う'*110+'。'
SOURCE='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>部</title></head><body><h1>部</h1><p>前段落。</p><p id="long">'+FIRST+'<ruby>東京<rt>とうきょう</rt></ruby>'+'い'*110+'。'+THIRD+'</p><p>後段落。</p></body></html>'

def create_book(create):return create(changed({'EPUB/chapter1.xhtml':SOURCE.encode()}))
def act(c,root,path,**options):
    d=details(c,root,options.get('paragraph_id',P2))
    return c.post(root+path,json={'revision':d['revision'],'expected_token':d['token'],'expected_chapter_token':d['chapter_token'],'paragraph_id':P2,**options})
def exported(c,root):
    r=c.get(root+'/export');assert r.status_code==200,r.text
    return Book(r.content)
def round_trip(c,root,original):
    out=exported(c,root);r=c.post('/api/projects/import',files={'file':('boundaries.eproof',c.get(root+'/project/export').content)})
    assert r.status_code==200,r.text
    assert exported(c,'/api/books/'+r.json()['id']).files==out.files
    rev=c.get(root).json()['edit_state']['revision']
    assert c.post(root+'/undo',json={'revision':rev}).status_code==200
    assert exported(c,root).files==Book(original).files
    assert c.post(root+'/redo',json={'revision':rev+1}).status_code==200
    assert exported(c,root).files==out.files

@pytest.mark.parametrize('position,left,right',[('before',FIRST,SECOND+THIRD),('after',FIRST+SECOND,THIRD)])
def test_insert_next_to_sentence_is_atomic_and_preserves_ruby_ids_and_backup(session,position,left,right):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    r=act(c,root,'/structure',action='insert',position=position,sentence_index=1,text='追加。')
    assert r.status_code==200,r.text
    chapter=r.json()['chapters'][0];assert [p['text'] for p in chapter['paragraphs']]==['前段落。',left,'追加。',right,'後段落。']
    assert chapter['paragraphs'][1]['id']==P2 and chapter['paragraphs'][-1]['id']==P3
    assert r.json()['focus_paragraph_id']==chapter['paragraphs'][2]['id']
    assert chapter['paragraph_count']==5 and r.json()['edit_state']['edit_count']==1
    assert exported(c,root).trees['EPUB/chapter1.xhtml'].xpath('//x:rt/text()',namespaces=NS)==['とうきょう']
    round_trip(c,root,original)

@pytest.mark.parametrize('position,left,right',[('before',FIRST,SECOND+THIRD),('after',FIRST+SECOND,THIRD)])
def test_chapter_next_to_sentence_splits_paragraph_and_nests_toc(session,position,left,right):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    r=act(c,root,'/chapters/split',position=position,sentence_index=1,title='一',level=2)
    assert r.status_code==200,r.text
    chapters=r.json()['chapters'];assert [p['text'] for p in chapters[0]['paragraphs']]==['前段落。',left]
    assert [p['text'] for p in chapters[1]['paragraphs']]==[right,'後段落。']
    assert chapters[0]['paragraphs'][1]['id']==P2 and chapters[1]['paragraphs'][1]['id']==P3
    assert r.json()['focus_paragraph_id']==chapters[1]['paragraphs'][0]['id']
    out=exported(c,root);nav=next(m['path'] for m in out.manifest if 'nav' in m['properties'].split())
    assert out.trees[nav].xpath('//x:nav/x:ol/x:li[1]/x:ol/x:li/x:a/text()',namespaces=NS)==['一']
    assert sum(len(t.xpath('//x:rt',namespaces=NS)) for t in out.trees.values())==sum(len(t.xpath('//x:rt',namespaces=NS)) for t in Book(original).trees.values())
    round_trip(c,root,original)

@pytest.mark.parametrize('kind,expected',[('merge',['前段落。'+FIRST+SECOND+THIRD,'後段落。']),('merge_next',['前段落。',FIRST+SECOND+THIRD+'後段落。'])])
def test_merge_uses_whole_paragraph_even_with_sentence_selection(session,kind,expected):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    r=act(c,root,'/structure',action=kind,sentence_index=1)
    assert r.status_code==200,r.text
    assert [p['text'] for p in r.json()['chapters'][0]['paragraphs']]==expected
    round_trip(c,root,original)

def test_after_last_paragraph_creates_editable_empty_chapter(session):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    r=act(c,root,'/chapters/split',paragraph_id=P3,position='after',title='続き',level=1)
    assert r.status_code==200,r.text
    assert r.json()['chapters'][0]['paragraph_count']==3
    assert [p['text'] for p in r.json()['chapters'][1]['paragraphs']]==['']
    assert r.json()['focus_paragraph_id']==r.json()['chapters'][1]['paragraphs'][0]['id']
    round_trip(c,root,original)

@pytest.mark.parametrize('position,index',[('before',0),('after',2)])
def test_edge_sentence_insert_does_not_create_extra_empty_paragraphs(session,position,index):
    c,create=session;root=create_book(create)
    r=act(c,root,'/structure',action='insert',position=position,sentence_index=index,text='')
    assert r.status_code==200,r.text
    assert r.json()['chapters'][0]['paragraph_count']==4
    archive=c.get(root+'/project/export');r=c.post('/api/projects/import',files={'file':('edge.eproof',archive.content)})
    assert r.status_code==200,r.text

@pytest.mark.parametrize('path,options',[('/structure',{'action':'insert','sentence_index':999}),('/chapters/split',{'title':'一','sentence_index':999,'position':'after'}),('/structure',{'action':'merge_next','paragraph_id':P3})])
def test_invalid_positions_leave_book_unchanged(session,path,options):
    c,create=session;root=create_book(create);before=c.get(root).json()
    r=act(c,root,path,**options);assert r.status_code==422,r.text
    assert c.get(root).json()==before

@pytest.mark.skipif(not os.getenv('EPUBCHECK_JAR'),reason='EPUBCheck unavailable')
def test_epubcheck_sentence_chapter_and_insert(session):
    c,create=session;root=create()
    r=act(c,root,'/chapters/split',title='一',level=2,position='after',sentence_index=0)
    assert r.status_code==200,r.text
    report=c.post(root+'/validate',json={'revision':1}).json();assert report['epubcheck']['status']=='passed',report
    root=create();r=act(c,root,'/structure',action='insert',sentence_index=0,position='after',text='挿入。');assert r.status_code==200,r.text
    report=c.post(root+'/validate',json={'revision':1}).json();assert report['epubcheck']['status']=='passed',report

@pytest.mark.parametrize('chapter',[False,True])
def test_split_content_resets_only_affected_review_and_inherits_pdf_mapping(session,chapter):
    c,create=session;root=create_book(create)
    for pid in (P2,P3):
        d=details(c,root,pid);assert c.post(root+'/paragraphs/'+pid+'/review',json={'target':'body','expected_token':d['token']}).status_code==200
    meta=c.get(root+'/project').json();mapping={'page':2,'rectangle':None,'pdf_sha256':'a'*64}
    assert c.patch(root+'/project',json={'version':meta['version'],'mappings':{P2:[mapping]}}).status_code==200
    path='/chapters/split' if chapter else '/structure'
    options={'title':'一','level':2} if chapter else {'action':'insert','text':'追加。'}
    r=act(c,root,path,position='after',sentence_index=0,**options);assert r.status_code==200,r.text
    assert not details(c,root,P2)['review_state']['body']['confirmed']
    assert details(c,root,P3)['review_state']['body']['confirmed']
    ps=r.json()['chapters'][1]['paragraphs'] if chapter else r.json()['chapters'][0]['paragraphs'][3:]
    right=ps[0]['id'];assert c.get(root+'/project').json()['mappings'][right]==[mapping]
    assert c.get(root+'/project').json()['statuses'][P2]=='review'

def test_forward_merge_preserves_both_pdf_mappings_and_rejects_separators(session):
    c,create=session;root=create_book(create);meta=c.get(root+'/project').json()
    a={'page':1,'rectangle':None,'pdf_sha256':'a'*64};b={**a,'page':2}
    assert c.patch(root+'/project',json={'version':meta['version'],'mappings':{P2:[a],P3:[b]}}).status_code==200
    assert act(c,root,'/structure',action='merge_next').status_code==200
    assert c.get(root+'/project').json()['mappings'][P2]==[a,b]
    protected=SOURCE.replace('<p>後段落。</p>','<h2>区切り</h2><p>後段落。</p>')
    root=create(changed({'EPUB/chapter1.xhtml':protected.encode()}));before=exported(c,root).files
    r=act(c,root,'/structure',action='merge_next');assert r.status_code==422
    assert exported(c,root).files==before

def test_stale_sentence_boundary_cannot_commit_partial_operation(session):
    from test_editing import edit
    c,create=session;root=create_book(create);d=details(c,root,P2)
    assert edit(c,root,P2,d['editor_text']+'変更。').status_code==200
    before=exported(c,root).files
    r=c.post(root+'/structure',json={'revision':d['revision'],'expected_token':d['token'],'expected_chapter_token':d['chapter_token'],'paragraph_id':P2,'action':'insert','position':'after','sentence_index':1,'text':'追加。'})
    assert r.status_code==409 and exported(c,root).files==before

def test_chapter_split_keeps_toc_anchor_order_and_moved_inline_links(session):
    base=Book(SAMPLE.read_bytes());navpath=next(m['path'] for m in base.manifest if 'nav' in m['properties'].split())
    source=SOURCE.replace(THIRD,'<span id="tail">'+THIRD+'</span>')
    nav='<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目次</title></head><body><nav epub:type="toc"><ol><li><a href="chapter1.xhtml">部</a><ol><li><a href="chapter1.xhtml#long">長い段落</a></li><li><a href="chapter1.xhtml#tail">末尾</a></li></ol></li></ol></nav></body></html>'
    c,create=session;root=create(changed({'EPUB/chapter1.xhtml':source.encode(),navpath:nav.encode()}))
    r=act(c,root,'/chapters/split',position='after',sentence_index=1,title='一',level=2);assert r.status_code==200,r.text
    out=exported(c,root);tree=out.trees[navpath]
    assert tree.xpath('//x:nav//x:a/text()',namespaces=NS)==['部','長い段落','一','末尾']
    assert tree.xpath('//x:a[text()="末尾"]/@href',namespaces=NS)[0].split('#')[0]==out.chapters[1]['path'].split('/')[-1]
