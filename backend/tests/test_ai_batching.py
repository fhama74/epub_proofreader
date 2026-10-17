import json
import uuid
import pytest
from cryptography.fernet import Fernet
from test_editing import session,details,edit,P2
from test_ai import engines,state,run,finish
from epub_proofreader import app as module
from epub_proofreader.ai import batching,jobs
from epub_proofreader.ai.providers import PROVIDERS
from epub_proofreader.ai.providers.base import Reply


def start(c,root,**patch):
    b=c.get(root).json()
    request={'engine_id':engines(c)[0]['id'],'scope':'chapter','chapter_id':b['chapters'][0]['id'],'revision':b['edit_state']['revision'],'request_id':str(uuid.uuid4()),'batch_paragraphs':4,'skip_confirmed':False,**patch}
    r=c.post(root+'/ai/jobs',json=request);assert r.status_code==200,r.text
    return r.json()['job_id']


def response(prompt):
    q=json.loads(prompt.split('\n前回')[0]);findings=[]
    if q['query_type']=='body':
        for p in q['paragraphs']:
            for unit_index,u in enumerate(p['units']):
                if '天汽' in u['text']:findings.append({'paragraph_id':p['paragraph_id'],'unit_id':unit_index,'start':u['text'].index('汽'),'original':'汽','replacement':'気','reason':'OCR誤認識','category':'kanji','confidence':.8})
    return q,findings


def mock(monkeypatch,transform=None):
    calls=[]
    def generate(cfg,system,prompt):
        q,findings=response(prompt);calls.append(q)
        if transform:findings=transform(q,findings)
        return Reply(json.dumps({'findings':findings}),100,50)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    return calls


def test_three_paragraphs_use_two_calls_and_save_only_findings(session,monkeypatch):
    c,create=session;root=create();calls=mock(monkeypatch);before=c.get(root+'/export').content
    ident=start(c,root);finish(ident)
    s=state(c,root);assert [q['query_type'] for q in calls]==['body','ruby'];assert len(calls[0]['paragraphs'])==3
    assert s['jobs'][0]['done']==3 and s['jobs'][0]['failed']==0
    assert len(s['results'])==1 and s['results'][0]['paragraph_id']==P2
    assert c.get(root+'/export').content==before
    assert s['jobs'][0]['input_tokens']==200 and s['jobs'][0]['output_tokens']==100


def test_estimate_matches_batch_calls_and_old_jobs_keep_single_protocol(session,monkeypatch):
    c,create=session;root=create();b=c.get(root).json();body={'engine_id':engines(c)[0]['id'],'scope':'chapter','chapter_id':b['chapters'][0]['id'],'revision':0,'request_id':str(uuid.uuid4())}
    single=c.post(root+'/ai/quote',json=body).json();batch=c.post(root+'/ai/quote',json={**body,'batch_paragraphs':4}).json()
    assert batch['calls']==2 and batch['calls']<single['calls'];assert batch['input_token_bound']<single['input_token_bound']
    ident=c.post(root+'/ai/jobs',json=body).json()['job_id']
    with module.database() as con:assert 'batch_paragraphs' not in json.loads(con.execute('SELECT config FROM ai_jobs WHERE id=?',(ident,)).fetchone()[0])


def test_batches_never_cross_chapters_or_character_limits():
    items=[{'paragraph_id':str(i),'chapter_id':chapter,'text':'文'*n,'rubies':[],'previous':'','next':''} for i,(chapter,n) in enumerate([('a',100),('a',100),('a',300),('b',100),('b',100)])]
    assert [[p['paragraph_id'] for p in g] for g in batching.groups(items,4,250)]==[['0','1'],['2'],['3','4']]
    plans=list(batching.plans(items,4,250));assert all(len({p['paragraph_id'] for p,_ in q['_members']})==len(q['_members']) for q in plans)
    assert all(len({p['chapter_id'] for p,_ in q['_members']})==1 for q in plans)


