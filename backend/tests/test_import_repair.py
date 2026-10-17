import io,zipfile
import pytest
from epub_proofreader.epub import Book,EpubError,xml
from epub_proofreader.import_repair import repair_numeric_references
from test_epub import changed,SAMPLES
from test_editing import session,P2,details,edit

BROKEN='&#<span class="tcy">x</span><span class="tcy">27</span>;'
def source():
    with zipfile.ZipFile(SAMPLES/'book.epub') as z:chapter=z.read('EPUB/chapter1.xhtml').decode()
    return changed({'EPUB/chapter1.xhtml':chapter.replace('今日は良い天汽だった。',f'今日は良い天汽だった。Arthur{BROKEN}s本。').encode()})

def test_strict_first_repair_is_opt_in_and_immutable():
    data=source()
    with pytest.raises(EpubError,match='CharRef'):Book(data)
    b=Book(data,repair_import=True);assert b.original==data and len(b.import_repairs)==1
    assert b.import_repairs[0]['after']=='&#x27;' and b.import_repairs[0]['path']=='EPUB/chapter1.xhtml'
    checked=Book(b.normalized);assert "Arthur's本。" in checked.chapters[0]['paragraphs'][1]['text']
    with zipfile.ZipFile(io.BytesIO(data)) as raw:
        assert BROKEN.encode() in raw.read('EPUB/chapter1.xhtml')
        assert {p for p in b.files if b.files[p]!=raw.read(p)}=={'EPUB/chapter1.xhtml'}
    normal=(SAMPLES/'book.epub').read_bytes();good=Book(normal,repair_import=True)
    assert not good.import_repairs and good.normalized==normal

@pytest.mark.parametrize('reference,expected',[
 ('&#<span class="tcy">123</span>;', '&#123;'),
 ('&#x<span class="tcy">27</span>;', '&#x27;'),
 (BROKEN,'&#x27;'),
 ('&#<span class="tcy">xD800</span>;',None),
 ('&#<span class="tcy">0</span>;',None),
 ('&#<span class="other">x27</span>;',None),
 ('&#<span class="tcy" onclick="bad()">x27</span>;',None),
 ('&#<span class="tcy">xyz</span>;',None),
])
def test_only_known_tcy_and_valid_xml_codepoints(reference,expected):
    data=('<p>'+reference+'</p>').encode();fixed,records=repair_numeric_references(data,'p.xhtml')
    assert bool(records)==(expected is not None)
    assert fixed==('<p>'+(expected or reference)+'</p>').encode()
    if expected:xml(fixed)

@pytest.mark.parametrize('markup',[
 '<p><![CDATA['+BROKEN+']]></p>', '<p><!--'+BROKEN+'--></p>',
 '<p value="'+BROKEN+'">本文</p>', '<?note '+BROKEN+'?><p>本文</p>',
])
def test_literal_or_attribute_content_is_not_changed(markup):
    data=markup.encode();assert repair_numeric_references(data,'p.xhtml')==(data,[])

def test_unrelated_xml_and_entities_are_not_silently_recovered():
    invalid=source()
    with zipfile.ZipFile(io.BytesIO(invalid)) as z:chapter=z.read('EPUB/chapter1.xhtml')
    bad=changed({'EPUB/chapter1.xhtml':chapter.replace(b'</p>',b'</bad>',1)})
    with pytest.raises(EpubError):Book(bad,repair_import=True)
    bad=changed({'EPUB/chapter1.xhtml':b'<!DOCTYPE html [<!ENTITY bad "secret">]><html xmlns="http://www.w3.org/1999/xhtml"><body><p>&bad;</p></body></html>'})
    with pytest.raises(EpubError):Book(bad,repair_import=True)

def test_repaired_project_edit_undo_strict_export_and_backup_roundtrip(session):
    c,create=session;data=source();root=create(data)
    book=c.get(root).json();assert len(book['import_repairs'])==1 and book['edit_state']['revision']==0
    assert c.get(root+'/original').content==data
    original_text=details(c,root,P2)['editor_text'];assert "Arthur's本。" in original_text
    assert edit(c,root,P2,original_text.replace('天汽','天気')).status_code==200
    assert c.post(root+'/undo',json={'revision':1}).status_code==200
    assert details(c,root,P2)['editor_text']==original_text
    # Export is strict XML, not an EPUB that still needs automatic repair.
    result=c.get(root+'/export');assert result.status_code==200,result.text
    exported=Book(result.content);assert not exported.import_repairs
    assert exported.chapters[0]['paragraphs'][1]['text']==original_text
    archive=c.get(root+'/project/export');assert archive.status_code==200
    restored=c.post('/api/projects/import',files={'file':('repaired.eproof',archive.content)})
    assert restored.status_code==200,restored.text
    again='/api/books/'+restored.json()['id']
    assert c.get(again+'/original').content==data
    assert len(c.get(again).json()['import_repairs'])==1
    assert details(c,again,P2)['editor_text']==original_text
    assert c.post(again+'/redo',json={'revision':2}).status_code==200
    assert '天気' in details(c,again,P2)['editor_text']
