import os
import pytest
from epub_proofreader.epub import Book, NS
from test_editing import session, details, P1, P2, P3
from test_block_actions import act, create_book, exported, round_trip, FIRST, SECOND, THIRD
from test_epub import changed


@pytest.mark.parametrize('position,left,right', [('before',FIRST,SECOND+THIRD),('after',FIRST+SECOND,THIRD)])
def test_empty_insert_splits_without_blank(session,position,left,right):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    r=act(c,root,'/structure',action='insert_boundary',sentence_index=1,position=position,text='')
    assert r.status_code==200,r.text
    paragraphs=r.json()['chapters'][0]['paragraphs']
    assert [p['text'] for p in paragraphs]==['前段落。',left,right,'後段落。']
    assert r.json()['focus_paragraph_id']==paragraphs[2]['id']
    round_trip(c,root,original)


@pytest.mark.parametrize('action,text', [('insert_boundary',''),('insert_boundary','   '),('blank','')])
@pytest.mark.parametrize('position,index', [('before',0),('after',2)])
def test_empty_at_boundary_inserts_one_blank(session,action,text,position,index):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    r=act(c,root,'/structure',action=action,text=text,sentence_index=index,position=position)
    assert r.status_code==200,r.text
    assert [p['text'] for p in r.json()['chapters'][0]['paragraphs']].count('')==1
    assert r.json()['chapters'][0]['paragraph_count']==4
    round_trip(c,root,original)


@pytest.mark.parametrize('action,text', [('insert_boundary','追加。'),('blank','')])
def test_explicit_blank_or_text_in_middle(session,action,text):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    r=act(c,root,'/structure',action=action,text=text,sentence_index=1,position='before')
    assert r.status_code==200,r.text
    assert [p['text'] for p in r.json()['chapters'][0]['paragraphs']]==['前段落。',FIRST,text,SECOND+THIRD,'後段落。']
    round_trip(c,root,original)


@pytest.mark.parametrize('index,remaining',[(0,SECOND+THIRD),(1,FIRST+THIRD),(2,FIRST+SECOND),(None,None)])
def test_delete_sentence_and_whole_paragraph_with_ruby(session,index,remaining):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    options={} if index is None else {'sentence_index':index}
    r=act(c,root,'/structure',action='delete',**options)
    assert r.status_code==200,r.text
    assert [p['text'] for p in r.json()['chapters'][0]['paragraphs']]==(['前段落。','後段落。'] if remaining is None else ['前段落。',remaining,'後段落。'])
    out=exported(c,root)
    assert len(out.trees['EPUB/chapter1.xhtml'].xpath('//x:rt',namespaces=NS))==(0 if index in (1,None) else 1)
    round_trip(c,root,original)


