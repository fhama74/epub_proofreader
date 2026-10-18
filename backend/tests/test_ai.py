import json,uuid,pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from epub_proofreader import app as module
from epub_proofreader.ai import jobs
from epub_proofreader.ai.providers import PROVIDERS
from epub_proofreader.ai.providers.base import Reply
from epub_proofreader.ai.proofreading import chunks,validated
from test_editing import session,details,edit,P2

def parse_prompt(prompt):
    d=json.loads(prompt.split('\n前回')[0])
    d.setdefault('previous','');d.setdefault('next','')
    if 'units' in d:d['target']=''.join(u['text'] for u in d['units'])
    elif 'context' in d:d['target']=d['context']
    return d

def hit(p,original='汽',replacement='気',**patch):
    if p.get('units') and 'i' in p['units'][0]:
        unit=next(u for u in p['units'] if original in u['text'])
        return {'i':unit['i'],'o':original,'r':replacement,**patch}
    return {'start':p['units'][0]['start']+p['target'].index(original),'original':original,'replacement':replacement,**patch}

def engines(client):return client.get('/api/ai/engines').json()['engines']
def request(client,root,scope='paragraph',**patch):
    b=client.get(root).json();return {'engine_id':engines(client)[0]['id'],'scope':scope,'paragraph_id':P2,'chapter_id':b['chapters'][0]['id'],'request_id':str(uuid.uuid4()),'revision':b['edit_state']['revision'],'skip_confirmed':False,**patch}
def job(client,root,scope='paragraph',**patch):
    body=request(client,root,scope,**patch);r=client.post(root+'/ai/jobs',json=body);assert r.status_code==200,r.text;return r.json()['job_id']
def state(client,root):
    r=client.get(root+'/ai');assert r.status_code==200,r.text;return r.json()
def run(ident):module.app.state.ai_worker.step(ident)
def finish(ident,steps=20):
    for _ in range(steps):run(ident)
def suggestion(original='天汽',replacement='天気',**patch):return {'target':'text','start':None,'end':None,'original':original,'replacement':replacement,'reason':'OCR誤認識','category':'kanji','confidence':.85,'ruby_index':None,'base_after':None,'reading_after':None,**patch}
@pytest.fixture
def mock_ai(monkeypatch):
    calls=[]
    def gen(e,system,prompt):
        p=parse_prompt(prompt);calls.append(p)
        return Reply(json.dumps({'paragraph_id':p['paragraph_id'],('findings' if p['query_type']=='body' else 'suggestions'):[hit(p)] if p['query_type']=='body' and '天汽' in p['target'] else []},ensure_ascii=False),100,50)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',gen)
    monkeypatch.setattr(PROVIDERS['ollama'],'models',lambda e:['qwen3:14b','qwen3:30b'])
    return calls

def test_engine_crud_default_switch_models(session,mock_ai):
    c,create=session;create();e=engines(c)[0];e.update(name='別モデル',model='qwen3:30b',is_default=True)
    r=c.post('/api/ai/engines',json=e);assert r.status_code==200,r.text
    ident=r.json()['id'];assert ident!=e['id'];assert sum(x['is_default'] for x in engines(c))==1
    assert c.post(f'/api/ai/engines/{ident}/test').json()['models']==['qwen3:14b','qwen3:30b']
    e.update(name='変更');assert c.put(f'/api/ai/engines/{ident}',json=e).json()['name']=='変更'
    assert c.delete(f'/api/ai/engines/{ident}').status_code==200

def test_ssrf_and_cloud_origins(session):
    c,create=session;create();e=engines(c)[0]
    for url in ['http://169.254.169.254','http://localhost:11434/secret','http://user:pass@localhost:11434','http://localhost:11434?x=1']:
        assert c.post('/api/ai/engines',json={**e,'url':url}).status_code==422
    assert c.post('/api/ai/engines',json={**e,'provider':'openai'}).status_code==422

