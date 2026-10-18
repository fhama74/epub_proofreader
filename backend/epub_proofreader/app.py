from __future__ import annotations
import os
import sqlite3
import uuid
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
import copy
import json
from pydantic import BaseModel, Field
from typing import Literal
from . import editing, projects, library
from .ai import schema as ai_schema
from .validation import epubcheck
from fastapi import FastAPI, UploadFile, HTTPException,Request
from . import unit_store,proof_score,maintenance
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from .epub import Book, EpubError, MAX_UPLOAD

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR",os.getenv("EPROOF_DATA_DIR", str(ROOT / ".data"))))
app = FastAPI(title="EPUB Proofreader", version="0.5.8")

@contextmanager
def _database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if unit_store.USE_NEW_STORAGE:unit_store.prepare_database(DATA_DIR)
    con = sqlite3.connect(DATA_DIR / (unit_store.DB_NAME if unit_store.USE_NEW_STORAGE else 'library.sqlite3'),timeout=10)
    con.execute('PRAGMA busy_timeout=10000')
    if unit_store.USE_NEW_STORAGE:con.execute('PRAGMA journal_mode=WAL')
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("CREATE TABLE IF NOT EXISTS books (id TEXT PRIMARY KEY, name TEXT NOT NULL, original BLOB NOT NULL)")
    con.execute("CREATE TABLE IF NOT EXISTS editing (book_id TEXT PRIMARY KEY REFERENCES books(id),working BLOB NOT NULL,revision INTEGER NOT NULL,commands TEXT NOT NULL,cursor INTEGER NOT NULL,history TEXT NOT NULL,ids TEXT NOT NULL DEFAULT '{}')")
    if 'ids' not in {row[1] for row in con.execute('PRAGMA table_info(editing)')}:
        try:con.execute("ALTER TABLE editing ADD COLUMN ids TEXT NOT NULL DEFAULT '{}'")
        except sqlite3.OperationalError:
            if 'ids' not in {row[1] for row in con.execute('PRAGMA table_info(editing)')}:raise
    for column,declaration in [('uploaded_at','TEXT'),('version_base','INTEGER NOT NULL DEFAULT 0')]:
        if column not in {row[1] for row in con.execute('PRAGMA table_info(books)')}:
            try:con.execute(f'ALTER TABLE books ADD COLUMN {column} {declaration}')
            except sqlite3.OperationalError:
                if column not in {row[1] for row in con.execute('PRAGMA table_info(books)')}:raise
    con.execute("CREATE TABLE IF NOT EXISTS publications (book_id TEXT NOT NULL REFERENCES books(id),version INTEGER NOT NULL,published_at TEXT NOT NULL,revision INTEGER NOT NULL,sha256 TEXT NOT NULL,epub BLOB NOT NULL,validation TEXT NOT NULL,request_id TEXT NOT NULL,PRIMARY KEY(book_id,version),UNIQUE(book_id,request_id))")
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS project_filename_upload ON books(name,uploaded_at) WHERE uploaded_at IS NOT NULL')
    con.execute("CREATE TABLE IF NOT EXISTS projects (book_id TEXT PRIMARY KEY REFERENCES books(id), metadata TEXT NOT NULL, pdf BLOB)")
    con.execute("CREATE TABLE IF NOT EXISTS editing_removed(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,path TEXT NOT NULL,PRIMARY KEY(book_id,path))")
    con.execute("CREATE TABLE IF NOT EXISTS editing_files(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,path TEXT NOT NULL,content BLOB NOT NULL,PRIMARY KEY(book_id,path))")
    ai_schema.ensure(con)
    unit_store.ensure(con)
    con.commit()
    if unit_store.USE_NEW_STORAGE and con.execute('SELECT 1 FROM books WHERE id NOT IN (SELECT book_id FROM unit_books) LIMIT 1').fetchone():
        con.execute('BEGIN IMMEDIATE')
        try:unit_store.migrate_all(con);con.commit()
        except Exception:con.rollback();con.close();raise
    missing=con.execute('SELECT book_id FROM unit_books WHERE book_id NOT IN (SELECT book_id FROM proof_scores)').fetchall()
    if missing:
        con.execute('BEGIN IMMEDIATE')
        try:
            for book_id, in missing:proof_score.rebuild(con,book_id)
            con.commit()
        except Exception:con.rollback();con.close();raise
    try:
        with con:
            yield con
    finally:
        con.close()

