import json,threading,time,os
try:import fcntl
except ImportError:fcntl=None
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from .. import editing
from . import engine_manager as em
from .models import Engine
from .providers import PROVIDERS
from .proofreading import payloads,candidate_key,estimate
from . import queries,batching,prompts

def queries_cost(cfg,query,feedback=''):
    if cfg['provider']=='ollama':return 0
    if cfg['input_price'] is None or cfg['output_price'] is None:return None
    size=len((queries.system(query,cfg.get('_prompt_policy'))+queries.prompt(query)+json.dumps(queries.output_schema(query))+feedback).encode())+1024
    return (size*cfg['input_price']+cfg['max_output_tokens']*cfg['output_price'])/1e6

ACTIVE={'queued','running','pause_requested'}
def prepare(con,book_id,req):
    e=em.engine(con,req.engine_id);e['prompt_policy']=prompts.read(con)['values'];value=editing.state(con,book_id)
    if value['revision']!=req.revision:raise HTTPException(409,'本文が更新されました。対象を確認して開始し直してください。')
    book=editing.working_model(value)
    ids={p['id'] for c in book.chapters if req.scope!='chapter' or c['id']==req.chapter_id for p in c['paragraphs'] if req.scope!='paragraph' or p['id']==req.paragraph_id}
    if not ids:raise HTTPException(422,'校正対象の段落がありません。')
    items=payloads(book,ids)
    return e,items,estimate({**e,'batch_paragraphs':req.batch_paragraphs},items)

