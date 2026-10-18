from __future__ import annotations
import hashlib,json,uuid
from pathlib import Path
from urllib.parse import quote
from fastapi import UploadFile,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel,Field
from . import projects,editing,library,unit_store,unit_archive,proof_score,maintenance
from .epub import EpubError
from .validation import epubcheck
from .ai import backup as ai_backup
from datetime import datetime,timezone

class ProjectPatch(BaseModel):
    version:int=Field(ge=0)
    view:dict|None=None
    statuses:dict|None=None
    mappings:dict|None=None
    drafts:dict|None=None

async def bounded(file,limit):
    data=bytearray()
    try:
        while chunk:=await file.read(1024*1024):
            data.extend(chunk)
            if len(data)>limit:raise HTTPException(413,'ファイルがサイズ上限を超えています。')
    finally:await file.close()
    return bytes(data)

class PublishRequest(BaseModel):
    revision:int=Field(ge=0)
    expected_version:int=Field(ge=0,lt=1000000000)
    request_id:uuid.UUID

class DeleteRequest(BaseModel):
    filename:str=Field(max_length=256)
    revision:int=Field(ge=0)
    published_version:int=Field(ge=0)

def install(app,database,load_book,snapshot,current_state):
    def response(con,book_id):
        value=projects.read(con,book_id)
        return {**value,'proof_score':proof_score.read(con,book_id),'catalog':library.info(con,book_id),'progress':projects.progress(editing.working_model(editing.state(con,book_id)),value)}

    @app.get('/api/projects')
    def list_projects():
        with database() as con:
            items=[]
            for row in con.execute('SELECT b.id,b.name,b.uploaded_at,b.version_base,COALESCE(e.revision,0),COALESCE(e.cursor,0),COALESCE(length(p.pdf),0),length(b.original)+COALESCE(length(e.working),0)+COALESCE((SELECT SUM(length(f.content)) FROM editing_files f WHERE f.book_id=b.id),0)+COALESCE(length(p.pdf),0)+COALESCE(length(CAST(p.metadata AS BLOB)),0)+COALESCE(length(CAST(e.commands AS BLOB)),0)+COALESCE(length(CAST(e.history AS BLOB)),0)+COALESCE(length(CAST(e.ids AS BLOB)),0) FROM books b LEFT JOIN editing e ON e.book_id=b.id LEFT JOIN projects p ON p.book_id=b.id ORDER BY b.uploaded_at DESC,b.rowid DESC'):
                catalog=library.info(con,row[0]);published_bytes=con.execute('SELECT COALESCE(SUM(length(epub)+length(CAST(validation AS BLOB))),0) FROM publications WHERE book_id=?',(row[0],)).fetchone()[0]
                ai_bytes=con.execute("SELECT COALESCE((SELECT SUM(length(CAST(payload AS BLOB))) FROM ai_items WHERE job_id IN (SELECT id FROM ai_jobs WHERE book_id=?)),0)+COALESCE((SELECT SUM(length(CAST(data AS BLOB))) FROM ai_results WHERE book_id=?),0)",(row[0],row[0])).fetchone()[0]
                items.append({'id':row[0],**catalog,'revision':row[4],'edit_count':row[5],'pdf_attached':row[6]>0,'size':row[7]+published_bytes+ai_bytes})
                if unit_store.enabled(con,row[0]):
                    items[-1]['proof_score']=proof_score.read(con,row[0])
                    revision,edits=con.execute('SELECT revision,edits FROM unit_books WHERE book_id=?',(row[0],)).fetchone()
                    size=con.execute('SELECT COALESCE(SUM(length(xml)+COALESCE(length(record),0)),0) FROM unit_nodes WHERE book_id=?',(row[0],)).fetchone()[0]
                    items[-1].update(revision=revision,edit_count=edits,size=items[-1]['size']+size)
            location=Path(con.execute('PRAGMA database_list').fetchone()[2])
            return {'projects':items,'storage':{'path':str(location.parent),'database':str(location),'used_bytes':sum(item['size'] for item in items),'database_bytes':location.stat().st_size if location.exists() else 0,'project_count':len(items)}}

    @app.post('/api/storage/compact')
    def compact_database():
        with maintenance.exclusive():
            with database() as con:
                try:return maintenance.compact(con)
                except ValueError as exc:raise EpubError(str(exc)) from None

    @app.post('/api/books/{book_id}/delete')
    def delete_project(book_id:str,request:DeleteRequest):
        load_book(book_id)
        with database() as con:
            con.execute('BEGIN IMMEDIATE');catalog=library.info(con,book_id);value=editing.state(con,book_id)
            if request.filename!=catalog['filename'] or request.revision!=value['revision'] or request.published_version!=catalog['published_version']:raise editing.EditConflict('プロジェクトが更新されています。一覧を開き直して確認してください。')
            for table in ('publications','projects','editing'):con.execute(f'DELETE FROM {table} WHERE book_id=?',(book_id,))
            con.execute('DELETE FROM books WHERE id=?',(book_id,))
        load_book.cache_clear()
        return {'deleted':book_id}

    @app.get('/api/books/{book_id}/publications')
    def list_publications(book_id:str):
        load_book(book_id)
        with database() as con:return {'catalog':library.info(con,book_id),'publications':library.releases(con,book_id)}

    @app.post('/api/books/{book_id}/publish')
    def publish(book_id:str,request:PublishRequest):
        original=load_book(book_id);token=str(request.request_id)
        def previous(con):
            row=con.execute('SELECT version,published_at,revision,sha256,length(epub),validation,request_id FROM publications WHERE book_id=? AND request_id=?',(book_id,token)).fetchone()
            if row:
                if row[2]!=request.revision or row[0]!=request.expected_version+1:raise editing.EditConflict('発行リクエストの内容が一致しません。')
                return library.release_info(row)
        with database() as con:
            existing=previous(con)
            if existing:return {'publication':existing,'book':snapshot(book_id)}
            catalog=library.info(con,book_id);value=editing.state(con,book_id)
        if value['revision']!=request.revision or catalog['published_version']!=request.expected_version:raise editing.EditConflict('編集中の内容または発行版が更新されています。発行画面を開き直してください。')
        data,internal=editing.validate_export(original,editing.working_model(value),value['commands'][:value['cursor']])
        version=request.expected_version+1;published_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        data=library.stamp(data,version,book_id,token,published_at);check=epubcheck(data)
        if check['status'] not in {'passed','unavailable'}:raise EpubError('発行後のEPUBCheckに成功しませんでした。版は追加していません。検証結果を確認してください。')
        validation={'internal':internal,'epubcheck':check};digest=hashlib.sha256(data).hexdigest()
        with database() as con:
            con.execute('BEGIN IMMEDIATE');existing=previous(con)
            if existing:publication=existing
            else:
                current=editing.state(con,book_id);catalog=library.info(con,book_id)
                if current['revision']!=request.revision or catalog['published_version']!=request.expected_version:raise editing.EditConflict('検証中に編集・発行が行われました。版は追加していません。')
                con.execute('INSERT INTO publications VALUES (?,?,?,?,?,?,?,?)',(book_id,version,published_at,request.revision,digest,data,json.dumps(validation,ensure_ascii=False),token))
                publication=next(item for item in library.releases(con,book_id) if item['version']==version)
        return {'publication':publication,'book':snapshot(book_id)}

    @app.get('/api/books/{book_id}/publications/{version}/epub')
    def download_publication(book_id:str,version:int):
        load_book(book_id)
        with database() as con:
            row=con.execute('SELECT epub,sha256 FROM publications WHERE book_id=? AND version=?',(book_id,version)).fetchone();name=library.info(con,book_id)['filename']
        if row is None:raise HTTPException(404,'発行版がありません。')
        if hashlib.sha256(row[0]).hexdigest()!=row[1]:raise EpubError('保存された発行版のハッシュが一致しません。')
        filename=Path(name).stem+f'_v{version:03d}.epub'
        return Response(row[0],media_type='application/epub+zip',headers={'Content-Disposition':f"attachment; filename=published_v{version}.epub; filename*=UTF-8''{quote(filename)}",'X-Content-Type-Options':'nosniff'})

    @app.get('/api/books/{book_id}/project')
    def get_project(book_id:str):
        load_book(book_id)
        with database() as con:return response(con,book_id)

    @app.patch('/api/books/{book_id}/project')
    def patch_project(book_id:str,request:ProjectPatch):
        load_book(book_id)
        with database() as con:
            con.execute('BEGIN IMMEDIATE');meta=projects.read(con,book_id)
            if request.version!=meta['version']:raise editing.EditConflict('別の画面でプロジェクトが更新されています。再読み込みしてください。未保存入力はこのブラウザに保護されています。')
            book=editing.working_model(editing.state(con,book_id));pids={p['id'] for c in book.chapters for p in [*c['paragraphs'],*c.get('headings',[])]}
            for key in ('view','statuses','mappings','drafts'):
                patch=getattr(request,key)
                if patch is None:continue
                if key in {'statuses','mappings'} and not set(patch)<=pids:raise EpubError('この書籍にない段落が指定されています。')
                for ident,value in patch.items():
                    if key=='statuses' and unit_store.enabled(con,book_id):
                        unit_store.lock(con,book_id,ident,unit_store.edit_owner.get())
                        if value=='human_checked':
                            projects.write(con,book_id,meta)
                            unit_store.confirm(con,book_id,ident)
                            meta=projects.read(con,book_id)
                        else:
                            meta.setdefault('reviews',{}).setdefault(ident,{}).pop('body',None)
                            con.execute("DELETE FROM unit_reviews WHERE book_id=? AND unit_id=? AND target='body'",(book_id,ident))
                    if value is None:meta[key].pop(ident,None)
                    else:meta[key][ident]=value
            meta['version']+=1
            meta=projects.validate_metadata(meta,book,projects.pdf_data(con,book_id));projects.write(con,book_id,meta)
            if request.statuses and unit_store.enabled(con,book_id):
                for pid in request.statuses:proof_score.refresh_unit(con,book_id,pid,unit_store.direct_details(con,book_id,pid),meta)
            return response(con,book_id)

    @app.post('/api/books/{book_id}/pdf')
    async def attach_pdf(book_id:str,file:UploadFile):
        load_book(book_id)
        if not (file.filename or '').lower().endswith('.pdf'):raise EpubError('PDFファイルを選択してください。')
        name=Path(file.filename).name;data=await bounded(file,256*1024*1024)
        if b'%PDF-' not in data[:1024]:raise EpubError('PDFの形式が不正です。')
        with database() as con:
            con.execute('BEGIN IMMEDIATE');library.info(con,book_id);meta=projects.read(con,book_id);digest=hashlib.sha256(data).hexdigest()
            if not meta['pdf'] or meta['pdf']['sha256']!=digest:meta['view']['pdf']={'page':1,'zoom':1,'mode':'page','scrollLeft':0,'scrollTop':0}
            meta['pdf']={'name':name,'sha256':digest,'size':len(data)};meta['version']+=1
            projects.write(con,book_id,meta);con.execute('UPDATE projects SET pdf=? WHERE book_id=?',(data,book_id))
            return response(con,book_id)

    @app.get('/api/books/{book_id}/pdf')
    def get_pdf(book_id:str):
        load_book(book_id)
        with database() as con:data=projects.pdf_data(con,book_id)
        if data is None:raise HTTPException(404,'添付PDFがありません。')
        return Response(data,media_type='application/pdf',headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})

    @app.get('/api/books/{book_id}/project/export')
    def export_project(book_id:str):
        original=load_book(book_id)
        with database() as con:
            con.execute('BEGIN');value=editing.state(con,book_id);meta=projects.read(con,book_id);pdf=projects.pdf_data(con,book_id)
            name=con.execute('SELECT name FROM books WHERE id=?',(book_id,)).fetchone()[0]
            meta['catalog']=library.info(con,book_id)
            ai=ai_backup.export(con,book_id)
        editing.validate_export(original,editing.working_model(value),value['commands'][:value['cursor']])
        data=projects.encode_project(original,value,meta,pdf,name,ai=ai)
        return Response(data,media_type='application/zip',headers={'Content-Disposition':f"attachment; filename=project.eproof; filename*=UTF-8''{quote(Path(name).stem+'.eproof')}",'X-Content-Type-Options':'nosniff'})

    @app.post('/api/projects/import')
    async def import_project(file:UploadFile):
        if not (file.filename or '').lower().endswith('.eproof'):raise EpubError('.eproofファイルを選択してください。')
        data=await bounded(file,projects.MAX_PROJECT)
        original,value,meta,pdf,name=projects.decode_project(data);book_id=str(uuid.uuid4())
        with database() as con:
            con.execute('BEGIN IMMEDIATE')
            version=meta.pop('catalog',{}).get('published_version',library.embedded_version(original))
            if unit_store.USE_NEW_STORAGE:
                normalized=isinstance(value['working'],unit_store.Source)
                if not normalized:
                    from .epub import Book
                    original=Book(editing.materialize(value['working'])).apply_ids(value.get('ids',{}))
                    meta['reviews']={};meta['statuses']={};meta['version']+=1
                    value.pop('_ai_backup',None)
                library.create(con,book_id,name,original,base=version);projects.write(con,book_id,meta)
                if normalized:unit_archive.restore(con,book_id,value)
            else:
                library.create(con,book_id,name,original,base=version);editing.save_state(con,book_id,value);projects.write(con,book_id,meta)
            con.execute('UPDATE projects SET pdf=? WHERE book_id=?',(pdf,book_id))
            if '_ai_backup' in value:ai_backup.restore(con,book_id,value['_ai_backup'],value)
        return snapshot(book_id)

    @app.post('/api/books/{book_id}/history/import')
    async def import_history(book_id:str,file:UploadFile):
        if unit_store.USE_NEW_STORAGE:
            await file.close()
            raise HTTPException(410,'操作履歴の読み込みは廃止しました。作業データ（.eproof）を読み込んでください。')
        original=load_book(book_id);data=await bounded(file,64*1024*1024)
        try:
            payload=json.loads(data)
            if payload.get('schema_version')!=2:raise EpubError('この履歴は表示専用の旧形式です。復元にはPhase 3形式の履歴JSONまたは.eproofを使用してください。')
            if payload.get('original_sha256')!=original.fingerprint:raise EpubError('履歴の原本SHA-256が、この書籍と一致しません。')
            value=projects.replay(original,payload['state'])
            if payload.get('events')!=value['history'] or payload.get('working_content_sha256')!=projects.content_hash(editing.working_model(value)):raise EpubError('履歴のハッシュ・イベントが一致しません。')
        except EpubError:raise
        except (ValueError,KeyError,TypeError,IndexError) as exc:raise EpubError('履歴JSONの形式が不正です。') from exc
        # Import to a new copy so existing edits and project data are never overwritten.
        new_id=str(uuid.uuid4())
        with database() as con:
            name=con.execute('SELECT name FROM books WHERE id=?',(book_id,)).fetchone()[0]
            library.create(con,new_id,name,original,base=library.info(con,book_id)['published_version']);editing.save_state(con,new_id,value)
        return snapshot(new_id)