@contextmanager
def database():
    with maintenance.access():
        with _database() as con:yield con

@app.middleware('http')
async def unit_owner(request:Request,call_next):
    token=unit_store.edit_owner.set(request.headers.get('X-Edit-Owner'))
    try:return await call_next(request)
    finally:unit_store.edit_owner.reset(token)

@lru_cache(maxsize=4)
def load_book(book_id: str):
    # Validate before querying; identifiers are random and never filesystem paths.
    try:
        uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(404, "書籍がありません。")
    with database() as con:
        row = con.execute("SELECT original FROM books WHERE id=?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "書籍がありません。")
    return Book(row[0],repair_import=True)

from fastapi.exceptions import RequestValidationError
@app.exception_handler(RequestValidationError)
async def invalid_request(request,exc):
    from fastapi.responses import JSONResponse
    # Request validation must never echo API-key inputs back to the browser or logs.
    errors=[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]
    return JSONResponse(status_code=422,content={'detail':errors})

@app.exception_handler(EpubError)
async def epub_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": str(exc)})

@app.exception_handler(sqlite3.OperationalError)
async def database_error(request,exc):
    from fastapi.responses import JSONResponse
    code=getattr(exc,'sqlite_errorcode',0) or 0
    busy=code & 255 in {sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED} or str(exc).lower() in {'database is locked','database table is locked'}
    if busy:
        return JSONResponse(status_code=503,content={'detail':'保存処理が混み合っています。少し待ってからもう一度操作してください。入力内容は保持されています。'},headers={'Retry-After':'2'})
    return JSONResponse(status_code=500,content={'detail':'保存データの処理に失敗しました。サーバーの記録を確認してください。'})

@app.get("/api/health")
def health():
    return {"status": "ok", "phase": 5}

@app.post("/api/books")
async def import_book(file: UploadFile):
    if not (file.filename or "").lower().endswith(".epub"):
        raise HTTPException(415, "EPUBファイルを選択してください。")
    data = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            data.extend(chunk)
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, "EPUBは64 MiB以下にしてください。")
    finally:
        await file.close()
    book = Book(bytes(data),repair_import=True)
    book_id = str(uuid.uuid4())
    with database() as con:
        library.create(con,book_id,Path(file.filename).name,book)
        if book.import_repairs and not unit_store.USE_NEW_STORAGE:
            editing.save_state(con,book_id,{'working':book.normalized,'revision':0,'commands':[],'cursor':0,'history':[],'ids':{}})
    return snapshot(book_id)

@app.get("/api/books/{book_id}")
def get_book(book_id: str):
    return snapshot(book_id)

@app.get("/api/books/{book_id}/chapters/{chapter_id}")
def get_chapter(book_id: str, chapter_id: str):
    return {"html": working_book(book_id).preview(chapter_id, book_id)}

@app.get("/api/books/{book_id}/assets/{asset_path:path}")
def get_asset(book_id: str, asset_path: str):
    book = load_book(book_id)
    item = next((i for i in book.manifest if i["path"] == asset_path), None)
    if item is None or item["media_type"] not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        raise HTTPException(404, "表示可能な画像がありません。")
    return Response(book.get(asset_path), media_type=item["media_type"], headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})

@app.get("/api/books/{book_id}/original")
def original(book_id: str):
    return Response(load_book(book_id).original, media_type="application/epub+zip", headers={"Content-Disposition": 'attachment; filename="original.epub"', "X-Content-Type-Options": "nosniff"})

@app.get("/api/samples/{name}")
def sample(name: str):
    if name not in {"book.epub", "original.pdf", "decoder-regression.pdf"}:
        raise HTTPException(404, "サンプルがありません。")
    from fastapi.responses import FileResponse
    return FileResponse(ROOT / "samples" / name)

class RevisionRequest(BaseModel):
    revision: int = Field(ge=0)
    reason: str = Field(default="手動校正", max_length=1000)

class TextRequest(RevisionRequest):
    expected_token: str | None = Field(default=None,min_length=64,max_length=64)
    text: str = Field(max_length=20000)
    sentence_index: int | None = Field(default=None,ge=0)
    expected_sentence: str | None = Field(default=None,max_length=20000)

