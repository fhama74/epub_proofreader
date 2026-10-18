import json
import sqlite3
import threading
import time
import pytest
from test_unit_store import client,create,detail,change,structure
from test_editing import P1,P2
from epub_proofreader import app as module,proof_score,maintenance
from epub_proofreader.epub import Book


def score(c,root):return c.get(root).json()['proof_score']


def test_three_character_ai_finding_survives_state_and_approval(client,monkeypatch):
    from test_ai import job,finish,parse_prompt
    from epub_proofreader.ai.providers import PROVIDERS
    from epub_proofreader.ai.providers.base import Reply
    root,b=create(client)
    def generate(cfg,system,prompt):
        p=parse_prompt(prompt)
        return Reply('{"findings":[{"i":0,"o":"天汽だ","r":"天気だ"}]}' if p['query_type']=='body' else '{"suggestions":[]}',1,1)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    finish(job(client,root,paragraph_id=P2))
    findings=client.get(root+'/ai').json()['results']
    assert len(findings)==1 and not findings[0]['stale'] and findings[0]['original']=='天汽だ'
    r=client.post(root+'/ai/results/'+findings[0]['id']+'/decision',json={'action':'approve','revision':0})
    assert r.status_code==200,r.text
    assert '天気だった' in detail(client,root)['editor_text']


def test_cached_score_confirmation_updates_no_recount_and_no_double_count(client,monkeypatch):
    root,b=create(client);assert b['proof_score']['total']==8
    assert b['proof_score']['score']==0
    def forbidden(*a,**kw):raise AssertionError('ordinary confirmation must not recount the book')
    monkeypatch.setattr(proof_score,'rebuild',forbidden)
    d=detail(client,root)
    for _ in range(2):
        r=client.post(root+'/paragraphs/'+P2+'/review',json={'expected_token':d['token'],'compact':True})
        assert r.status_code==200,r.text
        assert r.json()['proof_score']['reviewed']==1
        assert r.json()['proof_score']['score']==round(50/8,1)
    updated=change(client,root,P2,d['editor_text']+'訂正。')
    assert updated['proof_score']['reviewed']==1
    assert score(client,root)['reviewed']==1


def test_score_reset_structure_and_backup(client):
    root,b=create(client);change(client,root,P2,detail(client,root)['editor_text']+'訂正。')
    assert score(client,root)['reviewed']==1
    b=structure(client,root,'split',offset=detail(client,root)['editor_text'].index('。')+1)
    assert b['proof_score']['total']==9 and b['proof_score']['reviewed']==0
    right=b['focus_paragraph_id'];change(client,root,right,detail(client,root,right)['editor_text']+'追記。')
    assert score(client,root)['reviewed']==1
    b=structure(client,root,'merge',pid=right)
    assert b['proof_score']['total']==8 and b['proof_score']['reviewed']==0
    change(client,root,P2,detail(client,root)['editor_text']+'確定。')
    data=client.get(root+'/project/export').content
    r=client.post('/api/projects/import',files={'file':('保存.eproof',data)})
    assert r.status_code==200,r.text
    assert r.json()['proof_score']['reviewed']==1
    assert r.json()['proof_score']['total']==8
    r=client.post(root+'/review/reset',json={'scope':'paragraph','paragraph_id':P2,'target':'body'})
    assert r.status_code==200,r.text
    assert r.json()['proof_score']['reviewed']==0


def test_ai_bonus_requires_successful_whole_book_and_survives_backup(client,monkeypatch):
    from test_ai import job,finish,parse_prompt
    from epub_proofreader.ai.providers import PROVIDERS
    from epub_proofreader.ai.providers.base import Reply
    def generate(cfg,system,prompt):
        p=parse_prompt(prompt)
        return Reply(json.dumps({'paragraph_id':p['paragraph_id'],'findings' if p['query_type']=='body' else 'suggestions':[]}),1,1)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    root,b=create(client)
    ident=job(client,root,'chapter');finish(ident)
    assert not score(client,root)['ai_completed']
    ident=job(client,root,'book');finish(ident)
    s=score(client,root);assert s['ai_completed'] and s['score']==50
    assert client.get(root+'/ai').json()['proof_score']['ai_points']==50
    data=client.get(root+'/project/export').content
    r=client.post('/api/projects/import',files={'file':('AI.eproof',data)})
    assert r.status_code==200,r.text
    assert r.json()['proof_score']['ai_points']==50


def test_failed_whole_book_ai_has_no_bonus_until_retry_succeeds(client,monkeypatch):
    from test_ai import job,finish,parse_prompt
    from epub_proofreader.ai.providers import PROVIDERS
    from epub_proofreader.ai.providers.base import Reply
    root,b=create(client)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',lambda *a:Reply('invalid JSON',1,1))
    ident=job(client,root,'book');finish(ident)
    assert not score(client,root)['ai_completed']
    def generate(cfg,system,prompt):
        p=parse_prompt(prompt);return Reply(json.dumps({'paragraph_id':p['paragraph_id'],'findings' if p['query_type']=='body' else 'suggestions':[]}),1,1)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    assert client.post(root+'/ai/jobs/'+ident+'/retry').status_code==200
    finish(ident)
    assert score(client,root)['ai_points']==50


