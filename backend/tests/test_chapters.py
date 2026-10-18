import copy,json,os
import pytest
from lxml import etree
from epub_proofreader.epub import Book,NS
from test_editing import session,details,edit,SAMPLE,P1,P2,P3
from test_epub import changed

def split(c,root,pid=P2,title='新しい章',**extra):
    d=details(c,root,pid)
    return c.post(root+'/chapters/split',json={'paragraph_id':pid,'revision':d['revision'],'expected_token':d['token'],'expected_chapter_token':d['chapter_token'],'title':title,**extra})

def test_chapter_split_ids_links_edit_undo_redo_and_export(session):
    c,create=session;root=create();before=c.get(root).json();allids=[p['id'] for ch in before['chapters'] for p in ch['paragraphs']]
    r=split(c,root);assert r.status_code==200,r.text
    b=r.json();assert len(b['chapters'])==3
    assert b['chapters'][1]['title']=='新しい章'
    assert [[p['id'] for p in ch['paragraphs']] for ch in b['chapters']][:2]==[[P1],[P2,P3]]
    assert [p['id'] for ch in b['chapters'] for p in ch['paragraphs']]==allids
    assert b['focus_paragraph_id']==P2
    data=c.get(root+'/export');assert data.status_code==200,data.text
    out=Book(data.content);assert any(t['label']=='新しい章' and t['path']==out.chapters[1]['path'] for t in out.toc)
    assert c.get(root+'/original').content==SAMPLE.read_bytes()
    text=details(c,root,P2)['editor_text'];assert edit(c,root,P2,text+'追加。',1).status_code==200
    assert c.get(root+'/export').status_code==200
    for rev in [2,3]:assert c.post(root+'/undo',json={'revision':rev}).status_code==200
    assert Book(c.get(root+'/export').content).files==Book(SAMPLE.read_bytes()).files
    assert c.post(root+'/redo',json={'revision':4}).status_code==200
    assert len(c.get(root).json()['chapters'])==3
    assert c.get(root+'/export').status_code==200

def test_chapter_backup_replay_and_tamper_rejection(session):
    c,create=session;root=create();assert split(c,root).status_code==200
    archive=c.get(root+'/project/export');assert archive.status_code==200,archive.text
    imported=c.post('/api/projects/import',files={'file':('chapters.eproof',archive.content)});assert imported.status_code==200,imported.text
    newroot='/api/books/'+imported.json()['id'];assert len(imported.json()['chapters'])==3
    assert details(c,newroot,P2)['editor_text']==details(c,root,P2)['editor_text']
    assert c.post(newroot+'/undo',json={'revision':1}).status_code==200
    assert len(c.get(newroot).json()['chapters'])==2
    from epub_proofreader import app as module,projects,editing
    with module.database() as con:value=editing.state(con,root.split('/')[-1])
    state=copy.deepcopy({k:value[k] for k in ['commands','cursor','history','revision','ids']})
    state['commands'][0]['chapter_options']['title']='偽の章名'
    with pytest.raises(ValueError,match='履歴'):projects.replay(Book(SAMPLE.read_bytes()),state)

def test_chapter_preserves_review_and_pdf_mapping(session):
    c,create=session;root=create();d=details(c,root,P2)
    assert c.post(root+'/paragraphs/'+P2+'/review',json={'target':'body','expected_token':d['token']}).status_code==200
    meta=c.get(root+'/project').json()
    mapping={'page':2,'rectangle':None,'pdf_sha256':'a'*64}
    assert c.patch(root+'/project',json={'version':meta['version'],'mappings':{P2:[mapping]}}).status_code==200
    assert split(c,root).status_code==200
    assert details(c,root,P2)['review_state']['body']['confirmed']
    assert c.get(root+'/project').json()['mappings'][P2]==[mapping]
    assert c.post(root+'/undo',json={'revision':1}).status_code==200
    assert details(c,root,P2)['review_state']['body']['confirmed']
    assert c.post(root+'/redo',json={'revision':2}).status_code==200
    assert details(c,root,P2)['review_state']['body']['confirmed']