class RubyUpdate(BaseModel):
    index:int=Field(ge=0)
    base:str=Field(min_length=1,max_length=1000)
    reading:str=Field(min_length=1,max_length=2000)

class CombinedRequest(TextRequest):
    rubies:list[RubyUpdate]=Field(default_factory=list,max_length=1000)

class StructureRequest(RevisionRequest):
    expected_token: str | None = Field(default=None,min_length=64,max_length=64)
    expected_chapter_token: str | None = Field(default=None,min_length=64,max_length=64)
    action: Literal['insert','split','merge','merge_next','insert_boundary','blank','delete','chapter_merge']
    paragraph_id: str = Field(max_length=128)
    position: Literal['before','after'] = 'after'
    text: str = Field(default='',max_length=20000)
    offset: int | None = Field(default=None,ge=0)
    sentence_index:int|None=Field(default=None,ge=0,strict=True)

class RubyRequest(RevisionRequest):
    expected_token: str | None = Field(default=None,min_length=64,max_length=64)
    range_start:int|None=Field(default=None,ge=0,strict=True)
    range_end:int|None=Field(default=None,ge=1,strict=True)
    base: str = Field(min_length=1,max_length=1000)
    reading: str = Field(min_length=1,max_length=2000)

class ReplaceRequest(RevisionRequest):
    target: str = Field(min_length=1,max_length=1000)
    replacement: str = Field(max_length=1000)
    paragraph_id: str | None = Field(default=None,max_length=128)

@app.exception_handler(editing.EditConflict)
async def edit_conflict(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409,content={"detail":str(exc)})

def current_state(book_id):
    load_book(book_id)
    with database() as con:
        return editing.state(con,book_id)

def working_book(book_id):
    return editing.working_model(current_state(book_id))

def snapshot(book_id,value=None,metadata=None,catalog=None):
    original = load_book(book_id)
    value = value if value is not None else current_state(book_id)
    working = editing.working_model(value)
    result = copy.deepcopy(working.summary())
    if metadata is None:
        with database() as con:metadata=projects.read(con,book_id)
    if catalog is None:
        with database() as con:catalog=library.info(con,book_id)
    if value.get('proof_score') is not None:result['proof_score']=value['proof_score']
    result['import_repairs']=original.import_repairs
    result['warnings']=list(dict.fromkeys([*original.warnings,*result['warnings']]))
    originals = {p['id']:p for c in original.chapters for p in [*c['paragraphs'],*c.get('headings',[])]}
    for chapter in result['chapters']:
        for paragraph in [*chapter['paragraphs'],*chapter.get('headings',[])]:
            if result.get('storage_mode')=='units':
                from . import reviews
                paragraph['review_state']=reviews.both(metadata,reviews.record_details(paragraph));paragraph['status']='human_checked' if paragraph['review_state']['body']['confirmed'] else metadata['statuses'].get(paragraph['id'],'unchecked')
                if paragraph['status']=='human_checked' and not paragraph['review_state']['body']['confirmed']:paragraph['status']='review'
                continue
            previous = originals.get(paragraph['id'],{'original_xml':'','text':''})
            paragraph['current_xml'] = paragraph['original_xml']
            paragraph['edited'] = paragraph['original_xml'] != previous['original_xml']
            paragraph['original_xml'] = previous['original_xml']
            paragraph['original_text'] = previous['text']
            paragraph['revision'] = value['revision']
            from . import reviews
            d=reviews.record_details(paragraph)
            paragraph['review_state']=reviews.both(metadata,d)
            paragraph['status'] = 'human_checked' if paragraph['review_state']['body']['confirmed'] else metadata['statuses'].get(paragraph['id'],'unchecked')
            if paragraph['status']=='human_checked' and not paragraph['review_state']['body']['confirmed']:paragraph['status']='review'
    return {'id':book_id,**result,'fingerprint':original.fingerprint,'working_fingerprint':working.fingerprint,'edit_state':editing.edit_info(value),'project':metadata,'catalog':catalog,'progress':projects.progress(working,metadata)}

