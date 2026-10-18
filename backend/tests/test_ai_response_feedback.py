"""Optional proposals and actionable, redacted schema feedback for model retries."""
import json
import pytest
from test_editing import session
from test_ai import state,finish
from test_ai_batching import start,response
from test_ai_queries import paragraph
from epub_proofreader.ai import queries,batching
from epub_proofreader.ai.providers import PROVIDERS
from epub_proofreader.ai.providers.base import Reply


def assess(kind,items,batch):
    p={**paragraph(),'chapter_id':'c'};part=next(q for q in queries.queries(p,1200) if q['query_type']==kind)
    if batch:
        q=batching.pack(kind,[(p,part)])
        return batching.assess(json.dumps({'findings':[{'paragraph_id':'p',**item} for item in items]}),q)
    return queries.assess(json.dumps({'paragraph_id':'p','findings' if kind=='body' else 'suggestions':items}),p,part)


@pytest.mark.parametrize('batch',[False,True])
def test_optional_proposal_omission_is_detection_only(batch):
    values,issues=assess('body',[{'start':3,'original':'汽'}],batch)
    assert not issues and len(values)==1 and values[0]['replacement'] is None
    values,issues=assess('ruby',[{'ruby_index':0},{'ruby_index':0,'reading_after':'ネコ'}],batch)
    assert not issues and len(values)==2
    assert values[0]['replacement'] is None and values[1]['reading_after']=='ネコ'


@pytest.mark.parametrize('batch',[False,True])
@pytest.mark.parametrize('item,detail',[
    ({'start':3,'original':'長い指摘原文'},'最大3文字'),
    ({'start':'3','original':'汽'},'start（段落先頭からの文字位置）は整数'),
    ({'original':'汽'},'start（段落先頭からの文字位置）がありません'),
    ({'start':3,'original':['汽']},'original（指摘原文）は文字列'),
    ({'start':3,'original':'汽','private-input':'secret response content'},'指定形式にない項目'),
])
def test_feedback_names_failure_and_keeps_safe_siblings_without_leaking_values(batch,item,detail):
    values,issues=assess('body',[{'start':3,'original':'汽'},item],batch)
    assert len(values)==1 and detail in str(issues)
    assert 'secret response content' not in str(issues) and 'private-input' not in str(issues)


def test_ollama_uses_compatible_schema_but_server_keeps_short_original_validation(monkeypatch):
    part=next(queries.queries(paragraph(),1200));wire=[]
    def request(*args,**kwargs):
        wire.append(kwargs['json']);return {'message':{'content':'{"findings":[]}'}}
    monkeypatch.setattr(PROVIDERS['ollama'],'request',request)
    cfg={'model':'mock','max_output_tokens':1024,'_response_schema':queries.output_schema(part)}
    PROVIDERS['ollama'].generate(cfg,'system','prompt')
    definition=wire[0]['format']['$defs']['Candidate']
    assert definition['properties']['o']['minLength']==1
    assert definition['properties']['o']['maxLength']==3
    assert 'minimum' not in definition['properties']['i']
    assert definition['properties']['i']['type']=='integer'
    assert definition['required']==['i','o','r']
    incoming=json.dumps({'paragraph_id':'p','findings':[{'start':0,'original':'猫は天汽','replacement':None}]})
    accepted,issues=queries.assess(incoming,paragraph(),part)
    assert not accepted and '最大3文字' in str(issues)
    from epub_proofreader.ai.providers.base import schema
    assert 'maxLength' not in json.dumps(schema(cfg))
    assert wire[0]['think'] is False


def test_worker_retry_explains_bad_fields_and_saves_a_detection_without_proposal(session,monkeypatch):
    c,create=session;root=create();calls=[]
    def generate(cfg,system,prompt):
        q,findings=response(prompt);calls.append(prompt)
        if q['query_type']=='body' and len(calls)==1:
            findings=[{**findings[0],'original':'長すぎる原文'},{**findings[0],'start':'6'}]
        elif q['query_type']=='body':
            assert '最大3文字' in prompt and 'start（段落先頭からの文字位置）は整数' in prompt
            for finding in findings:finding.pop('replacement')
        return Reply(json.dumps({'findings':findings}),10,5)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    finish(start(c,root));s=state(c,root)
    assert s['jobs'][0]['failed']==0 and s['jobs'][0]['status']=='completed'
    assert len(s['results'])==1 and s['results'][0]['replacement'] is None
    assert len(calls)==3 # Invalid body, corrected body, separate ruby query.


def test_ollama_retries_rejected_short_bound_with_compatible_schema(monkeypatch):
    q=next(queries.queries(paragraph(),1200));calls=[]
    def request(*args,**kwargs):
        wire=kwargs['json']['format'];calls.append(wire)
        if len(calls)==1:raise ValueError('AI接続先が送信内容を受け付けませんでした（HTTP 400）。')
        return {'message':{'content':'{"findings":[]}'}}
    monkeypatch.setattr(PROVIDERS['ollama'],'request',request)
    PROVIDERS['ollama'].generate({'model':'mock','max_output_tokens':512,'_response_schema':queries.output_schema(q)},'system','prompt')
    assert len(calls)==2
    assert calls[0]['$defs']['Candidate']['properties']['o']['maxLength']==3
    assert 'maxLength' not in calls[1]['$defs']['Candidate']['properties']['o']