def test_encrypted_api_key_never_returned(session,monkeypatch):
    c,create=session;create();monkeypatch.setenv('AI_SECRET_KEY',Fernet.generate_key().decode());e=engines(c)[0]
    r=c.post('/api/ai/engines',json={**e,'provider':'openai','url':'https://api.openai.com','api_key':'mock-secret'});assert r.status_code==200,r.text
    assert 'mock-secret' not in r.text and 'api_key' not in r.json()
    with module.database() as con:
        encrypted=con.execute('SELECT key_cipher FROM ai_engines WHERE id=?',(r.json()['id'],)).fetchone()[0];assert 'mock-secret' not in encrypted
    assert 'mock-secret' not in c.get('/api/ai/engines').text

def test_key_requires_separate_master_secret(session,monkeypatch):
    c,create=session;create();monkeypatch.delenv('AI_SECRET_KEY',raising=False);monkeypatch.delenv('AI_SECRET_KEY_FILE',raising=False)
    from epub_proofreader.ai import engine_manager
    monkeypatch.setattr(engine_manager,'DEFAULT_SECRET_FILE',engine_manager.DEFAULT_SECRET_FILE.parent/'missing-test-key')
    e=engines(c)[0];assert c.post('/api/ai/engines',json={**e,'api_key':'secret'}).status_code==503

@pytest.mark.parametrize('scope,total',[('paragraph',1),('chapter',3),('book',6)])
def test_scopes_background_results_and_no_automatic_edit(session,mock_ai,scope,total):
    c,create=session;root=create();assert state(c,root)=={'jobs':[],'results':[],'cleared_count':0};before=c.get(root+'/export').content
    ident=job(c,root,scope);finish(ident)
    s=state(c,root);j=s['jobs'][0];assert j['status']=='completed';assert j['total']==j['done']==total
    assert len(s['results'])==1 and c.get(root+'/export').content==before
    assert mock_ai[0]['paragraph_id'] and 'previous' in mock_ai[0] and 'next' in mock_ai[0]

def test_start_idempotence_active_job_and_reexecute_keep_results(session,mock_ai):
    c,create=session;root=create();body=request(c,root);r=c.post(root+'/ai/jobs',json=body).json();assert c.post(root+'/ai/jobs',json=body).json()==r
    assert c.post(root+'/ai/jobs',json=request(c,root)).status_code==409
    finish(r['job_id']);ident=job(c,root);finish(ident);assert len(state(c,root)['results'])==1
    assert state(c,root)['cleared_count']==1

def test_approve_history_undo_redo_and_original(session,mock_ai):
    c,create=session;root=create();original=c.get(root+'/original').content;ident=job(c,root);finish(ident);cand=state(c,root)['results'][0]
    r=c.post(root+f"/ai/results/{cand['id']}/decision",json={'action':'approve','revision':0});assert r.status_code==200,r.text
    assert '天気' in details(c,root)['editor_text'];assert c.get(root+'/original').content==original
    history=c.get(root+'/history').json();assert history['state']['commands'][0]['source']=='ai'
    assert c.post(root+'/undo',json={'revision':1}).status_code==200;assert state(c,root)['results'][0]['status']=='undone'
    assert c.post(root+'/redo',json={'revision':2}).status_code==200;assert state(c,root)['results'][0]['status']=='approved'
    assert c.get(root+'/export').status_code==200
    backup=c.get(root+'/project/export');assert backup.status_code==200
    assert c.post('/api/projects/import',files={'file':('backup.eproof',backup.content)}).status_code==200

@pytest.mark.parametrize('action,status',[('reject','rejected'),('hold','held')])
def test_reject_hold_do_not_edit(session,mock_ai,action,status):
    c,create=session;root=create();ident=job(c,root);finish(ident);cand=state(c,root)['results'][0];before=details(c,root)['editor_text']
    r=c.post(root+f"/ai/results/{cand['id']}/decision",json={'action':action,'revision':0});assert r.status_code==200,r.text
    assert state(c,root)['results'][0]['status']==status and details(c,root)['editor_text']==before

def test_manual_change_marks_stale_and_blocks_approval(session,mock_ai):
    c,create=session;root=create();ident=job(c,root);finish(ident);cand=state(c,root)['results'][0]
    assert edit(c,root,P2,details(c,root)['editor_text']+'追加').status_code==200
    assert state(c,root)['results'][0]['status']=='reviewed'
    assert c.post(root+f"/ai/results/{cand['id']}/decision",json={'action':'approve','revision':1}).status_code==409