def mutate(book_id,request,kind,**kwargs):
    load_book(book_id)
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        if unit_store.enabled(con,book_id):
            if kind in {'undo','redo'}:raise EpubError('Undo／Redoは廃止しました。')
            if kind=='replace':
                unit_store.replace(con,book_id,request,kwargs.get('paragraph_id'),kwargs['target'],kwargs['replacement'])
                return snapshot(book_id,editing.state(con,book_id),projects.read(con,book_id),library.info(con,book_id))
            result,structural=unit_store.mutate(con,book_id,kind,request,**kwargs)
            if not structural:return result
            value=editing.state(con,book_id);result_book=snapshot(book_id,value,projects.read(con,book_id),library.info(con,book_id))
            if result:result_book['focus_paragraph_id']=result
            return result_book
        before_revision=editing.state(con,book_id)['revision']
        value = editing.commit_edit(con,book_id,request.revision,kind,reason=request.reason,expected_token=getattr(request,'expected_token',None),expected_chapter_token=getattr(request,'expected_chapter_token',None),**kwargs)
        if value['revision']!=before_revision:projects.invalidate(con,book_id,value)
        from . import reviews
        pid=kwargs.get('paragraph_id')
        if pid and kind in {'text','sentence','combined'}:
            reviews.mark(con,book_id,pid,'body',kwargs.get('sentence_index'))
        elif pid and kind=='ruby':reviews.mark(con,book_id,pid,'ruby',kwargs.get('ruby_index'))
        elif pid and kind in {'ruby_add','ruby_delete'}:
            meta=projects.read(con,book_id);d=editing.paragraph_details(editing.working_model(value),pid,value['revision'])
            was_confirmed=reviews.summary(meta,d)['confirmed'];row=meta.setdefault('reviews',{}).setdefault(pid,{})
            if was_confirmed and not row.get('body'):row['body']={'all':reviews.digest(d['editor_text'])}
            row['ruby']={};meta['version']+=1;projects.write(con,book_id,meta)
            if kind=='ruby_add':
                d=editing.paragraph_details(editing.working_model(value),pid,value['revision'])
                index=next(r['index'] for r in d['rubies'] if r['start']==kwargs['range_start'])
                reviews.mark(con,book_id,pid,'ruby',index)
        result = snapshot(book_id,value,projects.read(con,book_id),library.info(con,book_id))
        if value.get('focus_id'):result['focus_paragraph_id']=value['focus_id']
    return result

@app.get('/api/books/{book_id}/paragraphs/{paragraph_id}')
def editor(book_id: str,paragraph_id: str):
    with database() as con:
        if unit_store.enabled(con,book_id):return unit_store.direct_details(con,book_id,paragraph_id)
    value = current_state(book_id)
    d=editing.paragraph_details(editing.working_model(value),paragraph_id,value['revision'])
    from . import reviews
    with database() as con:d['review_state']=reviews.both(projects.read(con,book_id),d)
    return d

@app.post('/api/books/{book_id}/paragraphs/{paragraph_id}/lock')
def acquire_unit_lock(book_id:str,paragraph_id:str):
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        if unit_store.enabled(con,book_id):unit_store.lock(con,book_id,paragraph_id,unit_store.edit_owner.get())
    return {'expires_in':60}

@app.delete('/api/books/{book_id}/paragraphs/{paragraph_id}/lock')
def release_unit_lock(book_id:str,paragraph_id:str):
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        if unit_store.enabled(con,book_id):
            # A deleted unit may disappear before an editor unmounts.
            con.execute('DELETE FROM unit_locks WHERE book_id=? AND unit_id=? AND owner=?',(book_id,paragraph_id,unit_store.edit_owner.get()))
    return {'released':True}

class ReviewDraftRuby(BaseModel):
    base:str=Field(max_length=1000)
    reading:str=Field(max_length=2000)

class ReviewDraftRange(BaseModel):
    index:int=Field(ge=0)
    start:int=Field(ge=0)
    end:int=Field(ge=1)
    baseBefore:str=Field(max_length=1000)
    readingBefore:str=Field(max_length=2000)

class ReviewDraft(BaseModel):
    paragraphToken:str|None=Field(default=None,max_length=64)
    revision:int=Field(ge=0)
    text:str=Field(max_length=20000)
    rubies:dict[str,ReviewDraftRuby]=Field(default_factory=dict,max_length=1000)
    reason:str=Field(max_length=1000)
    paragraphId:str=Field(max_length=128)
    sentenceIndex:int|None=Field(default=None,ge=0)
    before:str=Field(max_length=20000)
    rubyRange:ReviewDraftRange|None=None

