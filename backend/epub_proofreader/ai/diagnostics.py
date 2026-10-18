"""On-demand local evidence; never store request headers or credentials."""
import json
import copy
import sqlite3
from uuid import uuid4
from fastapi import HTTPException
from ..editing import timestamp
from .engine_manager import OWNER


def category(message, fallback='processing'):
    if '接続エラー' in message or 'AIへ接続できません' in message:return 'connection'
    if 'AIから応答がありません' in message:return 'timeout'
    if 'JSON' in message or '応答形式' in message:return 'format'
    if 'HTTP ' in message:return 'http'
    return fallback


def current(con,book_id,paragraphs):
    from .. import editing,unit_store
    from .proofreading import fingerprint
    try:
        if unit_store.enabled(con,book_id):
            revision=con.execute('SELECT revision FROM unit_books WHERE book_id=?',(book_id,)).fetchone()[0];items=[]
            for pid in paragraphs:
                try:
                    d=unit_store.direct_details(con,book_id,pid)
                    items.append(dict(paragraph_id=pid,unit_version=d['unit_version'],text=d['editor_text'],rubies=d['rubies'],source_hash=fingerprint(d)))
                except ValueError:items.append(dict(paragraph_id=pid,missing=True))
            return dict(revision=revision,paragraphs=items)
        value=editing.state(con,book_id);book=editing.working_model(value);items=[]
        for pid in paragraphs:
            try:
                d=editing.paragraph_details(book,pid,value['revision'],include_tokens=False)
                items.append(dict(paragraph_id=pid,text=d['editor_text'],rubies=d['rubies'],source_hash=fingerprint(d)))
            except ValueError:items.append(dict(paragraph_id=pid,missing=True))
        return dict(revision=value['revision'],paragraphs=items)
    except Exception as exc:return dict(unavailable=type(exc).__name__)


def units(query,p):
    if query.get('query_type')!='body':return []
    from .body import slots
    return [dict(i=i,paragraph_id=member['paragraph_id'],start=part['_source']['offset']+u['start'],
                 end=part['_source']['offset']+u['end'],text=u['text']) for i,(member,part,u) in enumerate(slots(query,p))]


def capture(database,book_id,query,p,engine,system,prompt):
    members=query['_members'] if query.get('_batch') else [(p,query)]
    paragraphs=[dict(paragraph_id=m['paragraph_id'],text=m['text'],rubies=m['rubies'],source_hash=m['source_hash'],**({'unit_version':m['unit_version']} if 'unit_version' in m else {})) for m,_ in members]
    with database() as con:latest=current(con,book_id,[m['paragraph_id'] for m in paragraphs])
    # A new ID per actual provider call; the same attempt's request and response
    # share this object. Never copy the engine config (it contains the API key).
    return copy.deepcopy(dict(request_id=str(uuid4()),sent_at=timestamp(),provider=engine['provider'],model=engine['model'],
                              request=dict(system=system,prompt=prompt,response_schema=engine.get('_response_schema')),
                              sent_units=units(query,p),validation_paragraphs=paragraphs,current_before_send=latest))


def comparisons(output,context):
    try:findings=json.loads(output).get('findings',[])
    except (ValueError,TypeError,AttributeError):return []
    table={u['i']:u for u in context.get('validation_units',[])};result=[]
    for finding in findings if isinstance(findings,list) else []:
        if not isinstance(finding,dict):continue
        ident=finding.get('i');original=finding.get('o')
        if type(ident) is not int or not isinstance(original,str):continue
        unit=table.get(ident)
        result.append(dict(i=ident,o=original,assigned_unit=unit,
                           original_in_assigned_unit=bool(unit and original and original in unit['text']),
                           other_matching_units=[u['i'] for u in table.values() if u['i']!=ident and original and original in u['text']]))
    return result


def record(database, job_id, paragraphs, query_type, attempt, kind, message, output=None, exception_type=None,context=None):
    if output is not None and not isinstance(output,str):output=json.dumps(output,ensure_ascii=False)
    with database() as con:
        if not con.execute('SELECT 1 FROM ai_jobs WHERE id=?',(job_id,)).fetchone():return
        ident=str(uuid4())
        con.execute('INSERT INTO ai_failures VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (ident,job_id,timestamp(),json.dumps(list(dict.fromkeys(paragraphs))),query_type,attempt,kind,message,output,exception_type))
        if context is not None:
            context=copy.deepcopy(context)
            row=con.execute('SELECT book_id FROM ai_jobs WHERE id=?',(job_id,)).fetchone()
            context['current_at_error']=current(con,row[0],[p['paragraph_id'] for p in context['validation_paragraphs']])
            context['recorded_at']=timestamp()
            context['unit_mapping_unchanged']=context.get('sent_units')==context['validation_units'] if 'validation_units' in context and query_type=='body' else None
            context['findings_comparison']=comparisons(output,context)
            con.execute('INSERT INTO ai_failure_contexts VALUES (?,?)',(ident,json.dumps(context,ensure_ascii=False)))


def listing(con, book_id, job_id, offset=0):
    check(con,book_id,job_id)
    con.row_factory=sqlite3.Row
    rows=con.execute('SELECT id,created_at,paragraph_ids,query_type,attempt,kind,message,output IS NOT NULL AS has_output,exception_type FROM ai_failures WHERE job_id=? ORDER BY rowid DESC LIMIT 50 OFFSET ?',(job_id,offset)).fetchall()
    entries=[{**dict(r),'paragraph_ids':json.loads(r['paragraph_ids'])} for r in rows]
    total=con.execute('SELECT COUNT(*) FROM ai_failures WHERE job_id=?',(job_id,)).fetchone()[0]
    failed=[dict(r) for r in con.execute("SELECT paragraph_id,error FROM ai_items WHERE job_id=? AND status='failed' ORDER BY ordinal",(job_id,))]
    stop=con.execute('SELECT status,error FROM ai_jobs WHERE id=?',(job_id,)).fetchone()
    streak=con.execute('SELECT failures,stop_reason FROM ai_streaks WHERE job_id=?',(job_id,)).fetchone()
    return dict(entries=entries,total=total,offset=offset,failed_paragraphs=failed,status=stop['status'],
                message=stop['error'],consecutive_failures=streak['failures'] if streak else 0,
                stop_reason=streak['stop_reason'] if streak else None)


def check(con,book_id,job_id):
    if not con.execute('SELECT 1 FROM ai_jobs WHERE id=? AND book_id=? AND owner_id=?',(job_id,book_id,OWNER)).fetchone():
        raise HTTPException(404,'ジョブがありません。')


def stopped(con,job_id,reason):
    con.execute('INSERT INTO ai_streaks(job_id,failures,stop_reason) VALUES (?,0,?) ON CONFLICT(job_id) DO UPDATE SET stop_reason=excluded.stop_reason',(job_id,reason))
    con.execute('INSERT INTO ai_failures VALUES (?,?,?,?,?,?,?,?,?,?)',
                (str(uuid4()),job_id,timestamp(),'[]',None,None,'stop',reason,None,None))


def output(con,book_id,job_id,entry_id):
    check(con,book_id,job_id)
    row=con.execute('SELECT output FROM ai_failures WHERE id=? AND job_id=?',(entry_id,job_id)).fetchone()
    if not row:raise HTTPException(404,'エラー記録がありません。')
    context=con.execute('SELECT data FROM ai_failure_contexts WHERE failure_id=?',(entry_id,)).fetchone()
    return {'output':row[0],'context':json.loads(context[0]) if context else None}