def test_pause_resume_cancel_and_restart_restore(session,mock_ai,tmp_path):
    c,create=session;root=create();ident=job(c,root,'book')
    assert c.post(root+f'/ai/jobs/{ident}/pause').status_code==200;run(ident);assert state(c,root)['jobs'][0]['status']=='paused'
    c.post(root+f'/ai/jobs/{ident}/resume');run(ident);assert state(c,root)['jobs'][0]['done']==1
    worker=jobs.Worker(module.database,tmp_path/'worker');worker.launch();worker.close()
    assert state(c,root)['jobs'][0]['status']=='interrupted';assert state(c,root)['jobs'][0]['done']==1
    c.post(root+f'/ai/jobs/{ident}/resume');run(ident);assert state(c,root)['jobs'][0]['done']==2
    c.post(root+f'/ai/jobs/{ident}/cancel');run(ident);assert state(c,root)['jobs'][0]['status']=='cancelled'

def test_connection_fail_error_retry(session,mock_ai,monkeypatch):
    c,create=session;root=create();good=PROVIDERS['ollama'].generate
    def fail(*args):raise ValueError('AIへ接続できません。')
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',fail);ident=job(c,root);finish(ident);s=state(c,root);assert s['jobs'][0]['failed']==1;assert s['jobs'][0]['status']=='completed_with_errors'
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',good);assert c.post(root+f'/ai/jobs/{ident}/retry').status_code==200;finish(ident);assert len(state(c,root)['results'])==1
    monkeypatch.setattr(PROVIDERS['ollama'],'models',fail);assert c.post('/api/ai/engines/'+engines(c)[0]['id']+'/test').status_code==502

def test_invalid_response_retried_and_usage_saved(session,mock_ai,monkeypatch):
    c,create=session;root=create();calls=[]
    def bad(*args):calls.append(1);return Reply('not json',10,20)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',bad);ident=job(c,root);finish(ident);s=state(c,root)
    assert len(calls)==3 and s['jobs'][0]['failed']==1 and s['jobs'][0]['input_tokens']==30

def test_long_chunk_preserves_ruby_and_unique_positions():
    p={'paragraph_id':'p','text':'あ'*250+'漢字'+'い'*400,'rubies':[{'index':0,'start':250,'end':252,'base':'漢字','readings':['かんじ']}],'previous':'前','next':'次'}
    cs=list(chunks(p,251));assert ''.join(c['target'] for c in cs)==p['text'];assert cs[0]['target'].endswith('漢字')
    with pytest.raises(ValueError):validated(json.dumps({'paragraph_id':'wrong','suggestions':[]}),p,cs[0])
    with pytest.raises(ValueError):validated(json.dumps({'paragraph_id':'p','suggestions':[suggestion('あ','え')]}),p,cs[0])

def test_multiple_nonoverlap_candidates_can_be_approved(session,mock_ai,monkeypatch):
    c,create=session;root=create();old=details(c,root)['editor_text'];edit(c,root,P2,old+'縁起が7いい。')
    def gen(e,s,p):
        d=parse_prompt(p);return Reply(json.dumps({'paragraph_id':d['paragraph_id'],'findings':[hit(d),hit(d,'7','')]}),10,20)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',gen);ident=job(c,root);finish(ident);cs=state(c,root)['results'];assert len(cs)==2
    for rev,cand in enumerate(sorted(cs,key=lambda c:c['start']),1):
        r=c.post(root+f"/ai/results/{cand['id']}/decision",json={'action':'approve','revision':rev});assert r.status_code==200,r.text
    assert '天気' in details(c,root)['editor_text'] and '縁起がいい' in details(c,root)['editor_text']

