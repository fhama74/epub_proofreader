import io,json,sqlite3,zipfile
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_editing import session,details,edit,P1,P2
from epub_proofreader import app as module,editing
from epub_proofreader.epub import Book,EpubError
from epub_proofreader.working import WorkingFiles,baseline,model,recent


def clear_models():
 editing.cached_model.cache_clear();model.cache_clear();baseline.cache_clear();recent.clear()


def test_edit_preview_undo_redo_never_repack_and_only_analyze_changed_chapter(session,monkeypatch):
 c,create=session;root=create();before=details(c,root);original=c.get(root+'/original').content
 seen=[];original_analyze=Book.analyze_chapter
 def analyze(self,path,number):seen.append(path);return original_analyze(self,path,number)
 monkeypatch.setattr(Book,'analyze_chapter',analyze)
 def forbidden(*a,**k):raise AssertionError('editing must not assemble a ZIP')
 with monkeypatch.context() as guard:
  guard.setattr(editing,'repack',forbidden)
  result=edit(c,root,P2,before['editor_text'].replace('天汽','天気'));assert result.status_code==200,result.text
  assert c.get(root+'/chapters/chapter0001').status_code==200
  assert details(c,root)['editor_text'].find('天気')>=0
  assert c.post(root+'/undo',json={'revision':1}).status_code==200
  assert details(c,root)['editor_text']==before['editor_text']
  assert c.post(root+'/redo',json={'revision':2}).status_code==200
 assert seen and set(seen)=={'EPUB/chapter1.xhtml'}
 assert c.get(root+'/original').content==original
 output=Book(c.get(root+'/export').content)
 assert '天気' in output.chapters[0]['paragraphs'][1]['text']


def test_overlays_persist_after_cache_loss_and_keep_legacy_base_bytes(session):
 c,create=session;root=create();ident=root.split('/')[-1];old=details(c,root)
 assert edit(c,root,P2,old['editor_text']+'追記。').status_code==200
 with module.database() as con:
  base=con.execute('SELECT working FROM editing WHERE book_id=?',(ident,)).fetchone()[0]
  overlays=con.execute('SELECT path,content FROM editing_files WHERE book_id=?',(ident,)).fetchall()
  assert len(overlays)==1 and overlays[0][0]=='EPUB/chapter1.xhtml'
  assert '追記。' not in Book(base).chapters[0]['paragraphs'][1]['text']
 clear_models();module.load_book.cache_clear()
 assert details(c,root)['editor_text'].endswith('追記。')
 assert c.post(root+'/undo',json={'revision':1}).status_code==200
 with module.database() as con:assert con.execute('SELECT COUNT(*) FROM editing_files WHERE book_id=?',(ident,)).fetchone()[0]==0


def test_cached_snapshots_are_immutable_on_invalid_edits_and_parallel_reads(session):
 c,create=session;root=create();ident=root.split('/')[-1]
 with module.database() as con:value=editing.state(con,ident)
 original=editing.working_model(value);path=original.chapters[0]['path'];raw=original.get(path)
 changes,_,_=editing.text_changes(original,P2,'変更した文。')
 changed=editing.apply_changes(original,changes)
 new=editing.working_model({**value,'working':changed})
 assert original.get(path)==raw and original.chapters[0]['paragraphs'][1]['text']!=new.chapters[0]['paragraphs'][1]['text']
 with ThreadPoolExecutor(max_workers=4) as pool:
  results=list(pool.map(lambda i:editing.working_model(value if i%2 else {**value,'working':changed}).chapters[0]['paragraphs'][1]['text'],range(20)))
 assert len(set(results))==2
 bad=[{**changes[0],'after':'\x00'}]
 with pytest.raises(EpubError):editing.apply_changes(original,bad)
 assert editing.working_model(value).get(path)==raw


def test_structure_and_ruby_edits_use_overlays_and_export_backup(session,monkeypatch):
 c,create=session;root=create();original=c.get(root+'/original').content
 with monkeypatch.context() as guard:
  guard.setattr(editing,'repack',lambda *a,**k:pytest.fail('no ZIP during edits'))
  r=c.patch(root+f'/paragraphs/{P1}/rubies/0',json={'revision':0,'base':'吾輩','reading':'ワガハイ'});assert r.status_code==200,r.text
  r=c.post(root+'/structure',json={'revision':1,'action':'insert','paragraph_id':P2,'text':'追加段落。'});assert r.status_code==200,r.text
  assert c.post(root+'/undo',json={'revision':2}).status_code==200
  assert c.post(root+'/redo',json={'revision':3}).status_code==200
 data=c.get(root+'/project/export').content
 imported=c.post('/api/projects/import',files={'file':('overlay.eproof',data)});assert imported.status_code==200,imported.text
 restored='/api/books/'+imported.json()['id']
 assert c.get(restored+'/original').content==original
 assert c.get(restored).json()['edit_state']['revision']==4
 assert details(c,restored,P1)['rubies'][0]['readings']==['ワガハイ']
 assert c.post(restored+'/undo',json={'revision':4}).status_code==200


def test_legacy_working_epub_remains_readable_and_edits_become_overlays(session):
 c,create=session;root=create();ident=root.split('/')[-1];d=details(c,root)
 assert edit(c,root,P2,d['editor_text']+'旧保存。').status_code==200
 with module.database() as con:
  value=editing.state(con,ident);legacy=editing.materialize(value['working'])
  con.execute('UPDATE editing SET working=? WHERE book_id=?',(legacy,ident))
  con.execute('DELETE FROM editing_files WHERE book_id=?',(ident,))
 clear_models()
 assert details(c,root)['editor_text'].endswith('旧保存。')
 assert edit(c,root,P2,details(c,root)['editor_text']+'新保存。',1).status_code==200
 with module.database() as con:assert con.execute('SELECT working FROM editing WHERE book_id=?',(ident,)).fetchone()[0]==legacy
 assert c.post(root+'/undo',json={'revision':2}).status_code==200
 assert details(c,root)['editor_text'].endswith('旧保存。')
 assert c.post(root+'/undo',json={'revision':3}).status_code==200
 assert details(c,root)['editor_text']==d['editor_text']
