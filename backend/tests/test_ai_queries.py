import json,pytest
from epub_proofreader import app as module
from epub_proofreader.ai import queries
from epub_proofreader.ai.providers import PROVIDERS
from epub_proofreader.ai.providers.base import Reply,schema
from test_editing import session,details,P1,P2
from test_ai import mock_ai,job,finish,state

def paragraph():
    return {'paragraph_id':'p','text':'猫は天汽。','rubies':[{'index':0,'base':'猫','readings':['ねこ'],'start':0,'end':1,'editable':True}],'previous':'前の文','next':'次の文'}
def response(items):return json.dumps({'paragraph_id':'p','suggestions':items},ensure_ascii=False)
def body(**patch):return {'start':3,'original':'汽','replacement':'気','reason':'OCR誤認識','category':'kanji','confidence':.8,**patch}
def ruby(**patch):return {'ruby_index':0,'base_after':None,'reading_after':'ネコ','reason':'読みを確認','confidence':.8,**patch}

def test_queries_and_schemas_are_separate_and_omit_redundant_fields():
    p=paragraph();qs=list(queries.queries(p,1200));assert [q['query_type'] for q in qs]==['body','ruby']
    b=json.loads(queries.prompt(qs[0]));r=json.loads(queries.prompt(qs[1]))
    assert 'rubies' not in b and 'readings' not in json.dumps(b) and 'units' in b
    assert 'rubies' in r and 'units' not in r
    ruby_schema=queries.output_schema(qs[1]);assert 'replacement' not in json.dumps(ruby_schema) and 'original' not in json.dumps(ruby_schema)
    e={'_response_schema':ruby_schema};before=json.dumps(e);assert 'maxLength' not in json.dumps(schema(e));assert json.dumps(e)==before

def test_body_proposal_and_detection_only_both_locate_server_owned_text():
    p=paragraph();q=next(queries.queries(p,1200))
    values,issues=queries.assess(response([body(),body(replacement=None)]),p,q)
    assert not issues and len(values)==2
    assert values[0]['original']=='汽' and values[0]['replacement']=='気' and values[0]['start']==3
    assert values[1]['original']=='汽' and values[1]['replacement'] is None

def test_bad_proposal_is_rejected_without_sentence_fallback():
    p=paragraph();q=next(queries.queries(p,1200))
    for candidate in [body(original='本文にない文字列'),body(start=None),body(start=2),body(unit_id=999)]:
        values,issues=queries.assess(response([candidate]),p,q);assert not values and issues

def test_body_on_ruby_base_stays_short_and_manual():
    p=paragraph();q=next(queries.queries(p,1200));values,issues=queries.assess(response([body(start=0,original='猫',replacement='犬')]),p,q)
    assert not issues and values[0]['target']=='text' and values[0]['original']=='猫'
    assert values[0]['replacement'] is None and values[0]['proposal_note']

def test_ruby_reading_only_and_detection_only_require_no_duplicate_replacement():
    p=paragraph();q=list(queries.queries(p,1200))[1]
    values,issues=queries.assess(response([ruby(),ruby(reading_after=None)]),p,q)
    assert not issues and len(values)==2
    assert values[0]['base_after']=='猫' and values[0]['replacement']=='猫' and values[0]['reading_after']=='ネコ'
    assert values[1]['replacement'] is None and values[1]['ruby_before']=={'base':'猫','reading':'ねこ'}
    values,issues=queries.assess(response([ruby(ruby_index=999)]),p,q);assert not values and issues
    values,issues=queries.assess(response([ruby(reading_after='ねこ')]),p,q);assert not values and not issues

def test_complex_ruby_proposal_stays_manual():
    p=paragraph();p['rubies'][0]['editable']=False;q=list(queries.queries(p,1200))[1]
    values,issues=queries.assess(response([ruby()]),p,q);assert not issues and values[0]['replacement'] is None

def test_native_body_detection_confirm_and_backup(session,mock_ai,monkeypatch):
    c,create=session;root=create()
    def generate(e,s,prompt):
        q=json.loads(prompt);assert q['query_type']=='body';assert 'rubies' not in q
        return Reply(json.dumps({'paragraph_id':q['paragraph_id'],'suggestions':[body(start=6,replacement=None)]}),10,10)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate);ident=job(c,root);finish(ident);v=state(c,root);candidate=v['results'][0]
    assert v['jobs'][0]['status']=='completed' and candidate['replacement'] is None
    url=root+f"/ai/results/{candidate['id']}/decision"
    assert c.post(url,json={'action':'approve','revision':0}).status_code==409
    assert c.post(url,json={'action':'confirm','revision':0}).status_code==200
    assert state(c,root)['results'][0]['status']=='reviewed';assert details(c,root)['revision']==0
    archive=c.get(root+'/project/export').content;r=c.post('/api/projects/import',files={'file':('detect.eproof',archive)});assert r.status_code==200,r.text
    restored=state(c,'/api/books/'+r.json()['id']);assert restored['results'][0]['replacement'] is None and restored['results'][0]['status']=='reviewed'