def test_cloud_confirmation_quote_budget_and_cost(session,mock_ai,monkeypatch):
    c,create=session;root=create();monkeypatch.setenv('AI_SECRET_KEY',Fernet.generate_key().decode());e=engines(c)[0]
    cloud=c.post('/api/ai/engines',json={**e,'provider':'openai','url':'https://api.openai.com','api_key':'mock','input_price':2,'output_price':4}).json()
    b=request(c,root,engine_id=cloud['id'],budget=.00001);q=c.post(root+'/ai/quote',json=b).json();assert q['estimated_cost']>0
    assert c.post(root+'/ai/jobs',json=b).status_code==422
    monkeypatch.setattr(PROVIDERS['openai'],'generate',PROVIDERS['ollama'].generate)
    ident=c.post(root+'/ai/jobs',json={**b,'cloud_confirmed':True}).json()['job_id'];run(ident);assert state(c,root)['jobs'][0]['status']=='budget_paused'

def test_delete_project_cascades_ai_but_keeps_engines(session,mock_ai):
    c,create=session;root=create();ident=job(c,root);finish(ident);b=c.get(root).json()
    r=c.post(root+'/delete',json={'filename':b['catalog']['filename'],'revision':0,'published_version':0});assert r.status_code==200,r.text
    with module.database() as con:assert con.execute('SELECT COUNT(*) FROM ai_jobs').fetchone()[0]==0
    assert len(engines(c))==1

@pytest.mark.parametrize('provider',['ollama','openai','gemini','anthropic'])
def test_provider_adapter_normalization_and_schema(monkeypatch,provider):
    from epub_proofreader.ai.providers import base
    from epub_proofreader.ai.engine_manager import OFFICIAL
    calls=[];text=json.dumps({'paragraph_id':'p','suggestions':[]})
    responses={'ollama':{'message':{'content':text},'prompt_eval_count':11,'eval_count':22},'openai':{'output':[{'content':[{'type':'output_text','text':text}]}],'usage':{'input_tokens':11,'output_tokens':22}},'gemini':{'candidates':[{'content':{'parts':[{'text':text}]}}],'usageMetadata':{'promptTokenCount':11,'candidatesTokenCount':20,'thoughtsTokenCount':2}},'anthropic':{'content':[{'type':'text','text':text}],'usage':{'input_tokens':11,'output_tokens':22}}}
    def req(e,method,path,**kwargs):calls.append((path,kwargs));return responses[provider]
    monkeypatch.setattr(PROVIDERS[provider],'request',req)
    result=PROVIDERS[provider].generate({'provider':provider,'model':'test','url':OFFICIAL.get(provider,'http://localhost:11434'),'api_key':'mock','max_output_tokens':256},'system','prompt')
    assert result.text==text and result.input_tokens==11 and result.output_tokens==22
    assert 'schema' in json.dumps(calls[0][1]) or provider=='ollama'

def test_ruby_suggestion_approve_preserves_structure(session,mock_ai,monkeypatch):
    c,create=session;root=create();pid='chapter0001-p00001';d=details(c,root,pid);ruby=d['rubies'][0]
    def gen(e,s,p):
        data=parse_prompt(p)
        return Reply(json.dumps({'paragraph_id':pid,'suggestions':[] if data.get('query_type')=='body' else [suggestion(ruby['base'],ruby['base'],target='ruby',ruby_index=0,base_after=ruby['base'],reading_after='ワガハイ',category='ruby')]}),10,20)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',gen);ident=job(c,root,paragraph_id=pid);finish(ident);cand=state(c,root)['results'][0]
    r=c.post(root+f"/ai/results/{cand['id']}/decision",json={'action':'approve','revision':0});assert r.status_code==200,r.text
    assert details(c,root,pid)['rubies'][0]['readings']==['ワガハイ'];assert c.get(root+'/export').status_code==200

def test_result_saved_before_completion_and_state_reconnection(session,mock_ai):
    c,create=session;root=create();ident=job(c,root,'book');run(ident);run(ident)
    s=state(c,root);assert s['jobs'][0]['status']=='running' and s['jobs'][0]['done']==2 and len(s['results'])==1
    from fastapi.testclient import TestClient
    assert TestClient(module.app).get(root+'/ai').json()==s

def test_owner_fields_on_persistent_records(session,mock_ai):
    c,create=session;root=create();ident=job(c,root);finish(ident)
    with module.database() as con:
        for table in ['books','ai_engines','ai_jobs','ai_results','ai_usage']:
            assert con.execute(f'SELECT DISTINCT owner_id FROM {table}').fetchall()==[('local',)]

