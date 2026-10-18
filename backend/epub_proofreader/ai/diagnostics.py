"""On-demand local evidence; never store request headers or credentials."""
import json
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


def record(database, job_id, paragraphs, query_type, attempt, kind, message, output=None, exception_type=None):
    if output is not None and not isinstance(output,str):output=json.dumps(output,ensure_ascii=False)
    with database() as con:
        if not con.execute('SELECT 1 FROM ai_jobs WHERE id=?',(job_id,)).fetchone():return
        con.execute('INSERT INTO ai_failures VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (str(uuid4()),job_id,timestamp(),json.dumps(list(dict.fromkeys(paragraphs))),query_type,attempt,kind,message,output,exception_type))


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
    return {'output':row[0]}
