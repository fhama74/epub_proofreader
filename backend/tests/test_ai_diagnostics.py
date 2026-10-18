import json
import pytest
from test_editing import session
from test_ai import job,run,finish,state,mock_ai
from test_ai_continue_on_findings import source
from epub_proofreader import app as module
from epub_proofreader.ai import queries
from epub_proofreader.ai.providers import PROVIDERS
from epub_proofreader.ai.providers.base import Reply,ResponseFormatError


def errors(c,root,ident):
    r=c.get(root+f'/ai/jobs/{ident}/errors');assert r.status_code==200,r.text
    return r.json()


def test_validation_failures_store_each_full_output_and_survive_retry(session,monkeypatch):
    c,create=session;root=create(source(1))
    raw=json.dumps({'findings':[{'i':0,'o':'この原文は長すぎます','r':None}]},ensure_ascii=False)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',lambda *args:Reply(raw,10,10))
    ident=job(c,root,'chapter');finish(ident)
    listing=errors(c,root,ident)
    assert listing['total']==3 and {e['attempt'] for e in listing['entries']}=={1,2,3}
    assert listing['status']=='completed_with_errors' and listing['consecutive_failures']==0
    assert all(e['kind']=='format' and e['has_output'] for e in listing['entries'])
    assert all('output' not in e for e in listing['entries'])
    for e in listing['entries']:
        r=c.get(root+f'/ai/jobs/{ident}/errors/'+e['id']);assert r.status_code==200 and r.json()['output']==raw
    assert raw not in c.get(root+'/ai').text
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',lambda *args:Reply('{"findings":[]}',1,1))
    assert c.post(root+f'/ai/jobs/{ident}/retry').status_code==200
    finish(ident)
    assert errors(c,root,ident)['total']==3
    assert state(c,root)['jobs'][0]['status']=='completed'


@pytest.mark.parametrize('message,kind',[('接続エラー：AIサービスに接続できません。','connection'),('AIから応答がありません。処理の長期化、サービス停止、通信断の可能性があります。','timeout'),('AIサービスを利用できません（HTTP 503）。','http')])
def test_connection_errors_have_no_output_and_five_batches_stop(session,monkeypatch,message,kind):
    c,create=session;root=create(source(24));ident=job(c,root,'chapter',batch_paragraphs=4)
    def fail(*args):raise ValueError(message)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',fail)
    run(ident);j=state(c,root)['jobs'][0]
    assert j['failed']==4 and j['status']=='running' and j['consecutive_failures']==1
    for _ in range(4):run(ident)
    j=state(c,root)['jobs'][0]
    assert j['failed']==20 and j['status']=='paused' and j['consecutive_failures']==5
    listing=errors(c,root,ident)
    assert listing['stop_reason'] and '5回連続' in listing['stop_reason'] and message in listing['stop_reason']
    assert listing['total']==6 and all(e['kind'] in {kind,'stop'} and not e['has_output'] for e in listing['entries'])
    assert c.post(root+f'/ai/jobs/{ident}/resume').status_code==200
    assert state(c,root)['jobs'][0]['consecutive_failures']==0


def test_success_resets_count_and_old_failures_do_not_stop_job(session,monkeypatch):
    c,create=session;root=create(source(16));ident=job(c,root,'chapter');calls=[]
    def generate(*args):
        calls.append(1)
        if len(calls)%3:raise ValueError('接続エラー：AIサービスに接続できません。')
        return Reply('{"findings":[]}',1,1)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    finish(ident,steps=20)
    j=state(c,root)['jobs'][0]
    assert j['status']=='completed_with_errors' and j['failed']>5
    assert j['consecutive_failures']<3 and not j['stop_reason']


def test_unexpected_processing_error_records_class_and_reply_without_secret_exception_text(session,monkeypatch):
    c,create=session;root=create(source(1));ident=job(c,root,'chapter')
    raw='{"findings":[]}'
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',lambda *args:Reply(raw,1,1))
    def fail(*args):raise RuntimeError('private credential must not appear')
    monkeypatch.setattr(queries,'assess',fail)
    run(ident);listing=errors(c,root,ident)
    assert listing['entries'][0]['exception_type']=='RuntimeError'
    assert 'private credential' not in json.dumps(listing)
    assert c.get(root+f'/ai/jobs/{ident}/errors/'+listing['entries'][0]['id']).json()['output']==raw