def test_portable_backup_restores_ai_evidence_without_engines_or_autorun(session,mock_ai):
    c,create=session;root=create();ident=job(c,root);finish(ident);cand=state(c,root)['results'][0]
    c.post(root+f"/ai/results/{cand['id']}/decision",json={'action':'hold','revision':0})
    archive=c.get(root+'/project/export').content
    import io,zipfile
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        ai=z.read('ai.json');assert b'key_cipher' not in ai and b'api_key' not in ai
    restored=c.post('/api/projects/import',files={'file':('test.eproof',archive)});assert restored.status_code==200,restored.text
    s=state(c,'/api/books/'+restored.json()['id']);assert s['jobs'][0]['status']=='archived' and s['results'][0]['status']=='held'
    assert s['results'][0]['id']!=cand['id'] and len(engines(c))==1

def test_key_validation_error_does_not_echo_key(session):
    c,create=session;create();e=engines(c)[0];secret='secret'*100
    r=c.post('/api/ai/engines',json={**e,'api_key':secret});assert r.status_code==422 and 'secret' not in r.text

def test_bad_provider_envelope_retries_without_exposing_body(session,mock_ai,monkeypatch):
    c,create=session;root=create();calls=[]
    def bad(*args):calls.append(1);raise KeyError('private response body')
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',bad);ident=job(c,root);finish(ident);s=state(c,root)
    assert len(calls)==3 and s['jobs'][0]['failed']==1 and 'private response body' not in json.dumps(s)

def test_pause_and_cancel_during_inflight_request(session,mock_ai,monkeypatch):
    c,create=session;root=create();good=PROVIDERS['ollama'].generate;current={}
    def pause(*args):
        c.post(root+f"/ai/jobs/{current['id']}/pause");return good(*args)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',pause);current['id']=job(c,root);run(current['id']);s=state(c,root)
    assert s['jobs'][0]['status']=='paused' and len(s['results'])==1
    c.post(root+f"/ai/jobs/{current['id']}/cancel")
    def cancel(*args):
        c.post(root+f"/ai/jobs/{current['id']}/cancel");return good(*args)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',cancel);current['id']=job(c,root);run(current['id']);s=state(c,root)
    assert s['jobs'][0]['status']=='cancelled' and len(s['results'])==1

def test_human_edit_during_ai_request_marks_incoming_result_stale(session,mock_ai,monkeypatch):
    c,create=session;root=create();good=PROVIDERS['ollama'].generate
    def concurrent(*args):
        edit(c,root,P2,details(c,root)['editor_text']+'追記');return good(*args)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',concurrent);ident=job(c,root);finish(ident);assert state(c,root)['results'][0]['stale']

def test_approve_small_span_in_very_long_paragraph_and_backup(session,mock_ai,monkeypatch):
    c,create=session
    from test_epub import changed
    from test_editing import SAMPLE
    from epub_proofreader.epub import NS
    # Build a valid original with a paragraph beyond the manual editor limit.
    from lxml import etree
    from epub_proofreader.epub import Book
    source=Book(SAMPLE.read_bytes());tree=source.trees['EPUB/chapter1.xhtml'];node=tree.xpath('//x:p',namespaces=NS)[1]
    node.text=''.join(chr(0x4e00+i) for i in range(21000)).replace('汽','水')+'天汽。'
    for child in list(node):node.remove(child)
    import io,zipfile
    data=module.editing.repack(SAMPLE.read_bytes(),{'EPUB/chapter1.xhtml':etree.tostring(tree,encoding='utf-8',xml_declaration=True)})
    root=create(data);ident=job(c,root);finish(ident,100);cand=state(c,root)['results'][0]
    r=c.post(root+f"/ai/results/{cand['id']}/decision",json={'action':'approve','revision':0});assert r.status_code==200,r.text
    assert details(c,root)['editor_text'].endswith('天気。')
    archive=c.get(root+'/project/export').content
    assert c.post('/api/projects/import',files={'file':('long.eproof',archive)}).status_code==200

