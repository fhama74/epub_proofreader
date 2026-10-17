import os
import zipfile
import pytest
from lxml import etree
from epub_proofreader.epub import Book,NS
from epub_proofreader.segments import describe,sentences
from test_editing import session,details,edit,SAMPLE,P1,P2,P3
from test_epub import changed

def paragraph(text):return etree.fromstring(('<p xmlns="http://www.w3.org/1999/xhtml">'+text+'</p>').encode())
def operation(client,root,action,pid,revision=0,**kwargs):
    response=client.post(root+'/structure',json={'revision':revision,'action':action,'paragraph_id':pid,**kwargs})
    assert response.status_code==200,response.text
    return response.json()
def chapter(client,root):return client.get(root).json()['chapters'][0]
def undo(client,root,revision):
    r=client.post(root+'/undo',json={'revision':revision});assert r.status_code==200,r.text

def test_threshold_and_lossless_sentences():
    assert describe(paragraph('字'*299))[0]['unit_mode']=='paragraph'
    assert describe(paragraph('字'*300))[0]['unit_mode']=='sentence'
    assert describe(paragraph(' \n'+ '字'*298+'<ruby>字<rt>'+ 'よみ'*400+'</rt></ruby>'))[0]['character_count']==299
    value='「本当？」と言った。次は終わり！』\n最後'
    assert [s['text'] for s in sentences(value)]==['「本当？」と言った。','次は終わり！』\n','最後']
    d=describe(paragraph('<ruby>まる。続き<rt>よみ</rt></ruby>です。次。'))[0]
    assert [s['text'] for s in d['sentences']]==['まる。続きです。','次。']

def test_insert_counts_stable_ids_restart_and_export(session):
    client,create=session;root=create();before=chapter(client,root)
    result=operation(client,root,'insert',P2,text='欠落本文。',position='before')
    focus=result['focus_paragraph_id'];after=result['chapters'][0]
    assert after['paragraph_count']==4 and after['sentence_count']==before['sentence_count']+1
    assert [p['id'] for p in after['paragraphs']]==[P1,focus,P2,P3]
    assert edit(client,root,focus,'補完本文。',1).status_code==200
    from epub_proofreader import app as module
    module.load_book.cache_clear()
    assert details(client,root,focus)['editor_text']=='補完本文。'
    assert client.get(root+'/export').status_code==200
    assert client.get(root+'/original').content==SAMPLE.read_bytes()
    undo(client,root,2);undo(client,root,3)
    assert chapter(client,root)['paragraph_count']==3
    assert client.post(root+'/redo',json={'revision':4}).status_code==200
    assert chapter(client,root)['paragraphs'][1]['id']==focus
    assert client.get(root+'/export').status_code==200

def test_blank_insert_and_merge_undo_exact_original(session):
    client,create=session;root=create()
    inserted=operation(client,root,'insert',P2,text='')['focus_paragraph_id']
    assert details(client,root,inserted)['editor_text']==''
    operation(client,root,'merge',inserted,1)
    assert chapter(client,root)['paragraph_count']==3
    undo(client,root,2);undo(client,root,3)
    assert Book(client.get(root+'/export').content).files==Book(SAMPLE.read_bytes()).files

def test_split_preserves_ruby_inline_ids_and_undo_redo(session):
    client,create=session
    value='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>試験</title></head><body><p id="p"><em id="em">前文。<ruby>漢字<rt>かんじ</rt></ruby>後文。</em>末尾。</p><p>次。</p></body></html>'
    data=changed({'EPUB/chapter1.xhtml':value.encode()});root=create(data)
    r=client.post(root+'/structure',json={'revision':0,'action':'split','paragraph_id':P1,'offset':4})
    assert r.status_code==422 and client.get(root).json()['edit_state']['revision']==0
    result=operation(client,root,'split',P1,offset=3)
    focus=result['focus_paragraph_id'];ps=result['chapters'][0]['paragraphs']
    assert [p['text'] for p in ps]==['前文。','漢字後文。末尾。','次。']
    exported=client.get(root+'/export');assert exported.status_code==200,exported.text
    tree=Book(exported.content).trees['EPUB/chapter1.xhtml']
    assert tree.xpath('//@id')==['p','em'] and len(tree.xpath('//x:ruby',namespaces=NS))==1
    assert edit(client,root,focus,'漢字後文。追加。末尾。',1).status_code==200
    undo(client,root,2);undo(client,root,3)
    assert Book(client.get(root+'/export').content).files==Book(data).files
    assert client.post(root+'/redo',json={'revision':4}).status_code==200
    assert details(client,root,focus)['editor_text']=='漢字後文。末尾。'
    assert client.get(root+'/export').status_code==200