def test_native_ruby_reading_only_approve_and_undo(session,mock_ai,monkeypatch):
    c,create=session;root=create();calls=[]
    def generate(e,s,prompt):
        q=json.loads(prompt);calls.append(q['query_type'])
        return Reply(json.dumps({'paragraph_id':q['paragraph_id'],'suggestions':[] if q['query_type']=='body' else [ruby(reading_after='ワガハイ')]}),10,10)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate);ident=job(c,root,paragraph_id=P1);finish(ident);v=state(c,root)
    assert calls==['body','ruby'] and v['jobs'][0]['failed']==0
    candidate=v['results'][0];assert candidate['query_type']=='ruby'
    r=c.post(root+f"/ai/results/{candidate['id']}/decision",json={'action':'approve','revision':0});assert r.status_code==200,r.text
    assert details(c,root,P1)['rubies'][0]['readings']==['ワガハイ']
    assert c.post(root+'/undo',json={'revision':1}).status_code==200
    assert details(c,root,P1)['rubies'][0]['readings']==['わがはい']

def test_quote_includes_separate_ruby_calls(session,mock_ai):
    c,create=session;root=create();book=c.get(root).json()
    from test_ai import request
    req=request(c,root,'book');quote=c.post(root+'/ai/quote',json=req).json()
    with module.database() as con:
        model=module.editing.working_model(module.editing.state(con,book['id']))
    from epub_proofreader.ai.proofreading import payloads
    allp=payloads(model,{p['id'] for ch in model.chapters for p in ch['paragraphs']})
    expected=sum(len(list(queries.queries(p,1200))) for p in allp)
    assert quote['calls']==expected and expected>quote['paragraphs']

@pytest.mark.parametrize('target',['body','ruby'])
def test_confirm_proposal_preserves_source_and_does_not_create_edit(session,mock_ai,monkeypatch,target):
    c,create=session;root=create();pid=P2 if target=='body' else P1
    original=details(c,root,pid)
    def generate(e,s,prompt):
        q=json.loads(prompt)
        suggestion=body(start=6) if target=='body' else ruby(reading_after='ワガハイ')
        return Reply(json.dumps({'paragraph_id':q['paragraph_id'],'suggestions':[suggestion] if q['query_type']==target else []}),10,10)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    ident=job(c,root,paragraph_id=pid);finish(ident)
    candidate=state(c,root)['results'][0];assert candidate['replacement'] is not None
    result=c.post(root+f"/ai/results/{candidate['id']}/decision",json={'action':'confirm','revision':0})
    assert result.status_code==200 and result.json()['book']['id']==root.rsplit('/',1)[1]
    after=details(c,root,pid);assert after['editor_text']==original['editor_text'] and after['rubies']==original['rubies']
    assert after['review_state'][target]['confirmed']
    assert state(c,root)['results'][0]['status']=='reviewed'
    assert c.get(root).json()['edit_state']['revision']==0


def test_compact_schemas_request_only_locations_and_optional_proposals():
    from epub_proofreader.ai import batching
    p={**paragraph(),'chapter_id':'c'}
    for q in [*queries.queries(p,1200),*batching.plans([p],4,1200)]:
        wire=schema({'_response_schema':queries.output_schema(q)})
        encoded=json.dumps(wire)
        assert all('"'+field+'"' not in encoded for field in ['reason','category','confidence'])
        for definition in wire.get('$defs',{}).values():
            assert set(definition['required'])==set(definition['properties'])


def test_compact_body_uses_verified_position_for_repeated_text():
    p={**paragraph(),'text':'天汽と天汽。','rubies':[]};q=next(queries.queries(p,1200))
    compact={'unit_id':0,'start':3,'original':'天汽','replacement':'天気'}
    values,issues=queries.assess(response([compact]),p,q)
    assert not issues and values[0]['start']==3 and values[0]['original']=='天汽' and values[0]['replacement']=='天気'
    assert values[0]['reason'] and values[0]['category']=='unnatural'
    for bad in [None,2,999]:
        values,issues=queries.assess(response([{**compact,'start':bad}]),p,q)
        assert not values and issues
    values,issues=queries.assess(response([{**compact,'start':-1}]),p,q)
    assert not values and issues


def test_compact_batch_ruby_and_detection_only_are_saved(session,monkeypatch):
    from test_ai_batching import start
    c,create=session;root=create()
    def generate(cfg,system,prompt):
        q=json.loads(prompt);p=q['paragraphs'][0]
        findings=([{'i':p['units'][0]['i'],'o':p['units'][0]['text'][0],'r':None}]
                  if q['query_type']=='body' else [{'paragraph_id':p['paragraph_id'],'ruby_index':p['rubies'][0]['ruby_index'],'base_after':None,'reading_after':None}])
        return Reply(json.dumps({'findings':findings}),10,5)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    ident=start(c,root);finish(ident);s=state(c,root)
    assert s['jobs'][0]['failed']==0 and len(s['results'])==2
    assert all(r['replacement'] is None and r['reason'] for r in s['results'])


@pytest.mark.parametrize('model,expected',[('gpt-6-luna',True),('gpt-6-luna-2026-10-01',True),('gpt-6-astra',False),('test',False)])
def test_openai_none_is_sent_only_for_supported_model(monkeypatch,model,expected):
    adapter=PROVIDERS['openai'];calls=[]
    def request(*args,**kwargs):
        calls.append(kwargs['json']);return {'output':[],'usage':{}}
    monkeypatch.setattr(adapter,'request',request)
    adapter.generate({'model':model,'api_key':'mock','max_output_tokens':2048},'system','prompt')
    if expected:assert calls[0]['reasoning']=={'effort':'none'}
    else:assert 'reasoning' not in calls[0]