# Regression: one hallucinated or malformed candidate must not discard safe siblings.
def test_mixed_response_keeps_safe_candidates_and_reports_bad_ones():
    from epub_proofreader.ai.proofreading import assessed
    p={'paragraph_id':'p','text':'今日は天汽。','rubies':[]};chunk=next(chunks({**p,'previous':'','next':''},1200))
    valid,issues=assessed(json.dumps({'paragraph_id':'p','suggestions':[suggestion(),suggestion('存在しない語','修正'),{'unexpected':'value'}]}),p,chunk)
    assert len(valid)==1 and valid[0]['original']=='汽' and valid[0]['replacement']=='気'
    assert len(issues)==2 and '存在しない語' not in ' '.join(issues)

def test_context_including_unchanged_ruby_is_narrowed_safely():
    p={'paragraph_id':'p','text':'猫は天汽。','rubies':[{'index':0,'base':'猫','readings':['ねこ'],'start':0,'end':1,'editable':True}],'previous':'','next':''}
    result=validated(json.dumps({'paragraph_id':'p','suggestions':[suggestion('猫は天汽','猫は天気')]}),p,next(chunks(p,1200)))
    assert result[0]['start']==3 and result[0]['original']=='汽'
    with pytest.raises(ValueError):validated(json.dumps({'paragraph_id':'p','suggestions':[suggestion('猫','犬')]}),p,next(chunks(p,1200)))

def test_ruby_original_and_index_must_both_match():
    p={'paragraph_id':'p','text':'猫','rubies':[{'index':0,'base':'猫','readings':['ねこ'],'start':0,'end':1,'editable':True}],'previous':'','next':''}
    bad=suggestion('犬','猫',target='ruby',ruby_index=0,base_after='猫',reading_after='いぬ')
    with pytest.raises(ValueError):validated(json.dumps({'paragraph_id':'p','suggestions':[bad]}),p,next(chunks(p,1200)))
    bad=suggestion('猫','猫',target='text',ruby_index=0,base_after='猫',reading_after='ねこ')
    with pytest.raises(ValueError):validated(json.dumps({'paragraph_id':'p','suggestions':[bad]}),p,next(chunks(p,1200)))

def test_prompt_omits_ruby_xml_and_unchanged_ruby_is_ignored():
    p={'paragraph_id':'p','text':'猫','rubies':[{'index':0,'base':'猫','readings':['ねこ'],'start':0,'end':1,'editable':True,'xpath':'private/path','original_xml':'<ruby>cat</ruby>'}],'previous':'','next':''}
    chunk=next(chunks(p,1200));assert 'xpath' not in chunk['rubies'][0] and 'original_xml' not in chunk['rubies'][0]
    s=suggestion('猫','猫',target='ruby',ruby_index=0,base_after='猫',reading_after='ねこ')
    assert validated(json.dumps({'paragraph_id':'p','suggestions':[s]}),p,chunk)==[]

def test_partial_candidates_are_persisted_deduplicated_and_retried(session,mock_ai,monkeypatch):
    c,create=session;root=create();prompts=[]
    def mixed(e,s,p):
        prompts.append(p);d=parse_prompt(p)
        return Reply(json.dumps({'paragraph_id':d['paragraph_id'],'findings':[hit(d),{'i':0,'o':'不存在','r':'変更'}]}),10,20)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',mixed);ident=job(c,root);finish(ident);s=state(c,root)
    assert len(s['results'])==1 and s['jobs'][0]['failed']==1 and s['jobs'][0]['status']=='completed_with_errors'
    assert '指定した文にありません' in prompts[1] and '前回の検証結果' in prompts[1]
    assert '天汽' in details(c,root)['editor_text']
    def good(e,s,p):
        d=parse_prompt(p);return Reply(json.dumps({'paragraph_id':d['paragraph_id'],'findings':[hit(d)]}),10,20)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',good);c.post(root+f'/ai/jobs/{ident}/retry');finish(ident);s=state(c,root)
    assert len(s['results'])==1 and s['jobs'][0]['failed']==0 and s['jobs'][0]['error'] is None
