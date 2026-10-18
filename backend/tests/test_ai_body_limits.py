import json
import pytest
from test_editing import session
from test_ai import job,finish,state,parse_prompt
from test_ai_sentence_matches import inspect,paragraph
from epub_proofreader import app as module
from epub_proofreader.ai import queries,batching,prompts,schema
from epub_proofreader.ai.providers import PROVIDERS
from epub_proofreader.ai.providers.base import Reply


@pytest.mark.parametrize('batch',[False,True])
def test_three_characters_are_verbatim_and_four_character_clusters_are_rejected(batch):
    p=paragraph('ごおう。');q=next(batching.plans([p],4,1200)) if batch else next(queries.queries(p,1200))
    values,issues=queries.assess('{"findings":[{"i":0,"o":"ごおう","r":"言おう"}]}',p,q)
    assert not issues and len(values)==1 and values[0]['original']=='ごおう'
    assert values[0]['replacement']=='言おう'
    values,issues=inspect('あいうえ。',[{'i':0,'o':'あい'},{'i':0,'o':'う'}])
    assert not issues and len(values)==2
    values,issues=inspect('あいうえ。',[{'i':0,'o':'あい'},{'i':0,'o':'うえ'}])
    assert not values and '連続4文字以上' in str(issues)


@pytest.mark.parametrize('batch',[False,True])
def test_candidate_cap_and_incomplete_json_have_distinct_errors(batch):
    p=paragraph('汽。');q=next(batching.plans([p],4,1200)) if batch else next(queries.queries(p,1200))
    with pytest.raises(ValueError,match='候補上限100件に対し101件'):
        queries.assess(json.dumps({'findings':[{'i':0,'o':'汽'}]*101}),p,q)
    with pytest.raises(ValueError,match='JSONが不完全または不正'):
        queries.assess('{"findings":[',p,q)


def test_retry_feedback_identifies_wrong_id_original_and_matching_sentence(session,monkeypatch):
    c,create=session;root=create();calls=[]
    def generate(cfg,system,prompt):
        p=parse_prompt(prompt);calls.append((cfg,prompt))
        if p['query_type']=='ruby':return Reply('{"suggestions":[]}',1,1)
        units=json.loads(prompt.split('\n前回の検証結果')[0])['units']
        # The character occurs in sentence 0; sentence 1 is intentionally wrong.
        if len(calls)==1:return Reply('{"findings":[{"i":1,"o":"汽","r":"気"}]}',1,1)
        assert '指定した文の原文' in prompt and '庭の向こう' in prompt
        assert '"i": 1' in prompt and '"o": "汽"' in prompt
        assert '"一致する別の文ID": [0]' in prompt
        assert cfg['max_output_tokens']==4096
        return Reply('{"findings":[{"i":0,"o":"汽","r":"気"}]}',1,1)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    finish(job(c,root));result=state(c,root)
    assert result['jobs'][0]['failed']==0 and len(result['results'])==1


def test_old_default_output_limit_upgrades_once_and_custom_limits_remain(session):
    c,create=session;create()
    with module.database() as con:
        entries=con.execute('SELECT id,config FROM ai_engines').fetchall();ident,raw=entries[0]
        cfg=json.loads(raw);cfg['max_output_tokens']=2048
        con.execute('UPDATE ai_engines SET config=? WHERE id=?',(json.dumps(cfg),ident))
        con.execute("INSERT INTO ai_engines VALUES ('custom','local',?,NULL,'now')",(json.dumps({**cfg,'max_output_tokens':1024}),))
        con.execute("DELETE FROM ai_settings WHERE key='output_default_4096'")
        schema.ensure(con)
        def limit(i):return json.loads(con.execute('SELECT config FROM ai_engines WHERE id=?',(i,)).fetchone()[0])['max_output_tokens']
        assert limit(ident)==4096 and limit('custom')==1024
        con.execute('UPDATE ai_engines SET config=? WHERE id=?',(json.dumps(cfg),ident))
        schema.ensure(con);assert limit(ident)==2048


def test_saved_previous_default_policy_upgrades_without_replacing_custom_policy(session):
    c,create=session;create()
    with module.database() as con:
        value={'values':{**prompts.DEFAULTS,'body':prompts.PREVIOUS_BODY},'revision':3}
        con.execute("INSERT INTO ai_settings VALUES ('prompt_policy:local',?)",(json.dumps(value),))
        assert '最大3文字' in prompts.read(con)['values']['body']
        assert '最大3文字' in queries.system(next(queries.queries(paragraph('汽。'),1200)),value['values'])
        value['values']['body']='利用者の独自指示'
        con.execute("UPDATE ai_settings SET value=? WHERE key='prompt_policy:local'",(json.dumps(value),))
        assert prompts.read(con)['values']['body']=='利用者の独自指示'


def test_output_limit_migrates_unfinished_jobs_but_preserves_finished_settings(session):
    c,create=session;root=create();old=job(c,root)
    with module.database() as con:con.execute("UPDATE ai_jobs SET status='completed' WHERE id=?",(old,))
    active=job(c,root)
    with module.database() as con:
        for ident in (old,active):
            cfg=json.loads(con.execute('SELECT config FROM ai_jobs WHERE id=?',(ident,)).fetchone()[0]);cfg['max_output_tokens']=2048
            con.execute('UPDATE ai_jobs SET config=? WHERE id=?',(json.dumps(cfg),ident))
        con.execute("DELETE FROM ai_settings WHERE key='output_default_4096'");schema.ensure(con)
        def limit(ident):return json.loads(con.execute('SELECT config FROM ai_jobs WHERE id=?',(ident,)).fetchone()[0])['max_output_tokens']
        assert limit(active)==4096 and limit(old)==2048
