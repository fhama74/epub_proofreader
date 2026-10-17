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
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from .epub import Book, EpubError, MAX_UPLOAD

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR",os.getenv("EPROOF_DATA_DIR", str(ROOT / ".data"))))
app = FastAPI(title="EPUB Proofreader", version="0.5.8")

@contextmanager
def database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / "library.sqlite3")
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
    con.execute("CREATE TABLE IF NOT EXISTS projects (book_id TEXT PRIMARY KEY REFERENCES books(id), metadata TEXT NOT NULL, pdf BLOB)")
    con.execute("CREATE TABLE IF NOT EXISTS editing_files(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,path TEXT NOT NULL,content BLOB NOT NULL,PRIMARY KEY(book_id,path))")
    ai_schema.ensure(con)
    con.commit()
    try:
        with con:
            yield con
    finally:
        con.close()

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
        if book.import_repairs:
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
    action: Literal['insert','split','merge']
    paragraph_id: str = Field(max_length=128)
    position: Literal['before','after'] = 'after'
    text: str = Field(default='',max_length=20000)
    offset: int | None = Field(default=None,ge=0)

class RubyRequest(RevisionRequest):
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
    result['import_repairs']=original.import_repairs
    result['warnings']=list(dict.fromkeys([*original.warnings,*result['warnings']]))
    originals = {p['id']:p for c in original.chapters for p in [*c['paragraphs'],*c.get('headings',[])]}
    for chapter in result['chapters']:
        for paragraph in [*chapter['paragraphs'],*chapter.get('headings',[])]:
            previous = originals.get(paragraph['id'],{'original_xml':'','text':''})
            paragraph['current_xml'] = paragraph['original_xml']
            paragraph['edited'] = paragraph['original_xml'] != previous['original_xml']
            paragraph['original_xml'] = previous['original_xml']
            paragraph['original_text'] = previous['text']
            paragraph['revision'] = value['revision']
            paragraph['status'] = metadata['statuses'].get(paragraph['id'],'unchecked')
    return {'id':book_id,**result,'fingerprint':original.fingerprint,'working_fingerprint':working.fingerprint,'edit_state':editing.edit_info(value),'project':metadata,'catalog':catalog,'progress':projects.progress(working,metadata)}

def mutate(book_id,request,kind,**kwargs):
    load_book(book_id)
    with database() as con:
        con.execute('BEGIN IMMEDIATE')
        value = editing.commit_edit(con,book_id,request.revision,kind,reason=request.reason,**kwargs)
        if value['revision']!=request.revision:projects.invalidate(con,book_id,value)
        result = snapshot(book_id,value,projects.read(con,book_id),library.info(con,book_id))
        if value.get('focus_id'):result['focus_paragraph_id']=value['focus_id']
    return result

@app.get('/api/books/{book_id}/paragraphs/{paragraph_id}')
def editor(book_id: str,paragraph_id: str):
    value = current_state(book_id)
    return editing.paragraph_details(editing.working_model(value),paragraph_id,value['revision'])

@app.patch('/api/books/{book_id}/paragraphs/{paragraph_id}')
def edit_text(book_id: str,paragraph_id: str,request: TextRequest):
    return mutate(book_id,request,'sentence' if request.sentence_index is not None else 'text',paragraph_id=paragraph_id,text=request.text,sentence_index=request.sentence_index,expected_sentence=request.expected_sentence)

@app.patch('/api/books/{book_id}/paragraphs/{paragraph_id}/edit')
def edit_combined(book_id:str,paragraph_id:str,request:CombinedRequest):
    return mutate(book_id,request,'combined',paragraph_id=paragraph_id,text=request.text,sentence_index=request.sentence_index,expected_sentence=request.expected_sentence,rubies=[r.model_dump() for r in request.rubies])

@app.post('/api/books/{book_id}/structure')
def edit_structure(book_id: str,request: StructureRequest):
    return mutate(book_id,request,request.action,paragraph_id=request.paragraph_id,text=request.text,position=request.position,offset=request.offset)

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