class ReviewDraftPatch(BaseModel):
    key:str=Field(max_length=256)
    expected:ReviewDraft|None=None
    value:ReviewDraft|None=None

class ReviewRequest(BaseModel):
    target: Literal['body','ruby'] = 'body'
    index: int | None = Field(default=None,ge=0)
    expected_token: str = Field(min_length=64,max_length=64)
    compact:bool=False
    draft_patch:ReviewDraftPatch|None=None

class ReviewReset(BaseModel):
    scope: Literal['paragraph','chapter','book'] = 'paragraph'
    target: Literal['body','ruby','both'] = 'body'
    paragraph_id: str | None = None
    chapter_id: str | None = None

class RubyStructureRequest(RevisionRequest):
    action: Literal['add','delete']
    expected_token: str = Field(min_length=64,max_length=64)
    start: int | None = Field(default=None,ge=0)
    end: int | None = Field(default=None,ge=1)
    reading: str | None = Field(default=None,min_length=1,max_length=2000)
    index: int | None = Field(default=None,ge=0)

@app.post('/api/books/{book_id}/paragraphs/{paragraph_id}/review')
def confirm_review(book_id:str,paragraph_id:str,request:ReviewRequest):
    from . import reviews
    load_book(book_id)
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        patch=request.draft_patch.model_dump(exclude_unset=True) if request.draft_patch else None
        receipt=reviews.mark(con,book_id,paragraph_id,request.target,request.index,request.expected_token,compact=request.compact,draft_patch=patch)
        if request.compact:return receipt
        result=snapshot(book_id,editing.state(con,book_id),projects.read(con,book_id),library.info(con,book_id))
    return result

@app.post('/api/books/{book_id}/review/reset')
def reset_review(book_id:str,request:ReviewReset):
    from . import reviews
    load_book(book_id)
    with database() as con:
        con.execute('BEGIN IMMEDIATE');value=editing.state(con,book_id);book=editing.working_model(value);meta=projects.read(con,book_id)
        ids=[p['id'] for c in book.chapters if request.scope!='chapter' or c['id']==request.chapter_id for p in [*c['paragraphs'],*c.get('headings',[])] if request.scope!='paragraph' or p['id']==request.paragraph_id]
        if not ids:raise EpubError('対象の段落がありません。')
        for pid in ids:
            if unit_store.enabled(con,book_id):
                targets=('body','ruby') if request.target=='both' else (request.target,)
                for target in targets:con.execute('DELETE FROM unit_reviews WHERE book_id=? AND unit_id=? AND target=?',(book_id,pid,target))
            d=editing.paragraph_details(book,pid,value['revision']);was=reviews.summary(meta,d)['confirmed']
            row=meta.setdefault('reviews',{}).setdefault(pid,{})
            if was and 'body' not in row:row['body']={'all':reviews.digest(d['editor_text'])}
            for target in ('body','ruby'):
                if request.target in {target,'both'}:row[target]={}
            meta['statuses'][pid]='human_checked' if reviews.summary(meta,d)['confirmed'] else 'unchecked'
        meta['version']+=1;projects.write(con,book_id,meta)
        if unit_store.enabled(con,book_id):proof_score.rebuild(con,book_id,book)
        value['proof_score']=proof_score.read(con,book_id)
        result=snapshot(book_id,value,meta,library.info(con,book_id))
    return result

@app.post('/api/books/{book_id}/paragraphs/{paragraph_id}/ruby-structure')
def change_ruby_structure(book_id:str,paragraph_id:str,request:RubyStructureRequest):
    return mutate(book_id,request,'ruby_'+request.action,paragraph_id=paragraph_id,range_start=request.start,range_end=request.end,reading=request.reading,ruby_index=request.index)

@app.patch('/api/books/{book_id}/paragraphs/{paragraph_id}')
def edit_text(book_id: str,paragraph_id: str,request: TextRequest):
    return mutate(book_id,request,'sentence' if request.sentence_index is not None else 'text',paragraph_id=paragraph_id,text=request.text,sentence_index=request.sentence_index,expected_sentence=request.expected_sentence)