def test_ncx_and_navless_book_navigation_are_updated(session):
    from epub_proofreader.editing import repack
    c,create=session;base=Book(SAMPLE.read_bytes());opf=etree.fromstring(base.get(base.opf_path))
    manifest=opf.find('opf:manifest',NS);spine=opf.find('opf:spine',NS);spine.set('toc','ncx')
    etree.SubElement(manifest,'{'+NS['opf']+'}item',id='ncx',href='toc.ncx',attrib={'media-type':'application/x-dtbncx+xml'})
    for item in manifest:
        if 'nav' in item.get('properties','').split():item.attrib.pop('properties')
    ncx=b'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap><navPoint id="one" playOrder="1"><navLabel><text>Old</text></navLabel><content src="chapter1.xhtml"/></navPoint><navPoint id="two" playOrder="2"><navLabel><text>Next</text></navLabel><content src="chapter2.xhtml"/></navPoint></navMap></ncx>'
    root=create(repack(SAMPLE.read_bytes(),{base.opf_path:etree.tostring(opf),'EPUB/toc.ncx':ncx}))
    r=split(c,root);assert r.status_code==200,r.text
    out=Book(c.get(root+'/export').content);assert any(t['label']=='新しい章' for t in out.toc)
    tree=etree.fromstring(out.get('EPUB/toc.ncx'))
    assert tree.xpath('//*[local-name()="navLabel"]/*/text()')==['Old','新しい章','Next']
    assert tree.xpath('//@playOrder')==['1','2','3']
    archive=c.get(root+'/project/export');r=c.post('/api/projects/import',files={'file':('ncx.eproof',archive.content)})
    assert r.status_code==200,r.text

def test_nested_chapter_split_and_cross_file_anchor_links(session):
    source='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>旧章</title><link rel="stylesheet" href="style.css"/></head><body>\n<section id="section"><h1>旧章</h1><p id="before"><a href="#after">後へ</a></p>\n<div id="container"><p id="after"><ruby>親<rt>おや</rt></ruby><a href="#before">前へ</a></p><p>末尾。</p></div>\n</section>\n</body></html>'
    c,create=session;root=create(changed({'EPUB/chapter1.xhtml':source.encode()}));r=split(c,root)
    assert r.status_code==200,r.text
    out=Book(c.get(root+'/export').content);new=out.chapters[1]['path'];old=out.trees['EPUB/chapter1.xhtml'];right=out.trees[new]
    assert old.xpath('//x:a/@href',namespaces=NS)==[new.split('/')[-1]+'#after']
    assert right.xpath('//x:a/@href',namespaces=NS)==['chapter1.xhtml#before']
    assert right.xpath('//x:rt/text()',namespaces=NS)==['おや']
    assert right.xpath('//x:link/@href',namespaces=NS)==['style.css']
    assert c.get(root+'/project/export').status_code==200

def test_chapter_rejects_conflict_and_invalid_title_without_changes(session):
    c,create=session;root=create();d=details(c,root,P2)
    assert edit(c,root,P3,'他の編集。').status_code==200
    req={'paragraph_id':P2,'revision':0,'expected_token':d['token'],'expected_chapter_token':d['chapter_token'],'title':'新章'}
    assert c.post(root+'/chapters/split',json=req).status_code==409
    assert split(c,root,title='   ').status_code==422
    assert len(c.get(root).json()['chapters'])==2

def test_repeated_chapter_splits_and_undo_preserve_all_following_ids(session):
    c,create=session;root=create();before=c.get(root).json();ids=[p['id'] for ch in before['chapters'] for p in ch['paragraphs']]
    assert split(c,root,P2,'中章').status_code==200
    assert split(c,root,P3,'後章').status_code==200
    b=c.get(root).json();assert len(b['chapters'])==4
    assert [p['id'] for ch in b['chapters'] for p in ch['paragraphs']]==ids
    r=c.post('/api/projects/import',files={'file':('twice.eproof',c.get(root+'/project/export').content)})
    assert r.status_code==200,r.text
    for rev in [2,3]:assert c.post(root+'/undo',json={'revision':rev}).status_code==200
    assert Book(c.get(root+'/export').content).files==Book(SAMPLE.read_bytes()).files

def test_text_edits_after_chapter_split_keep_the_xhtml_only_fast_path(session,monkeypatch):
    c,create=session;root=create();assert split(c,root).status_code==200
    from epub_proofreader import editing
    def forbidden(*args,**kwargs):raise AssertionError('EPUB ZIP rebuilt during a text edit')
    monkeypatch.setattr(editing,'repack',forbidden)
    r=edit(c,root,P2,'新しい章の本文。',1);assert r.status_code==200,r.text
    assert details(c,root,P2)['editor_text']=='新しい章の本文。'