def test_maintenance_preserves_content_flags_evidence_and_other_projects(client,monkeypatch):
    root,b=create(client);other,_=create(client);change(client,root,P2,detail(client,root)['editor_text']+'確定。')
    # Make obsolete versions and a genuinely inactive unit through real edits.
    structure(client,root,'insert_boundary',text='後で削除する本文。')
    book=client.get(root).json();target=next(p['id'] for c in book['chapters'] for p in c['paragraphs'] if p['text']=='後で削除する本文。')
    structure(client,root,'delete',pid=target)
    bid=b['id']
    with module.database() as con:
        con.execute('INSERT OR REPLACE INTO unit_locks VALUES (?,?,?,?)',(bid,P1,'expired',0))
        con.execute('INSERT OR REPLACE INTO unit_locks VALUES (?,?,?,?)',(bid,P2,'test-browser',time.time()+3600))
        con.execute('INSERT OR IGNORE INTO unit_reviews VALUES (?,?,?,?,?,?)',(bid,P2,1,'body',0,1))
        con.execute('INSERT INTO ai_jobs(id,book_id,owner_id,engine_id,config,scope,status,created_at,request_id) VALUES (?,?,?,?,?,?,?,?,?)',('evidence-job',bid,'local','engine','{}','paragraph','archived','now','evidence-request'))
        con.execute('INSERT INTO ai_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('evidence','evidence-job',bid,'local','engine','model',target,'chapter','{}','source','pending','now','now',None))
        con.execute('INSERT INTO ai_result_units VALUES (?,?,?,?,?)',('evidence',target,1,0,1))
        con.execute('INSERT INTO ai_failures VALUES (?,?,?,?,?,?,?,?,?,?)',('failure','evidence-job','now','[]','body',1,'format','test','full output',None))
        con.execute('INSERT INTO ai_failure_contexts VALUES (?,?)',('failure','{"request":"kept"}'))
        # A free page allocation lets VACUUM reclaim observable storage.
        con.execute('CREATE TABLE scratch(data BLOB)');con.execute('INSERT INTO scratch VALUES (?)',(b'x'*1024*1024,));con.execute('DROP TABLE scratch')
    before=Book(client.get(root+'/export').content).files
    other_before=Book(client.get(other+'/export').content).files
    s=score(client,root)
    from epub_proofreader import project_api
    import uuid
    monkeypatch.setattr(project_api,'epubcheck',lambda data:{'status':'passed'})
    published=client.post(root+'/publish',json={'revision':client.get(root).json()['edit_state']['revision'],'expected_version':0,'request_id':str(uuid.uuid4())})
    assert published.status_code==200,published.text
    release=client.get(root+'/publications/1/epub').content
    r=client.post('/api/storage/compact')
    assert r.status_code==200,r.text
    result=r.json();assert result['compacted'] and result['removed_units']>=1
    assert result['expired_locks']>=1 and result['obsolete_reviews']>=1
    assert result['reclaimed_bytes']>0
    assert Book(client.get(root+'/export').content).files==before
    assert Book(client.get(other+'/export').content).files==other_before
    assert score(client,root)==s
    assert client.get(root+'/publications/1/epub').content==release
    with module.database() as con:
        assert con.execute('SELECT 1 FROM unit_locks WHERE book_id=? AND unit_id=?',(bid,P2)).fetchone()
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert con.execute('SELECT data FROM ai_failure_contexts WHERE failure_id=?',('failure',)).fetchone()[0]=='{"request":"kept"}'
        assert con.execute('SELECT 1 FROM ai_result_units WHERE result_id=?',('evidence',)).fetchone()


def test_maintenance_gate_drains_connections_and_allows_nested_reads(client):
    create(client);entered=threading.Event();finished=threading.Event()
    def clean():
        with maintenance.exclusive():
            entered.set()
            with module.database() as con:assert con.execute('SELECT 1').fetchone()[0]==1
        finished.set()
    with module.database():
        thread=threading.Thread(target=clean);thread.start()
        assert not entered.wait(.05)
        with module.database() as con:assert con.execute('SELECT 1').fetchone()[0]==1
    assert finished.wait(2);thread.join(2)


def test_compaction_failure_reports_partial_success_without_losing_active_data(client,monkeypatch):
    root,b=create(client);before=Book(client.get(root+'/export').content).files
    original=maintenance.compact
    class Connection:
        def __init__(self,con):self.con=con
        def execute(self,sql,*a):
            if sql=='VACUUM':raise sqlite3.OperationalError('database full')
            return self.con.execute(sql,*a)
        def __getattr__(self,key):return getattr(self.con,key)
    monkeypatch.setattr(maintenance,'compact',lambda con:original(Connection(con)))
    r=client.post('/api/storage/compact');assert r.status_code==200,r.text
    assert not r.json()['compacted'] and r.json()['warning']
    assert Book(client.get(root+'/export').content).files==before