def test_delete_last_paragraph_keeps_editable_placeholder(session):
    c,create=session;root=create(changed({'EPUB/chapter1.xhtml':b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>One</title></head><body><h1>One</h1><p id="last">Only</p></body></html>'}))
    original=c.get(root+'/original').content
    r=act(c,root,'/structure',paragraph_id=P1,action='delete')
    assert r.status_code==200,r.text
    assert [p['text'] for p in r.json()['chapters'][0]['paragraphs']]==['']
    assert r.json()['focus_paragraph_id']==r.json()['chapters'][0]['paragraphs'][0]['id']
    round_trip(c,root,original)


def test_chapter_merge_keeps_body_and_paragraph_ids_and_roundtrips(session):
    c,create=session;root=create();original=c.get(root+'/original').content
    before=c.get(root).json();second=before['chapters'][1]
    heading=second['headings'][0]
    r=act(c,root,'/structure',paragraph_id=heading['id'],action='chapter_merge')
    assert r.status_code==200,r.text
    chapters=r.json()['chapters'];assert len(chapters)==len(before['chapters'])-1
    assert [p['id'] for p in chapters[0]['paragraphs']]==[p['id'] for ch in before['chapters'][:2] for p in ch['paragraphs']]
    assert [p['text'] for p in chapters[0]['paragraphs']]==[p['text'] for ch in before['chapters'][:2] for p in ch['paragraphs']]
    assert heading['text'] not in [h['text'] for h in chapters[0]['headings']]
    out=exported(c,root);assert second['path'] not in out.files
    assert second['title'] not in str(out.toc)
    round_trip(c,root,original)


def test_first_chapter_cannot_be_deleted(session):
    c,create=session;root=create();before=c.get(root).json()
    heading=before['chapters'][0]['headings'][0]
    r=act(c,root,'/structure',paragraph_id=heading['id'],action='chapter_merge')
    assert r.status_code==422
    assert c.get(root).json()==before


def test_merge_created_chapter_and_replay_full_history(session):
    c,create=session;root=create_book(create);original=c.get(root+'/original').content
    r=act(c,root,'/chapters/split',title='分割',level=2,position='before',sentence_index=1)
    assert r.status_code==200,r.text
    heading=r.json()['chapters'][1]['headings'][0]
    r=act(c,root,'/structure',paragraph_id=heading['id'],action='chapter_merge')
    assert r.status_code==200,r.text
    assert [p['text'] for p in r.json()['chapters'][0]['paragraphs']]==['前段落。',FIRST,SECOND+THIRD,'後段落。']
    out=exported(c,root)
    archive=c.get(root+'/project/export')
    r=c.post('/api/projects/import',files={'file':('merge.eproof',archive.content)})
    assert r.status_code==200,r.text
    assert exported(c,'/api/books/'+r.json()['id']).files==out.files
    for revision in (2,3):assert c.post(root+'/undo',json={'revision':revision}).status_code==200
    assert exported(c,root).files==Book(original).files
    for revision in (4,5):assert c.post(root+'/redo',json={'revision':revision}).status_code==200
    assert exported(c,root).files==out.files


def test_merge_rewrites_duplicate_ids_and_preserves_nested_navigation(session):
    from lxml import etree
    c,create=session
    first='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>A</title></head><body><h1 id="title">A</h1><p id="p">First <a href="chapter2.xhtml#p">Go</a></p></body></html>'
    second='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>B</title></head><body><h1 id="title">B</h1><p id="p"><a href="#title">Up</a></p><h2 id="sub">Sub</h2><p>Last</p></body></html>'
    nav='<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>TOC</title></head><body><nav epub:type="toc"><ol><li><a href="chapter1.xhtml#title">A</a></li><li><a href="chapter2.xhtml#title">B</a><ol><li><a href="chapter2.xhtml#sub">Sub</a></li></ol></li></ol></nav></body></html>'
    base=Book(__import__('test_editing').SAMPLE.read_bytes());navpath=next(m['path'] for m in base.manifest if 'nav' in m['properties'].split())
    opf=etree.fromstring(base.get(base.opf_path))
    etree.SubElement(opf.find('opf:manifest',NS),'{'+NS['opf']+'}item',id='ncx',href='toc.ncx',attrib={'media-type':'application/x-dtbncx+xml'})
    opf.find('opf:spine',NS).set('toc','ncx')
    ncx=b'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:depth" content="2"/></head><navMap><navPoint id="one" playOrder="1"><navLabel><text>A</text></navLabel><content src="chapter1.xhtml#title"/></navPoint><navPoint id="two" playOrder="2"><navLabel><text>B</text></navLabel><content src="chapter2.xhtml#title"/><navPoint id="sub" playOrder="3"><navLabel><text>Sub</text></navLabel><content src="chapter2.xhtml#sub"/></navPoint></navPoint></navMap></ncx>'
    root=create(changed({'EPUB/chapter1.xhtml':first.encode(),'EPUB/chapter2.xhtml':second.encode(),navpath:nav.encode(),base.opf_path:etree.tostring(opf),'EPUB/toc.ncx':ncx}))
    original=c.get(root+'/original').content;heading=c.get(root).json()['chapters'][1]['headings'][0]
    r=act(c,root,'/structure',paragraph_id=heading['id'],action='chapter_merge');assert r.status_code==200,r.text
    out=exported(c,root);tree=out.trees['EPUB/chapter1.xhtml']
    ids=tree.xpath('//@id');assert len(ids)==len(set(ids))
    assert [e['label'] for e in out.toc]==['A','Sub']
    assert all(e['path']=='EPUB/chapter1.xhtml' for e in out.toc)
    for value in tree.xpath('//x:a/@href',namespaces=NS):
        assert value.split('#')[1] in ids
    ncxtree=etree.fromstring(out.get('EPUB/toc.ncx'))
    assert ncxtree.xpath('//*[local-name()="navLabel"]/*/text()')==['A','Sub']
    assert ncxtree.xpath('//@playOrder')==['1','2']
    round_trip(c,root,original)


@pytest.mark.skipif(not os.getenv('EPUBCHECK_JAR'),reason='EPUBCheck unavailable')
@pytest.mark.parametrize('action',['chapter_merge','delete','blank','insert_boundary'])
def test_new_operations_pass_epubcheck(session,action):
    c,create=session;root=create()
    pid=c.get(root).json()['chapters'][1]['headings'][0]['id'] if action=='chapter_merge' else P2
    r=act(c,root,'/structure',paragraph_id=pid,action=action)
    assert r.status_code==200,r.text
    r=c.post(root+'/validate',json={'revision':1})
    assert r.status_code==200,r.text
    assert r.json()['epubcheck']['status']=='passed',r.json()