def test_insert_after_heading_or_list_and_round_trip(session):
    c,create=session
    source='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>試験</title></head><body><h1>題</h1><ul><li>項目</li></ul><p>本文。</p></body></html>'
    root=create(changed({'EPUB/chapter1.xhtml':source.encode()}));b=c.get(root).json();heading=b['chapters'][0]['headings'][0]['id']
    for rev,pid in [(0,heading),(1,P1)]:
        r=c.post(root+'/structure',json={'revision':rev,'action':'insert','paragraph_id':pid,'text':'追加。'})
        assert r.status_code==200,r.text
    out=Book(c.get(root+'/export').content);tree=out.trees['EPUB/chapter1.xhtml']
    assert tree.xpath('//x:body/x:p/text()',namespaces=NS)==['追加。','追加。','本文。']
    assert tree.xpath('//x:ul/x:li/text()',namespaces=NS)==['項目']
    r=c.post('/api/projects/import',files={'file':('insert.eproof',c.get(root+'/project/export').content)})
    assert r.status_code==200,r.text

@pytest.mark.skipif(not os.getenv('EPUBCHECK_JAR'),reason='EPUBCheck unavailable')
def test_real_epubcheck_after_chapter_split(session):
    c,create=session;root=create();assert split(c,root).status_code==200
    response=c.post(root+'/validate',json={'revision':1})
    assert response.status_code==200,response.text
    assert response.json()['epubcheck']['status']=='passed',response.json()['epubcheck']

def toc_tree(c,root):
    book=Book(c.get(root+'/export').content)
    nav=next(m for m in book.manifest if 'nav' in m['properties'].split())
    return book,book.trees[nav['path']].xpath('//x:nav[@*[local-name()="type"]="toc"]/x:ol',namespaces=NS)[0]

def test_child_sibling_and_new_part_toc_order_roundtrip(session):
    c,create=session;root=create()
    assert split(c,root,P2,'一',level=2).status_code==200
    assert split(c,root,P3,'二',level=2).status_code==200
    out,toc=toc_tree(c,root)
    assert toc.xpath('./x:li/x:a/text()',namespaces=NS)==['第一章　午後の庭','第二章　旅の朝']
    assert toc.xpath('./x:li[1]/x:ol/x:li/x:a/text()',namespaces=NS)==['一','二']
    assert out.chapters[1]['heading_level']==2
    assert out.chapters[2]['heading_level']==2
    assert out.trees[out.chapters[1]['path']].xpath('//x:body/x:h2/text()',namespaces=NS)==['一']
    archive=c.get(root+'/project/export')
    restored=c.post('/api/projects/import',files={'file':('levels.eproof',archive.content)})
    assert restored.status_code==200,restored.text
    restored_root='/api/books/'+restored.json()['id']
    assert toc_tree(c,restored_root)[0].files==out.files
    for rev in (2,3):assert c.post(root+'/undo',json={'revision':rev}).status_code==200
    assert Book(c.get(root+'/export').content).files==Book(SAMPLE.read_bytes()).files
    for rev in (4,5):assert c.post(root+'/redo',json={'revision':rev}).status_code==200
    assert toc_tree(c,root)[0].files==out.files
    assert split(c,root,P3,'新しい部',level=1).status_code==200
    _,toc=toc_tree(c,root)
    assert toc.xpath('./x:li/x:a/text()',namespaces=NS)==['第一章　午後の庭','新しい部','第二章　旅の朝']