def start(con,book_id,req):
    prior=con.execute('SELECT id FROM ai_jobs WHERE book_id=? AND request_id=?',(book_id,req.request_id)).fetchone()
    if prior:return prior[0]
    e,items,quote=prepare(con,book_id,req)
    if e['provider']!='ollama':
        if not req.cloud_confirmed:raise HTTPException(422,'クラウド送信範囲と料金の確認が必要です。')
        if not e['has_api_key']:raise HTTPException(422,'APIキーを登録してください。')
        if req.budget is not None and quote['estimated_cost'] is None:raise HTTPException(422,'上限額を使うには入力・出力の単価を設定してください。')
    if con.execute("SELECT 1 FROM ai_jobs WHERE book_id=? AND status IN ('queued','running','pause_requested','paused','interrupted','budget_paused')",(book_id,)).fetchone():raise HTTPException(409,'この書籍には実行中・一時停止中のジョブがあります。再開または中止してください。')
    ident=str(uuid4());cfg={k:v for k,v in e.items() if k not in {'api_key','has_api_key'}}
    if req.batch_paragraphs>1:cfg['batch_paragraphs']=req.batch_paragraphs
    con.execute('INSERT INTO ai_jobs(id,book_id,owner_id,engine_id,config,scope,status,created_at,request_id,budget) VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,book_id,em.OWNER,e['id'],json.dumps(cfg),req.scope,'queued',editing.timestamp(),req.request_id,req.budget))
    for i,p in enumerate(items):con.execute('INSERT INTO ai_items VALUES (?,?,?,?,?,?,?)',(ident,i,p['paragraph_id'],p['chapter_id'],json.dumps(p,ensure_ascii=False),'pending',None))
    return ident

def control(con,book_id,ident,action):
    row=con.execute('SELECT status FROM ai_jobs WHERE id=? AND book_id=? AND owner_id=?',(ident,book_id,em.OWNER)).fetchone()
    if not row:raise HTTPException(404,'ジョブがありません。')
    status=row[0]
    if action=='pause':new='pause_requested' if status=='running' else 'paused' if status=='queued' else status
    elif action=='cancel':new='cancelled'
    elif action=='resume':
        if status not in {'paused','interrupted','budget_paused'}:raise HTTPException(409,'再開できる状態ではありません。')
        new='queued'
    elif action=='retry':
        if status not in {'completed_with_errors','completed','paused','interrupted'}:raise HTTPException(409,'処理の停止後に再試行してください。')
        con.execute("UPDATE ai_items SET status='pending',error=NULL WHERE job_id=? AND status='failed'",(ident,));new='queued'
    else:raise HTTPException(422,'未対応の操作です。')
    if new=='queued' and con.execute("SELECT 1 FROM ai_jobs WHERE book_id=? AND id!=? AND status IN ('queued','running','pause_requested','paused','interrupted','budget_paused')",(book_id,ident)).fetchone():raise HTTPException(409,'別のジョブが実行中です。先に停止してください。')
    con.execute('UPDATE ai_jobs SET status=?,finished_at=NULL,error=NULL WHERE id=?',(new,ident))

class Worker:
    def __init__(self,database,data_dir):self.database=database;self.data_dir=data_dir;self.stop=threading.Event();self.thread=None;self.lock=None
    def launch(self):
        self.data_dir.mkdir(parents=True,exist_ok=True);self.lock=open(self.data_dir/'ai-worker.lock','a')
        try:
            if fcntl:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            else:
                import msvcrt
                self.lock.seek(0);self.lock.write('0');self.lock.flush();self.lock.seek(0);msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:self.lock.close();self.lock=None;return
        with self.database() as con:
            con.execute("UPDATE ai_jobs SET status='interrupted',error='バックエンド停止を検出しました。保存済み段落から手動で再開できます。' WHERE status IN ('running','queued','pause_requested')")
            con.execute("UPDATE ai_items SET status='pending' WHERE status='running'")
        self.thread=threading.Thread(target=self.loop,daemon=True,name='ai-proofreading');self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)
        # Retain flock until an in-flight HTTP call stops, preventing a second worker.
        if self.lock and (not self.thread or not self.thread.is_alive()):self.lock.close();self.lock=None
    def loop(self):
        while not self.stop.wait(.3):
            try:
                with self.database() as con:
                    con.execute('BEGIN IMMEDIATE')
                    row=con.execute("SELECT id FROM ai_jobs WHERE status IN ('queued','running','pause_requested') ORDER BY created_at LIMIT 1").fetchone()
                    if not row:continue
                    ident=row[0]
                self.step(ident)
            except Exception:
                # Never log keys or provider response bodies. Next pass retries DB contention.
                self.stop.wait(1)
    def unknown_usage(self,ident,cfg):
        with self.database() as con:
            if con.execute('SELECT 1 FROM ai_jobs WHERE id=?',(ident,)).fetchone():con.execute('INSERT INTO ai_usage VALUES (?,?,?,?,?,?,?)',(str(uuid4()),ident,em.OWNER,None,None,0 if cfg['provider']=='ollama' else None,editing.timestamp()))
    def step(self,ident):
        with self.database() as con:
            con.execute('BEGIN IMMEDIATE');con.row_factory=__import__('sqlite3').Row
            job=con.execute('SELECT * FROM ai_jobs WHERE id=?',(ident,)).fetchone()
            if not job or job['status'] not in ACTIVE:return
            if job['status']=='pause_requested':con.execute("UPDATE ai_jobs SET status='paused' WHERE id=?",(ident,));return
            item=con.execute("SELECT * FROM ai_items WHERE job_id=? AND status='pending' ORDER BY ordinal LIMIT 1",(ident,)).fetchone()
            if not item:
                failed=con.execute("SELECT COUNT(*) FROM ai_items WHERE job_id=? AND status='failed'",(ident,)).fetchone()[0]
                con.execute('UPDATE ai_jobs SET status=?,finished_at=? WHERE id=?',('completed_with_errors' if failed else 'completed',editing.timestamp(),ident));return
            raw_cfg=json.loads(job['config']);items=[item];size=len(json.loads(item['payload'])['text'])
            if raw_cfg.get('batch_paragraphs',1)>1:
                pending=con.execute("SELECT * FROM ai_items WHERE job_id=? AND status='pending' AND ordinal>? ORDER BY ordinal LIMIT ?",(ident,item['ordinal'],raw_cfg['batch_paragraphs']-1)).fetchall()
                for other in pending:
                    n=len(json.loads(other['payload'])['text'])
                    if other['chapter_id']!=item['chapter_id'] or other['ordinal']!=items[-1]['ordinal']+1 or size+n>raw_cfg['chunk_chars']:break
                    items.append(other);size+=n
            con.execute("UPDATE ai_jobs SET status='running' WHERE id=?",(ident,))
            con.executemany("UPDATE ai_items SET status='running' WHERE job_id=? AND ordinal=?",[(ident,i['ordinal']) for i in items])
        paragraphs=[json.loads(i['payload']) for i in items];p=paragraphs[0];cfg=Engine(**raw_cfg).model_dump(exclude={'api_key'});cfg['id']=job['engine_id'];cfg['_prompt_policy']=raw_cfg.get('prompt_policy');suggestions=[];unresolved={}
        plans=batching.plans(paragraphs,raw_cfg['batch_paragraphs'],cfg['chunk_chars']) if raw_cfg.get('batch_paragraphs',1)>1 else queries.queries(p,cfg['chunk_chars'])
        try:
            with self.database() as con:cfg['api_key']=em.engine(con,job['engine_id'],True).get('api_key')
            if cfg['provider']!='ollama' and not cfg['api_key']:raise ValueError('APIキーがありません。')
            for query in plans:
                cfg['_response_schema']=queries.output_schema(query)
                feedback='';issues=[]
                for attempt in range(3):
                    with self.database() as con:
                        current=con.execute('SELECT status FROM ai_jobs WHERE id=?',(ident,)).fetchone()
                        if not current or current[0]=='cancelled':return
                        spent=con.execute('SELECT COALESCE(SUM(cost),0) FROM ai_usage WHERE job_id=?',(ident,)).fetchone()[0]
                        unknown=con.execute('SELECT COUNT(*) FROM ai_usage WHERE job_id=? AND cost IS NULL',(ident,)).fetchone()[0]
                    bound=queries_cost(cfg,query,feedback)
                    if job['budget'] is not None and cfg['provider']!='ollama' and (unknown or spent+(bound or 0)>job['budget']):
                        with self.database() as con:
                            con.execute("UPDATE ai_jobs SET status='budget_paused',error='設定した利用上限額に達する可能性があるため停止しました。' WHERE id=?",(ident,));con.executemany("UPDATE ai_items SET status='pending' WHERE job_id=? AND ordinal=?",[(ident,i['ordinal']) for i in items])
                        return
                    try:
                        reply=PROVIDERS[cfg['provider']].generate(cfg,queries.system(query,cfg.get('_prompt_policy')),queries.prompt(query)+('\n前回の検証結果：'+feedback+'\n原文から正確に照合できる候補のみ返してください。修正案が不明な時はnullとし、変更のない箇所は除外してください。' if attempt else ''))
                    except (KeyError,TypeError,AttributeError):
                        self.unknown_usage(ident,cfg)
                        if attempt<2:continue
                        raise ValueError('AIの応答形式が不正です（3回試行）。') from None
                    except ValueError as exc:
                        self.unknown_usage(ident,cfg)
                        if '不正なJSON' in str(exc) and attempt<2:continue
                        raise
                    cost=0 if cfg['provider']=='ollama' else (reply.input_tokens*cfg['input_price']+reply.output_tokens*cfg['output_price'])/1e6 if None not in (reply.input_tokens,reply.output_tokens,cfg['input_price'],cfg['output_price']) else None
                    with self.database() as con:
                        if con.execute('SELECT 1 FROM ai_jobs WHERE id=?',(ident,)).fetchone():con.execute('INSERT INTO ai_usage VALUES (?,?,?,?,?,?,?)',(str(uuid4()),ident,em.OWNER,reply.input_tokens,reply.output_tokens,cost,editing.timestamp()))
                    try:
                        accepted,issues=queries.assess(reply.text,p,query)
                        suggestions.extend(accepted)
                    except ValueError as exc:issues={pid:[str(exc)] for pid in [a['paragraph_id'] for a,_ in query['_members']]} if query.get('_batch') else [str(exc)]
                    if not issues:break
                    scoped=issues if isinstance(issues,dict) else {p['paragraph_id']:issues}
                    feedback=' / '.join(f'{pid}: {message}' for pid,messages in scoped.items() for message in messages)[:1800]
                    if attempt==2:
                        for pid,messages in scoped.items():unresolved.setdefault(pid,[]).extend(messages)
            with self.database() as con:
                con.execute('BEGIN IMMEDIATE')
                row=con.execute('SELECT status FROM ai_jobs WHERE id=?',(ident,)).fetchone()
                if not row or row[0]=='cancelled':return
                now=editing.timestamp()
                failed=any(unresolved.values())
                for item,p in zip(items,paragraphs):
                    seen={candidate_key(json.loads(r[0])) for r in con.execute('SELECT data FROM ai_results WHERE job_id=? AND paragraph_id=?',(ident,p['paragraph_id']))}
                    for suggestion in suggestions:
                        if suggestion.get('_paragraph_id',paragraphs[0]['paragraph_id'])!=p['paragraph_id']:continue
                        d={k:v for k,v in suggestion.items() if k!='_paragraph_id'};key=candidate_key(d)
                        if key in seen:continue
                        seen.add(key)
                        con.execute('INSERT OR IGNORE INTO ai_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(str(uuid4()),ident,job['book_id'],em.OWNER,job['engine_id'],cfg['model'],p['paragraph_id'],p['chapter_id'],json.dumps(d,ensure_ascii=False,sort_keys=True),p['source_hash'],'pending',now,now,None))
                    issues=unresolved.get(p['paragraph_id'],[])
                    message=('一部の候補を保存せず、要再検査にしました（3回試行）。'+' / '.join(issues[:5]))[:1800] if issues else None
                    con.execute('UPDATE ai_items SET status=?,error=? WHERE job_id=? AND ordinal=?',('failed' if issues else 'done',message,ident,item['ordinal']))
                latest=con.execute("SELECT error FROM ai_items WHERE job_id=? AND status='failed' ORDER BY ordinal DESC LIMIT 1",(ident,)).fetchone()
                con.execute('UPDATE ai_jobs SET error=? WHERE id=?',(latest[0] if latest else None,ident))
                if failed and con.execute("SELECT COUNT(*) FROM ai_items WHERE job_id=? AND status='failed'",(ident,)).fetchone()[0]>=5:con.execute("UPDATE ai_jobs SET status='paused' WHERE id=?",(ident,))
                if row[0]=='pause_requested':con.execute("UPDATE ai_jobs SET status='paused' WHERE id=?",(ident,))
        except Exception as exc:
            # Only curated messages; provider SDK/internal exceptions may contain authentication material.
            message=str(exc) if type(exc) is ValueError else 'AI処理に失敗しました。接続・モデル・暗号化キーを確認してください。'
            with self.database() as con:
                row=con.execute('SELECT status FROM ai_jobs WHERE id=?',(ident,)).fetchone()
                if not row or row[0]=='cancelled':return
                con.executemany("UPDATE ai_items SET status='failed',error=? WHERE job_id=? AND ordinal=?",[(message,ident,i['ordinal']) for i in items])
                con.execute('UPDATE ai_jobs SET error=? WHERE id=?',(message,ident))
                count=con.execute("SELECT COUNT(*) FROM ai_items WHERE job_id=? AND status='failed'",(ident,)).fetchone()[0]
                if count>=5:con.execute("UPDATE ai_jobs SET status='paused' WHERE id=? AND status!='cancelled'",(ident,))
