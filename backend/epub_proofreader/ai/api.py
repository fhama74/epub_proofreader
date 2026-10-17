import asyncio,json,sqlite3
from functools import lru_cache
from uuid import uuid4
from typing import Literal
from fastapi import HTTPException,Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from .. import editing,projects,library
from . import engine_manager as em,jobs,prompts
from .models import Engine,Start
from .providers import PROVIDERS
from .proofreading import fingerprint

@lru_cache(maxsize=2)
def evidence(data,ids):
    return editing.working_model({'working':data,'ids':json.loads(ids)}),{}

def state(con,book_id):
    con.row_factory=sqlite3.Row
    engines={r[0]:json.loads(r[1]) for r in con.execute('SELECT id,config FROM ai_engines WHERE owner_id=?',(em.OWNER,))}
    result_jobs=[]
    for row in con.execute('SELECT * FROM ai_jobs WHERE book_id=? AND owner_id=? ORDER BY created_at DESC',(book_id,em.OWNER)).fetchall():
        j=dict(row);j['config']=json.loads(j['config']);counts=dict(con.execute('SELECT status,COUNT(*) FROM ai_items WHERE job_id=? GROUP BY status',(j['id'],)))
        j.update(total=sum(counts.values()),done=counts.get('done',0),failed=counts.get('failed',0))
        usage=con.execute('SELECT SUM(input_tokens),SUM(output_tokens),SUM(cost),SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) FROM ai_usage WHERE job_id=?',(j['id'],)).fetchone()
        j.update(input_tokens=usage[0] or 0,output_tokens=usage[1] or 0,cost=None if usage[3] else usage[2] or 0)
        j['errors']=[{'paragraph_id':r[0],'error':r[1]} for r in con.execute("SELECT paragraph_id,error FROM ai_items WHERE job_id=? AND status='failed'",(j['id'],))]
        result_jobs.append(j)
    results=[];value=editing.state(con,book_id);active={c['id'] for c in value['commands'][:value['cursor']]};known={c['id'] for c in value['commands']}
    book=None;hashes={}
    for row in con.execute('SELECT * FROM ai_results WHERE book_id=? AND owner_id=? AND id NOT IN (SELECT result_id FROM ai_cleared_results) ORDER BY created_at,id',(book_id,em.OWNER)).fetchall():
        r=dict(row);r.update(json.loads(r.pop('data')));r['engine_name']=engines.get(r['engine_id'],{}).get('name',next((j['config']['name'] for j in result_jobs if j['id']==r['job_id']),r['model_name']))
        if r['command_id']:
            r['status']='approved' if r['command_id'] in active else 'undone' if r['command_id'] in known else 'superseded'
        if r['status'] in {'pending','held','undone'}:
            if book is None:book,hashes=evidence(value['working'],json.dumps(value['ids'],sort_keys=True))
            pid=r['paragraph_id']
            if pid not in hashes:
                try:hashes[pid]=fingerprint(editing.paragraph_details(book,pid,value['revision'],include_tokens=False))
                except ValueError:hashes[pid]=None
            r['stale']=r['source_hash']!=hashes[pid] or r['target']=='text' and not 1<=len(r['original'])<=2
        else:r['stale']=False
        results.append(r)
    for j in result_jobs:
        mine=[r for r in results if r['job_id']==j['id']];j['candidates']=len(mine);j['unreviewed']=sum(r['status'] in {'pending','undone'} for r in mine)
    cleared=con.execute('SELECT COUNT(*) FROM ai_cleared_results WHERE result_id IN (SELECT id FROM ai_results WHERE book_id=? AND owner_id=?)',(book_id,em.OWNER)).fetchone()[0]
    return {'jobs':result_jobs,'results':results,'cleared_count':cleared}

class BudgetChange(BaseModel):
    budget:float=Field(gt=0,le=10000)

class Decision(BaseModel):
    action:Literal['approve','reject','hold','confirm']
    revision:int