def test_all_six_heading_levels_and_nested_ncx(session):
    from epub_proofreader.editing import repack
    c,create=session;base=Book(SAMPLE.read_bytes());opf=etree.fromstring(base.get(base.opf_path))
    etree.SubElement(opf.find('opf:manifest',NS),'{'+NS['opf']+'}item',id='ncx',href='toc.ncx',attrib={'media-type':'application/x-dtbncx+xml'})
    opf.find('opf:spine',NS).set('toc','ncx')
    ncx=b'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:depth" content="1"/></head><navMap><navPoint id="one" playOrder="1"><navLabel><text>Part</text></navLabel><content src="chapter1.xhtml"/></navPoint><navPoint id="two" playOrder="2"><navLabel><text>Next</text></navLabel><content src="chapter2.xhtml"/></navPoint></navMap></ncx>'
    source='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>部</title></head><body><h1>部</h1>'+''.join(f'<p>本文{i}。</p>' for i in range(7))+'</body></html>'
    root=create(repack(SAMPLE.read_bytes(),{base.opf_path:etree.tostring(opf),'EPUB/chapter1.xhtml':source.encode(),'EPUB/toc.ncx':ncx}))
    pids=[p['id'] for p in c.get(root).json()['chapters'][0]['paragraphs']]
    for level,pid in zip(range(2,7),pids[1:]):
        response=split(c,root,pid,f'階層{level}',level=level)
        assert response.status_code==200,response.text
    out,toc=toc_tree(c,root)
    branch=toc
    for level in range(1,7):
        item=branch.find('x:li',NS);assert item is not None
        assert item.find('x:a',NS).text==('第一章　午後の庭' if level==1 else f'階層{level}')
        chapter=out.chapters[level-1];assert chapter['heading_level']==level
        assert chapter['title']==('部' if level==1 else f'階層{level}')
        branch=item.find('x:ol',NS)
    ncxtree=etree.fromstring(out.get('EPUB/toc.ncx'))
    assert ncxtree.xpath('//*[local-name()="meta"][@name="dtb:depth"]/@content')==['6']
    assert ncxtree.xpath('//@playOrder')==[str(n) for n in range(1,8)]
    assert max(len(p.xpath('ancestor::*[local-name()="navPoint"]'))+1 for p in ncxtree.xpath('//*[local-name()="navPoint"]'))==6
    if os.getenv('EPUBCHECK_JAR'):
        # Use the original valid sample's navigation for EPUBCheck, since the
        # deliberately minimal NCX fixture does not contain all required metadata.
        simple=create();assert split(c,simple,P2,'深い節',level=6).status_code==200
        report=c.post(simple+'/validate',json={'revision':1}).json()
        assert report['epubcheck']['status']=='passed',report['epubcheck']

@pytest.mark.parametrize('level',[0,7,-1,2.5,'2',True])
def test_chapter_invalid_level_does_not_change_book(session,level):
    c,create=session;root=create();before=c.get(root).json()
    assert split(c,root,level=level).status_code==422
    assert c.get(root).json()==before

def test_pre_level_backup_replay_is_unchanged(session):
    from epub_proofreader import app as module,editing,projects
    c,create=session;root=create()
    # A command made before the level selector has no level in its options.
    with module.database() as con:
        editing.commit_edit(con,root.split('/')[-1],0,'chapter_split',paragraph_id=P2,text='旧形式の章')
        value=editing.state(con,root.split('/')[-1])
    assert 'level' not in value['commands'][0]['chapter_options']
    replayed=projects.replay(Book(SAMPLE.read_bytes()),{k:value[k] for k in ['commands','cursor','history','revision','ids']})
    assert editing.working_model(replayed).files==editing.working_model(value).files

def test_imported_h2_at_toc_root_stays_sibling_and_existing_children_survive(session):
    c,create=session
    source='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>一</title></head><body><h2>一</h2><p>前。</p><p>後。</p><h3 id="sub">小節</h3><p>末尾。</p></body></html>'
    nav='<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目次</title></head><body><nav epub:type="toc"><ol><li><a href="chapter1.xhtml">一</a><ol><li><a href="chapter1.xhtml#sub">小節</a></li></ol></li><li><a href="chapter2.xhtml">次章</a></li></ol></nav></body></html>'
    base=Book(SAMPLE.read_bytes());navpath=next(m['path'] for m in base.manifest if 'nav' in m['properties'].split())
    root=create(changed({'EPUB/chapter1.xhtml':source.encode(),navpath:nav.encode()}))
    assert split(c,root,P2,'二',level=2).status_code==200
    out,toc=toc_tree(c,root)
    assert toc.xpath('./x:li/x:a/text()',namespaces=NS)==['一','二','次章']
    assert toc.xpath('./x:li[2]/x:ol/x:li/x:a/text()',namespaces=NS)==['小節']
    assert out.trees[out.chapters[1]['path']].xpath('//x:h3/text()',namespaces=NS)==['小節']
