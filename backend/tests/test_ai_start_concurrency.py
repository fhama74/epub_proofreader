"""Preparing a large AI job must not reserve the database writer."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from test_editing import session,details,edit,P2
from test_ai import request
from epub_proofreader import app as module
from epub_proofreader.ai import jobs


@pytest.mark.parametrize('concurrent_change',['none','body','engine'])
def test_start_prepares_without_write_lock_and_rechecks_snapshot(session,monkeypatch,concurrent_change):
    c,create=session;root=create();req=request(c,root);ready=Event();release=Event();actual=jobs.prepare
    def slow_prepare(*args):
        value=actual(*args);ready.set();assert release.wait(4);return value
    monkeypatch.setattr(jobs,'prepare',slow_prepare)
    with ThreadPoolExecutor(max_workers=1) as executor:
        response=executor.submit(c.post,root+'/ai/jobs',json=req)
        try:
            assert ready.wait(3)
            # Before this fix BEGIN IMMEDIATE in /ai/jobs held the writer here.
            with sqlite3.connect(module.DATA_DIR/'library.sqlite3',timeout=0) as independent:
                independent.execute('BEGIN IMMEDIATE');independent.rollback()
            if concurrent_change=='body':assert edit(c,root,P2,details(c,root)['editor_text']+'追記。').status_code==200
            if concurrent_change=='engine':
                engine=c.get('/api/ai/engines').json()['engines'][0]
                assert c.put('/api/ai/engines/'+engine['id'],json={**engine,'name':'変更後のエンジン'}).status_code==200
        finally:release.set()
        result=response.result(timeout=5)
    assert result.status_code==(200 if concurrent_change=='none' else 409),result.text
    with module.database() as con:assert con.execute('SELECT COUNT(*) FROM ai_jobs').fetchone()[0]==(1 if concurrent_change=='none' else 0)


def test_start_duplicate_returns_same_job_even_if_text_changed(session):
    c,create=session;root=create();req=request(c,root)
    first=c.post(root+'/ai/jobs',json=req);assert first.status_code==200
    assert edit(c,root,P2,details(c,root)['editor_text']+'変更。').status_code==200
    duplicate=c.post(root+'/ai/jobs',json=req)
    assert duplicate.status_code==200 and duplicate.json()==first.json()


@pytest.mark.parametrize('message,status',[('database is locked',503),('no such column: private content',500)])
def test_database_errors_are_json_without_private_sql_details(session,monkeypatch,message,status):
    c,create=session;root=create();req=request(c,root);ident=c.post(root+'/ai/jobs',json=req).json()['job_id']
    def fail(*args):raise sqlite3.OperationalError(message)
    monkeypatch.setattr(jobs,'control',fail)
    response=c.post(root+f'/ai/jobs/{ident}/pause')
    assert response.status_code==status and response.headers['content-type'].startswith('application/json')
    assert response.json()['detail'] and 'private content' not in response.text
    if status==503:assert response.headers['Retry-After']=='2' and '少し待って' in response.json()['detail']


def test_ai_payload_fingerprint_matches_editor_without_expensive_edit_tokens(session,monkeypatch):
    from epub_proofreader.ai.proofreading import payloads,fingerprint
    c,create=session;root=create();d=details(c,root)
    with module.database() as con:book=module.editing.working_model(module.editing.state(con,root.rsplit('/',1)[1]))
    lean=module.editing.paragraph_details(book,P2,0,include_tokens=False)
    assert 'chapter_token' not in lean and 'token' not in lean
    assert fingerprint(d)==fingerprint(lean)
    assert payloads(book,{P2})[0]['source_hash']==fingerprint(d)
