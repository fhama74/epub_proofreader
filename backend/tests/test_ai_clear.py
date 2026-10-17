import pytest
from test_editing import session,details
from test_ai import mock_ai,job,finish,state
from epub_proofreader import app as module


def test_clear_is_reversible_and_keeps_approved_edits_and_usage(session,mock_ai):
    c,create=session;root=create();ident=job(c,root);finish(ident)
    before=state(c,root);candidate=before['results'][0]
    assert c.post(root+f"/ai/results/{candidate['id']}/decision",json={'action':'approve','revision':0}).status_code==200
    edited=details(c,root)
    for _ in range(2):assert c.post(root+'/ai/results/clear').status_code==200
    hidden=state(c,root);assert hidden['results']==[] and hidden['cleared_count']==1
    assert hidden['jobs'][0]['candidates']==0 and hidden['jobs'][0]['unreviewed']==0
    assert hidden['jobs'][0]['input_tokens']==before['jobs'][0]['input_tokens']
    assert details(c,root)==edited
    assert c.post(root+f"/ai/results/{candidate['id']}/decision",json={'action':'hold','revision':1}).status_code==404
    assert c.post(root+'/ai/results/restore').status_code==200
    restored=state(c,root);assert restored['cleared_count']==0 and restored['results'][0]['status']=='approved'
    assert details(c,root)==edited


@pytest.mark.parametrize('status',['queued','running','pause_requested'])
def test_clear_refuses_active_jobs_without_hiding_existing_results(session,mock_ai,status):
    c,create=session;root=create();ident=job(c,root);finish(ident)
    with module.database() as con:con.execute('UPDATE ai_jobs SET status=? WHERE id=?',(status,ident))
    assert c.post(root+'/ai/results/clear').status_code==409
    assert len(state(c,root)['results'])==1


def test_clear_is_project_scoped_and_preserved_in_portable_backup(session,mock_ai):
    c,create=session;root=create();other=create()
    finish(job(c,root));finish(job(c,other))
    assert c.post(root+'/ai/results/clear').status_code==200
    assert len(state(c,other)['results'])==1
    archive=c.get(root+'/project/export').content
    r=c.post('/api/projects/import',files={'file':('cleared.eproof',archive)});assert r.status_code==200,r.text
    imported='/api/books/'+r.json()['id']
    assert state(c,imported)['results']==[] and state(c,imported)['cleared_count']==1
    assert c.post(imported+'/ai/results/restore').status_code==200
    assert len(state(c,imported)['results'])==1
    assert state(c,root)['cleared_count']==1


def test_new_results_are_visible_after_clear_and_paused_work_can_be_cleared(session,mock_ai):
    c,create=session;root=create();first=job(c,root);finish(first)
    with module.database() as con:con.execute("UPDATE ai_jobs SET status='paused' WHERE id=?",(first,))
    assert c.post(root+'/ai/results/clear').status_code==200
    assert state(c,root)['jobs'][0]['status']=='paused'
    c.post(root+f'/ai/jobs/{first}/cancel')
    finish(job(c,root));s=state(c,root)
    assert len(s['results'])==1 and s['cleared_count']==1
    c.post(root+'/ai/results/restore');assert len(state(c,root)['results'])==2