def install(app,database,load_book,snapshot,data_dir):
    worker=jobs.Worker(database,data_dir)
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lifespan(application):
        worker.launch()
        try:yield
        finally:worker.close()
    app.router.lifespan_context=lifespan
    app.state.ai_worker=worker
    @app.get('/api/ai/prompts')
    def get_prompts():
        with database() as con:return prompts.read(con)
    @app.put('/api/ai/prompts')
    def update_prompts(req:prompts.Update):
        with database() as con:
            con.execute('BEGIN IMMEDIATE');return prompts.save(con,req)
    @app.get('/api/ai/engines')
    def engines():
        with database() as con:return {'engines':[em.engine(con,r[0]) for r in con.execute('SELECT id FROM ai_engines WHERE owner_id=? ORDER BY created_at',(em.OWNER,))],'allowed_origins':sorted(em.allowed_origins())}
    @app.post('/api/ai/engines')
    def create_engine(req:Engine):
        with database() as con:
            con.execute('BEGIN IMMEDIATE');return em.save(con,req)
    @app.put('/api/ai/engines/{ident}')
    def update_engine(ident:str,req:Engine):
        with database() as con:
            con.execute('BEGIN IMMEDIATE');return em.save(con,req,ident)
    @app.delete('/api/ai/engines/{ident}')
    def delete_engine(ident:str):
        with database() as con:
            con.execute('BEGIN IMMEDIATE');em.engine(con,ident)
            if con.execute("SELECT 1 FROM ai_jobs WHERE engine_id=? AND status IN ('queued','running','pause_requested','paused','interrupted','budget_paused')",(ident,)).fetchone():raise HTTPException(409,'ジョブを中止してからエンジンを削除してください。')
            con.execute('DELETE FROM ai_engines WHERE id=?',(ident,));con.execute('DELETE FROM ai_acl WHERE engine_id=?',(ident,))
        return {'deleted':True}
    @app.post('/api/ai/engines/{ident}/test')
    @app.get('/api/ai/engines/{ident}/models')
    def test_engine(ident:str):
        with database() as con:e=em.engine(con,ident,True)
        if e['provider']!='ollama' and not e.get('api_key'):raise HTTPException(422,'APIキーを登録してください。')
        try:return {'models':PROVIDERS[e['provider']].models(e),'status':'connected'}
        except Exception as exc:raise HTTPException(502,str(exc) if type(exc) is ValueError else 'モデル一覧を取得できません。接続と認証を確認してください。') from None
    @app.post('/api/books/{book_id}/ai/quote')
    def quote(book_id:str,req:Start):
        load_book(book_id)
        with database() as con:return jobs.prepare(con,book_id,req)[2]
    @app.post('/api/books/{book_id}/ai/jobs')
    def start(book_id:str,req:Start):
        load_book(book_id)
        # Build paragraph snapshots and estimates without holding the write lock.
        # Recheck revision/engine settings when publishing the prepared job.
        with database() as con:
            prior=con.execute('SELECT id FROM ai_jobs WHERE book_id=? AND request_id=?',(book_id,req.request_id)).fetchone()
            if prior:return {'job_id':prior[0]}
            prepared=jobs.prepare(con,book_id,req)
        with database() as con:
            con.execute('BEGIN IMMEDIATE');ident=jobs.start(con,book_id,req,prepared=prepared)
        return {'job_id':ident}
    @app.post('/api/books/{book_id}/ai/jobs/{ident}/{action}')
    def control(book_id:str,ident:str,action:str,req:BudgetChange|None=None):
        load_book(book_id)
        with database() as con:
            con.execute('BEGIN IMMEDIATE')
            if req:
                row=con.execute('SELECT budget FROM ai_jobs WHERE id=? AND book_id=? AND owner_id=?',(ident,book_id,em.OWNER)).fetchone()
                if not row:raise HTTPException(404,'ジョブがありません。')
                if row[0] is not None and req.budget<row[0]:raise HTTPException(422,'再開時の上限額は現在の額以上を指定してください。')
                con.execute('UPDATE ai_jobs SET budget=? WHERE id=?',(req.budget,ident))
            jobs.control(con,book_id,ident,action)
        return {'ok':True}
    @app.get('/api/books/{book_id}/ai')
    def status(book_id:str):
        load_book(book_id)
        with database() as con:return state(con,book_id)
    @app.post('/api/books/{book_id}/ai/results/clear')
    def clear_results(book_id:str):
        load_book(book_id)
        with database() as con:
            con.execute('BEGIN IMMEDIATE')
            if con.execute("SELECT 1 FROM ai_jobs WHERE book_id=? AND owner_id=? AND status IN ('queued','running','pause_requested')",(book_id,em.OWNER)).fetchone():
                raise HTTPException(409,'AI校正を一時停止または中止してから、検出結果をクリアしてください。')
            con.execute('DELETE FROM ai_results WHERE book_id=? AND owner_id=?',(book_id,em.OWNER))
        return {'ok':True}
    @app.get('/api/books/{book_id}/ai/events')
    async def events(book_id:str,request:Request):
        load_book(book_id)
        async def stream():
            previous=None
            while not await request.is_disconnected():
                try:
                    def read():
                        with database() as con:
                            if not con.execute('SELECT 1 FROM books WHERE id=?',(book_id,)).fetchone():return None
                            return json.dumps(state(con,book_id),ensure_ascii=False)
                    value=await asyncio.to_thread(read)
                    if value is None:return
                    if value!=previous:yield 'data: '+value+'\n\n';previous=value
                    else:yield ': heartbeat\n\n'
                    await asyncio.sleep(2)
                except asyncio.CancelledError:return
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    @app.post('/api/books/{book_id}/ai/results/{ident}/decision')
    def decision(book_id:str,ident:str,req:Decision):
        load_book(book_id)
        with database() as con:
            con.execute('BEGIN IMMEDIATE');con.row_factory=sqlite3.Row
            row=con.execute('SELECT * FROM ai_results WHERE id=? AND book_id=? AND owner_id=? AND id NOT IN (SELECT result_id FROM ai_cleared_results)',(ident,book_id,em.OWNER)).fetchone()
            if not row:raise HTTPException(404,'候補がありません。')
            value=editing.state(con,book_id);active={c['id'] for c in value['commands'][:value['cursor']]}
            if row['command_id'] in active:raise HTTPException(409,'承認済みです。変更を戻す場合はUndoを使用してください。')
            if req.action=='approve':
                if row['command_id']:raise HTTPException(409,'この候補は編集履歴にあります。Redoまたは再検査を使用してください。')
                book=editing.working_model(value);d=editing.paragraph_details(book,row['paragraph_id'],value['revision']);s=json.loads(row['data'])
                if s.get('match_count',1)>1:raise HTTPException(409,'同じ文に複数の一致箇所があります。原本と照合し、編集欄で修正してください。')
                if s['replacement'] is None:raise HTTPException(409,'修正案がない要確認箇所です。手動編集で確認してください。')
                if fingerprint(d)!=row['source_hash']:raise HTTPException(409,'AI検査後に本文・ルビが変更されています。再検査または手動編集で確認してください。')
                if d['editor_text'][s['start']:s['end']]!=s['original']:raise HTTPException(409,'対象文字列が一致しません。')
                kwargs={'paragraph_id':row['paragraph_id'],'reason':s['reason'],'source':'ai','candidate_id':ident,'engine_id':row['engine_id']}
                if s['target']=='ruby':kwargs.update(ruby_index=s['ruby_index'],base=s['base_after'],reading=s['reading_after']);kind='ruby'
                else:kwargs.update(text=s['replacement'],span_start=s['start'],span_end=s['end'],expected_span=s['original']);kind='text'
                before_revision=value['revision']
                value=editing.commit_edit(con,book_id,req.revision,kind,expected_token=d['token'],**kwargs)
                if value['revision']==before_revision:raise HTTPException(409,'対象は既に修正済みです。')
                command=value['commands'][value['cursor']-1]['id'];projects.invalidate(con,book_id,value)
                con.execute("UPDATE ai_results SET status='approved',command_id=?,updated_at=? WHERE id=?",(command,editing.timestamp(),ident))
                # Disjoint candidates in the same paragraph can safely follow a known approved edit.
                new=editing.paragraph_details(editing.working_model(value),row['paragraph_id'],value['revision']);delta=len(s['replacement'])-len(s['original']);newhash=fingerprint(new)
                for other in con.execute("SELECT id,data FROM ai_results WHERE book_id=? AND paragraph_id=? AND source_hash=? AND command_id IS NULL AND id!=?",(book_id,row['paragraph_id'],row['source_hash'],ident)).fetchall():
                    o=json.loads(other['data'])
                    if o['end']<=s['start']:pass
                    elif o['start']>=s['end']:o['start']+=delta;o['end']+=delta
                    else:continue
                    if new['editor_text'][o['start']:o['end']]!=o['original']:continue
                    con.execute('UPDATE ai_results SET data=?,source_hash=? WHERE id=?',(json.dumps(o,ensure_ascii=False,sort_keys=True),newhash,other['id']))
                from .. import reviews
                index=s.get('ruby_index') if s['target']=='ruby' else next((x['index'] for x in new['sentences'] if x['start']<=s['start']<x['end']),None) if new['unit_mode']=='sentence' else None
                reviews.mark(con,book_id,row['paragraph_id'],'ruby' if s['target']=='ruby' else 'body',index)
                result=snapshot(book_id,value,projects.read(con,book_id),library.info(con,book_id))
            else:
                con.execute('UPDATE ai_results SET status=?,updated_at=? WHERE id=?',('rejected' if req.action=='reject' else 'reviewed' if req.action=='confirm' else 'held',editing.timestamp(),ident));result=None
                if req.action=='confirm':
                    from .. import reviews
                    try:d=editing.paragraph_details(editing.working_model(value),row['paragraph_id'],value['revision'])
                    except ValueError:d=None
                    if d is not None and fingerprint(d)==row['source_hash']:
                        s=json.loads(row['data']);index=s.get('ruby_index') if s['target']=='ruby' else next((x['index'] for x in d['sentences'] if x['start']<=s['start']<x['end']),None) if d['unit_mode']=='sentence' else None
                        reviews.mark(con,book_id,row['paragraph_id'],'ruby' if s['target']=='ruby' else 'body',index)
                        result=snapshot(book_id,value,projects.read(con,book_id),library.info(con,book_id))
            con.execute('INSERT INTO ai_decisions VALUES (?,?,?,?,?)',(str(uuid4()),ident,em.OWNER,req.action,editing.timestamp()))
        return {'book':result}
