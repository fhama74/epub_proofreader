import pytest
from test_editing import session,P1,details
from test_epub import changed,SAMPLES
from zipfile import ZipFile
from epub_proofreader.epub import Book

def data():
 with ZipFile(SAMPLES/'book.epub') as z:s=z.read('EPUB/chapter1.xhtml').decode()
 start=s.index('<p id="original-p1">');end=s.index('</p>',start)+4
 s=s[:start]+'<p id="original-p1">前<ruby>漢字<rp>（</rp><rt>かんじ</rt><rp>）</rp></ruby>後。</p>'+s[end:]
 return changed({'EPUB/chapter1.xhtml':s.encode()})

def patch(c,root,start,end,base,reading,revision=0):
 return c.patch(root+'/paragraphs/'+P1+'/rubies/0',json={'revision':revision,'base':base,'reading':reading,'range_start':start,'range_end':end})

@pytest.mark.parametrize('start,end,base,left,right',[(0,4,'前漢字後','','。'),(2,3,'字','前漢','後。'),(1,2,'漢','前','字後。'),(0,3,'前漢字','','後。')])
def test_ruby_boundary_preserves_body_and_undo_backup(session,start,end,base,left,right):
 c,create=session;root=create(data());original=details(c,root,P1)['editor_text'];assert original=='前漢字後。'
 r=patch(c,root,start,end,base,'よみ');assert r.status_code==200,r.text
 d=details(c,root,P1);assert d['editor_text']==original and d['rubies'][0]['base']==base
 assert d['rubies'][0]['start']==start and d['rubies'][0]['end']==end
 out=c.get(root+'/export');assert out.status_code==200,out.text
 parsed=Book(out.content);node=parsed.trees[parsed.chapters[0]['path']].find('.//{http://www.w3.org/1999/xhtml}ruby')
 assert (node.getparent().text or '')==left and node.tail==right
 assert len(node.findall('{http://www.w3.org/1999/xhtml}rp'))==2
 archive=c.get(root+'/project/export').content
 restored=c.post('/api/projects/import',files={'file':('range.eproof',archive)});assert restored.status_code==200,restored.text
 assert details(c,'/api/books/'+restored.json()['id'],P1)['rubies'][0]['base']==base
 assert c.post(root+'/undo',json={'revision':1}).status_code==200
 assert details(c,root,P1)['editor_text']==original and details(c,root,P1)['rubies'][0]['base']=='漢字'
 assert c.post(root+'/redo',json={'revision':2}).status_code==200
 assert details(c,root,P1)['rubies'][0]['base']==base

@pytest.mark.parametrize('start,end',[(0,1),(3,4),(0,100),(2,2)])
def test_boundary_rejects_non_overlapping_or_outside_range(session,start,end):
 c,create=session;root=create(data());r=patch(c,root,start,end,'漢','かん');assert r.status_code==422
 assert details(c,root,P1)['editor_text']=='前漢字後。'

def test_range_and_spelling_change_together_and_revision_conflict(session):
 c,create=session;root=create(data());r=patch(c,root,0,4,'前感じ後','よみ');assert r.status_code==200,r.text
 assert details(c,root,P1)['editor_text']=='前感じ後。'
 assert patch(c,root,0,1,'前','まえ').status_code==409