def test_ruby_queries_are_bounded_and_only_accept_rubies_actually_sent():
    p={'paragraph_id':'p','chapter_id':'c','text':'漢'*85,'rubies':[{'index':i,'start':i,'end':i+1,'base':'漢','readings':['かん'],'editable':True} for i in range(85)],'previous':'','next':''}
    plans=[q for q in batching.plans([p],4,1200) if q['query_type']=='ruby']
    assert [len(q['paragraphs'][0]['rubies']) for q in plans]==[40,40,5]
    reply=json.dumps({'findings':[{'paragraph_id':'p','ruby_index':84,'base_after':None,'reading_after':'かんじ','reason':'読みの誤認識','confidence':.8}]})
    accepted,issues=batching.assess(reply,plans[0]);assert not accepted and issues['p']
    accepted,issues=batching.assess(reply,plans[-1]);assert len(accepted)==1 and not issues


def test_partial_bad_finding_only_fails_its_paragraph_and_deduplicates_safe_siblings(session,monkeypatch):
    c,create=session;root=create()
    def transform(q,findings):
        return findings+[{'paragraph_id':q['paragraphs'][0]['paragraph_id'],'unit_id':999,'original':None,'replacement':None,'reason':'要確認','category':'unnatural','confidence':.5}] if q['query_type']=='body' else findings
    calls=mock(monkeypatch,transform);ident=start(c,root);finish(ident);s=state(c,root)
    assert s['jobs'][0]['done']==2 and s['jobs'][0]['failed']==1 and len(s['results'])==1
    assert [q['query_type'] for q in calls]==['body','body','body','ruby']


def test_unknown_paragraph_ids_are_not_saved_or_silently_ignored(session,monkeypatch):
    c,create=session;root=create()
    calls=mock(monkeypatch,lambda q,f:[{**f[0],'paragraph_id':'foreign'}] if f else f)
    ident=start(c,root);finish(ident);s=state(c,root)
    assert s['jobs'][0]['failed']==3 and not s['results']
    assert len(calls)==4


def test_pause_finishes_claimed_batch_and_cancel_discards_uncommitted_findings(session,monkeypatch):
    c,create=session;root=create();current={};calls=[]
    def generate(cfg,system,prompt):
        q,findings=response(prompt);calls.append(q)
        c.post(root+f"/ai/jobs/{current['id']}/pause")
        return Reply(json.dumps({'findings':findings}),10,5)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate);current['id']=start(c,root);run(current['id']);s=state(c,root)
    assert s['jobs'][0]['status']=='paused' and s['jobs'][0]['done']==3 and len(s['results'])==1
    c.post(root+f"/ai/jobs/{current['id']}/cancel")
    def cancel(cfg,system,prompt):
        _,findings=response(prompt);c.post(root+f"/ai/jobs/{current['id']}/cancel")
        return Reply(json.dumps({'findings':findings}),10,5)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',cancel);current['id']=start(c,root);run(current['id']);s=state(c,root)
    assert s['jobs'][0]['status']=='cancelled' and not [r for r in s['results'] if r['job_id']==current['id']]


def test_budget_mid_batch_restores_all_pending_and_counts_paid_call(session,monkeypatch):
    c,create=session;root=create();monkeypatch.setenv('AI_SECRET_KEY',Fernet.generate_key().decode())
    e=engines(c)[0];r=c.post('/api/ai/engines',json={**e,'provider':'openai','url':'https://api.openai.com','api_key':'mock','input_price':1,'output_price':1});assert r.status_code==200
    cloud=r.json();calls=[]
    def generate(cfg,system,prompt):
        q,f=response(prompt);calls.append(q);return Reply(json.dumps({'findings':f}),20000,1000)
    monkeypatch.setattr(PROVIDERS['openai'],'generate',generate)
    ident=start(c,root,engine_id=cloud['id'],cloud_confirmed=True,budget=.02);run(ident);s=state(c,root)
    assert len(calls)==1 and s['jobs'][0]['status']=='budget_paused' and s['jobs'][0]['done']==0
    assert s['jobs'][0]['cost']==pytest.approx(.021) and not s['results']
    c.post(root+f'/ai/jobs/{ident}/resume',json={'budget':.2});finish(ident);s=state(c,root)
    assert s['jobs'][0]['done']==3 and len(s['results'])==1 and s['jobs'][0]['cost']==pytest.approx(.063)


def test_edit_during_batch_keeps_original_hash_and_marks_result_stale(session,monkeypatch):
    c,create=session;root=create();edited=[]
    def transform(q,f):
        if not edited:edit(c,root,P2,details(c,root)['editor_text']+'追記');edited.append(True)
        return f
    mock(monkeypatch,transform);ident=start(c,root);finish(ident)
    assert state(c,root)['results'][0]['stale']
