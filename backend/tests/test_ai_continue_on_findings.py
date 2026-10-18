"""Malformed findings do not stop a book scan or count as service failures."""
import json
import pytest
from test_editing import session
from test_epub import changed
from test_ai import job,finish,state,run
from epub_proofreader import app as module
from epub_proofreader.ai import jobs
from epub_proofreader.ai.providers import PROVIDERS
from epub_proofreader.ai.providers.base import Reply


def source(count):
    html='<html xmlns="http://www.w3.org/1999/xhtml"><head><title>検査</title></head><body>'+''.join(f'<p>文章{i}を確認します。</p>' for i in range(count))+'</body></html>'
    return changed({'EPUB/chapter1.xhtml':html.encode()})


@pytest.mark.parametrize('batch',[1,4])
def test_more_than_five_bad_paragraphs_continue_keep_good_siblings_and_finish(session,monkeypatch,batch):
    c,create=session;root=create(source(9));calls=[]
    def generate(cfg,system,prompt):
        q=json.loads(prompt.split('\n前回')[0]);calls.append(q)
        if batch>1:
            findings=[finding for p in q['paragraphs'] for finding in [
                {'paragraph_id':p['paragraph_id'],'start':0,'original':'文','replacement':None},
                {'paragraph_id':p['paragraph_id'],'start':0,'original':p['units'][0]['text'],'replacement':None}]]
            reply={'findings':findings}
        else:
            reply={'paragraph_id':q['paragraph_id'],'findings':[
                {'start':0,'original':'文','replacement':None},
                {'start':0,'original':q['units'][0]['text'],'replacement':None}]}
        return Reply(json.dumps(reply),10,5)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    ident=job(c,root,'chapter',batch_paragraphs=batch);finish(ident)
    result=state(c,root);j=result['jobs'][0]
    assert j['status']=='completed_with_errors' and j['failed']==j['total']==9
    assert len(result['results'])==9 and all(r['original']=='文' for r in result['results'])
    assert len(calls)==(9 if batch==4 else 27)
    assert all('最大3文字' in row['error'] for row in j['errors'])
    # The retained failures can still be explicitly retried, without resending
    # successfully saved candidates twice within the same job.
    assert c.post(root+f'/ai/jobs/{ident}/retry').status_code==200
    finish(ident)
    assert state(c,root)['jobs'][0]['status']=='completed_with_errors'
    assert len(state(c,root)['results'])==9


def test_format_errors_do_not_count_toward_service_failure_stop(session,monkeypatch):
    c,create=session;root=create(source(12));ident=job(c,root,'chapter')
    with module.database() as con:
        con.execute("UPDATE ai_items SET status='failed',error=? WHERE job_id=? AND ordinal<6",(jobs.FORMAT_ERROR_PREFIX+'（3回試行）。原文が長すぎます。',ident))
    def fail(*args):raise ValueError('接続エラー：AIサービスに接続できません。')
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',fail)
    run(ident);j=state(c,root)['jobs'][0]
    assert j['status']=='running' and j['failed']==7
    for _ in range(4):run(ident)
    j=state(c,root)['jobs'][0]
    assert j['status']=='paused' and j['failed']==11
    # One pending paragraph remains because actual service failures still stop.
    with module.database() as con:
        assert con.execute("SELECT COUNT(*) FROM ai_items WHERE job_id=? AND status='pending'",(ident,)).fetchone()[0]==1