def test_merge_retains_anchors_rubies_and_rejects_separators(session):
    client,create=session
    with zipfile.ZipFile(SAMPLE) as archive:source=archive.read('EPUB/chapter1.xhtml')
    source=source.replace(b'<p>',b'<p id="original-p2">',1)
    root=create(changed({'EPUB/chapter1.xhtml':source}));before=chapter(client,root)
    result=operation(client,root,'merge',P2)
    assert result['chapters'][0]['paragraphs'][0]['text']==before['paragraphs'][0]['text']+before['paragraphs'][1]['text']
    exported=client.get(root+'/export');assert exported.status_code==200,exported.text
    tree=Book(exported.content).trees['EPUB/chapter1.xhtml']
    assert tree.xpath('//*[@id="original-p2"]')
    assert [r['original_xml'] for r in result['chapters'][0]['paragraphs'][0]['rubies']]==[r['original_xml'] for r in before['paragraphs'][0]['rubies']]
    undo(client,root,1)
    assert client.post(root+'/structure',json={'revision':2,'action':'merge','paragraph_id':P1}).status_code==422
    source=source.replace(b'<p id="original-p2"', '<h2>区切り</h2><p id="original-p2"'.encode())
    separated=create(changed({'EPUB/chapter1.xhtml':source}))
    assert client.post(separated+'/structure',json={'revision':0,'action':'merge','paragraph_id':P2}).status_code==422

def test_sentence_edit_only_selected_repeated_occurrence_and_recounts(session):
    client,create=session
    source='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>試験</title></head><body><p>'+('同文。'*110)+'</p></body></html>'
    root=create(changed({'EPUB/chapter1.xhtml':source.encode()}))
    assert len(chapter(client,root)['proof_units'])==110
    r=client.patch(root+'/paragraphs/'+P1,json={'revision':0,'sentence_index':1,'expected_sentence':'同文。','text':'修正文。追加文。'})
    assert r.status_code==200,r.text
    assert details(client,root,P1)['editor_text'].startswith('同文。修正文。追加文。同文。')
    assert chapter(client,root)['sentence_count']==111
    assert client.patch(root+'/paragraphs/'+P1,json={'revision':1,'sentence_index':1,'expected_sentence':'同文。','text':'変更'}).status_code==409
    undo(client,root,1);assert details(client,root,P1)['editor_text']=='同文。'*110

@pytest.mark.skipif(not os.getenv('EPUBCHECK_JAR'),reason='requires EPUBCheck')
def test_epubcheck_structural_operations(session):
    client,create=session;root=create()
    result=operation(client,root,'split',P1,offset=8)
    operation(client,root,'merge',result['focus_paragraph_id'],1)
    operation(client,root,'insert',P2,2,text='補完した段落。')
    response=client.post(root+'/validate',json={'revision':3})
    assert response.status_code==200,response.text
    assert response.json()['epubcheck']['status']=='passed',response.json()

def test_legacy_editing_database_migration_preserves_history(session):
    import sqlite3
    from epub_proofreader import app as module
    client,create=session;root=create();d=details(client,root)
    assert edit(client,root,P2,d['editor_text']+'追加。').status_code==200
    with sqlite3.connect(module.DATA_DIR/'library.sqlite3') as con:
        con.execute('ALTER TABLE editing RENAME TO editing_new')
        con.execute('CREATE TABLE editing (book_id TEXT PRIMARY KEY,working BLOB NOT NULL,revision INTEGER NOT NULL,commands TEXT NOT NULL,cursor INTEGER NOT NULL,history TEXT NOT NULL)')
        con.execute('INSERT INTO editing SELECT book_id,working,revision,commands,cursor,history FROM editing_new')
        con.execute('DROP TABLE editing_new')
    module.load_book.cache_clear()
    assert details(client,root)['editor_text'].endswith('追加。')
    operation(client,root,'insert',P2,1,text='補完。')
    undo(client,root,2);undo(client,root,3)
    assert details(client,root)['editor_text']==d['editor_text']
    assert len(client.get(root+'/history').json()['events'])==4