@app.patch('/api/books/{book_id}/paragraphs/{paragraph_id}/edit')
def edit_combined(book_id:str,paragraph_id:str,request:CombinedRequest):
    return mutate(book_id,request,'combined',paragraph_id=paragraph_id,text=request.text,sentence_index=request.sentence_index,expected_sentence=request.expected_sentence,rubies=[r.model_dump() for r in request.rubies])

@app.post('/api/books/{book_id}/structure')
def edit_structure(book_id: str,request: StructureRequest):
    return mutate(book_id,request,request.action,paragraph_id=request.paragraph_id,text=request.text,position=request.position,offset=request.offset,sentence_index=request.sentence_index)

class ChapterSplitRequest(RevisionRequest):
    paragraph_id:str=Field(max_length=128)
    title:str=Field(min_length=1,max_length=200)
    level:int=Field(default=1,ge=1,le=6,strict=True)
    position:Literal['before','after']|None=None
    sentence_index:int|None=Field(default=None,ge=0,strict=True)
    expected_token:str=Field(min_length=64,max_length=64)
    expected_chapter_token:str=Field(min_length=64,max_length=64)

@app.post('/api/books/{book_id}/chapters/split')
def split_chapter(book_id:str,request:ChapterSplitRequest):
    return mutate(book_id,request,'chapter_split',paragraph_id=request.paragraph_id,text=request.title,chapter_level=request.level,chapter_position=request.position,sentence_index=request.sentence_index)

@app.patch('/api/books/{book_id}/paragraphs/{paragraph_id}/rubies/{ruby_index}')
def edit_ruby(book_id: str,paragraph_id: str,ruby_index: int,request: RubyRequest):
    return mutate(book_id,request,'ruby',paragraph_id=paragraph_id,ruby_index=ruby_index,base=request.base,reading=request.reading,range_start=request.range_start,range_end=request.range_end)

@app.post('/api/books/{book_id}/undo')
def undo(book_id: str,request: RevisionRequest):
    return mutate(book_id,request,'undo')

@app.post('/api/books/{book_id}/redo')
def redo(book_id: str,request: RevisionRequest):
    return mutate(book_id,request,'redo')

@app.post('/api/books/{book_id}/replace')
def replace(book_id: str,request: ReplaceRequest):
    return mutate(book_id,request,'replace',paragraph_id=request.paragraph_id,target=request.target,replacement=request.replacement)

@app.get('/api/books/{book_id}/history')
def history(book_id: str):
    original = load_book(book_id)
    value = current_state(book_id)
    if isinstance(value['working'],unit_store.Source):raise HTTPException(410,'操作履歴の保存は廃止しました。作業データ（.eproof）を書き出してください。')
    return projects.history_export(original,value)

@app.get('/api/books/{book_id}/export')
def export(book_id: str, revision: int | None = None):
    original = load_book(book_id)
    value = current_state(book_id)
    if revision is not None and revision != value['revision']:
        raise editing.EditConflict('検証後に内容が変更されています。出力画面を開き直してください。')
    data,_ = editing.validate_export(original,editing.working_model(value),value['commands'][:value['cursor']])
    with database() as con:
        name = con.execute('SELECT name FROM books WHERE id=?',(book_id,)).fetchone()[0]
    filename = Path(name).stem + '_corrected.epub'
    return Response(data,media_type='application/epub+zip',headers={'Content-Disposition':f"attachment; filename=corrected.epub; filename*=UTF-8''{quote(filename)}",'X-Content-Type-Options':'nosniff'})

@app.post('/api/books/{book_id}/validate')
def validate(book_id: str,request: RevisionRequest):
    value = current_state(book_id)
    if request.revision != value['revision']:
        raise editing.EditConflict('編集中の内容が更新されています。最新の状態で検証してください。')
    data,internal = editing.validate_export(load_book(book_id),editing.working_model(value),value['commands'][:value['cursor']])
    return {'revision':value['revision'],'internal':internal,'epubcheck':epubcheck(data)}

from .project_api import install
install(app,database,load_book,snapshot,current_state)

from .ai.api import install as install_ai
install_ai(app,database,load_book,snapshot,DATA_DIR)

# Production serves the Vite build from the same origin as the API.
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