def test_bad_json_records_full_reply_but_never_auto_pauses(session,monkeypatch):
    c,create=session;root=create(source(7));ident=job(c,root,'chapter')
    raw='not JSON <script>bad()</script>'
    def fail(*args):raise ResponseFormatError('AI接続先から不正なJSONが返りました。',raw)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',fail)
    finish(ident)
    listing=errors(c,root,ident)
    assert listing['total']==21 and listing['status']=='completed_with_errors'
    assert listing['consecutive_failures']==0 and all(e['kind']=='format' for e in listing['entries'])
    entry=listing['entries'][0]
    assert c.get(root+f'/ai/jobs/{ident}/errors/'+entry['id']).json()['output']==raw
    other=create()
    assert c.get(other+f'/ai/jobs/{ident}/errors').status_code==404
    assert c.get(other+f'/ai/jobs/{ident}/errors/'+entry['id']).status_code==404


def test_paragraph_start_resets_only_target_and_quote_does_not_change_review(session,mock_ai):
    from test_review_workflow import confirm
    from test_editing import details,P1,P2
    from test_ai import request
    c,create=session;root=create()
    for pid in (P1,P2):
        assert confirm(c,root,pid).status_code==200
        assert confirm(c,root,pid,'ruby').status_code==200
    body=request(c,root,paragraph_id=P1,skip_confirmed=True)
    before=c.get(root+'/history').json()
    r=c.post(root+'/ai/quote',json=body);assert r.status_code==200 and r.json()['paragraphs']==1
    assert details(c,root,P1)['review_state']['body']['confirmed']
    r=c.post(root+'/ai/jobs',json=body);assert r.status_code==200,r.text
    assert not details(c,root,P1)['review_state']['body']['confirmed']
    assert not details(c,root,P1)['review_state']['ruby']['confirmed']
    assert details(c,root,P2)['review_state']['body']['confirmed']
    assert c.get(root+'/history').json()==before
    finish(r.json()['job_id'])
    assert [q['query_type'] for q in mock_ai]==['body','ruby']


def test_context_separates_sent_validation_and_edited_live_text(session,monkeypatch):
    from test_editing import details,edit,P1
    c,create=session;root=create(source(1));original=details(c,root,P1)['editor_text']
    ident=job(c,root,paragraph_id=P1)
    calls=[]
    def generate(cfg,system,prompt):
        calls.append(prompt)
        if len(calls)==1:
            r=edit(c,root,P1,original+'新しい追記。');assert r.status_code==200,r.text
        return Reply('{"findings":[{"i":0,"o":"新","r":null}]}',10,5)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    finish(ident)
    entries=errors(c,root,ident)['entries'];assert len(entries)==3
    records=[c.get(root+f'/ai/jobs/{ident}/errors/'+e['id']).json() for e in entries]
    contexts={e['attempt']:r['context'] for e,r in zip(entries,records)}
    first=contexts[1]
    assert first['request']['prompt']==calls[0]
    assert first['sent_units'][0]['text']==original
    assert first['validation_units']==first['sent_units'] and first['unit_mapping_unchanged'] is True
    assert first['current_before_send']['paragraphs'][0]['text']==original
    assert first['current_at_error']['paragraphs'][0]['text']==original+'新しい追記。'
    assert first['findings_comparison'][0]['original_in_assigned_unit'] is False
    assert first['findings_comparison'][0]['assigned_unit']['text']==original
    assert contexts[2]['current_before_send']['paragraphs'][0]['text']==original+'新しい追記。'
    assert len({ctx['request_id'] for ctx in contexts.values()})==3
    assert '前回の検証結果' in contexts[2]['request']['prompt']
    assert 'current_at_error' not in c.get(root+'/ai').text


def test_context_shows_other_sent_unit_containing_the_reported_character(session,monkeypatch):
    c,create=session;root=create(source(2));ident=job(c,root,'chapter',batch_paragraphs=4)
    def generate(cfg,system,prompt):
        # Credentials/config unrelated to the text must never enter diagnostics.
        cfg['api_key']='private-test-credential'
        return Reply('{"findings":[{"i":0,"o":"1","r":null}]}',1,1)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    finish(ident)
    entry=errors(c,root,ident)['entries'][0]
    response=c.get(root+f'/ai/jobs/{ident}/errors/'+entry['id'])
    ctx=response.json()['context'];check=ctx['findings_comparison'][0]
    assert check['original_in_assigned_unit'] is False and check['other_matching_units']==[1]
    assert [u['i'] for u in ctx['sent_units']]==[0,1]
    assert ctx['unit_mapping_unchanged'] is True
    assert 'private-test-credential' not in response.text
    assert 'api_key' not in response.text


def test_legacy_errors_have_no_context_and_access_checks_still_apply(session):
    from epub_proofreader.ai import diagnostics
    c,create=session;root=create();ident=job(c,root)
    diagnostics.record(module.database,ident,['chapter0001-p00002'],'body',1,'format','旧記録','old output')
    entry=errors(c,root,ident)['entries'][0]
    assert c.get(root+f'/ai/jobs/{ident}/errors/'+entry['id']).json()=={'output':'old output','context':None}
