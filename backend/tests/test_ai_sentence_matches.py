import json
import pytest
from test_editing import session,details,P1,P2,SAMPLE
from test_epub import changed
from test_ai import job,finish,state
from epub_proofreader.ai import queries,batching
from epub_proofreader.ai.providers import PROVIDERS
from epub_proofreader.ai.providers.base import Reply


def paragraph(text,pid='p'):
    return {'paragraph_id':pid,'chapter_id':'c','text':text,'rubies':[],'previous':'','next':''}

def inspect(text,findings):
    p=paragraph(text);q=next(queries.queries(p,1200))
    return queries.assess(json.dumps({'findings':findings}),p,q)


def test_unique_match_returns_proposal_without_any_character_position():
    values,issues=inspect('😀今日は天汽です。',[{'i':0,'o':'汽','r':'気'}])
    assert not issues and len(values)==1
    d=values[0];assert d['start']==5 and d['end']==6 and d['original']=='汽' and d['replacement']=='気' and d['match_count']==1


def test_multiple_matches_are_all_located_but_never_get_an_automatic_proposal():
    values,issues=inspect('天汽と天汽。次の文には天汽。',[{'i':0,'o':'汽','r':'気'}])
    assert not issues and [v['start'] for v in values]==[1,4]
    assert all(v['match_count']==2 and v['replacement'] is None and v['suggested_replacement']=='気' for v in values)
    other,issues=inspect('天汽と天汽。次の文には天汽。',[{'i':1,'o':'汽','r':'気'}])
    assert not issues and len(other)==1 and other[0]['replacement']=='気'


def test_overlapping_repetitions_are_all_highlighted_not_treated_as_a_long_finding():
    values,issues=inspect('ののの。',[{'i':0,'o':'のの','r':'の'}])
    assert not issues and [(v['start'],v['end']) for v in values]==[(0,2),(1,3)]
    assert all(v['replacement'] is None for v in values)


def test_repetition_count_uses_the_whole_sentence_across_chunks():
    p=paragraph('汽'+'あ'*1400+'汽。');q=next(queries.queries(p,1200))
    values,issues=queries.assess('{"findings":[{"i":0,"o":"汽","r":"気"}]}',p,q)
    assert not issues and [v['start'] for v in values]==[0,1401]
    assert all(v['match_count']==2 and v['replacement'] is None for v in values)


@pytest.mark.parametrize('finding',[
    {'i':0,'o':'存在しない文字'}, {'i':0,'o':'犬'}, {'i':99,'o':'汽'},
    {'i':'0','o':'汽'}, {'i':-1,'o':'汽'}, {'i':0,'o':''}, {'i':0,'o':'天汽。長'},
])
def test_bad_ids_and_nonverbatim_or_long_originals_are_not_saved(finding):
    values,issues=inspect('天汽。',[finding]);assert not values and issues


def test_deletion_and_detection_without_proposal():
    values,issues=inspect('天汽と7。',[{'i':0,'o':'7','r':''},{'i':0,'o':'汽'}])
    assert not issues and [v['replacement'] for v in values]==['',None]


def test_ruby_base_remains_manual_even_when_the_text_match_is_unique():
    p=paragraph('猫。');p['rubies']=[{'index':0,'base':'猫','readings':['ねこ'],'start':0,'end':1,'editable':True}]
    q=next(queries.queries(p,1200));values,issues=queries.assess('{"findings":[{"i":0,"o":"猫","r":"犬"}]}',p,q)
    assert not issues and values[0]['replacement'] is None and '親文字' in values[0]['proposal_note']


def test_batch_sentence_ids_are_short_unique_and_map_to_the_right_paragraph():
    paragraphs=[paragraph('前の文。天汽。','a'),paragraph('天汽。','b')]
    q=next(batching.plans(paragraphs,4,1200));wire=json.loads(queries.prompt(q))
    assert [u['i'] for p in wire['paragraphs'] for u in p['units']]==[0,1,2]
    assert 'start' not in queries.prompt(q) and 'unit_id' not in queries.prompt(q)
    values,issues=queries.assess('{"findings":[{"i":2,"o":"汽","r":"気"}]}',paragraphs[0],q)
    assert not issues and values[0]['_paragraph_id']=='b' and values[0]['start']==1
    schema=queries.output_schema(q);definition=schema['$defs']['Candidate']
    assert set(definition['properties'])=={'i','o','r'} and set(schema['properties'])=={'findings'}


def test_ambiguous_occurrences_stay_manual_through_backup_and_only_one_manual_edit_is_applied(session,monkeypatch):
    c,create=session
    root=create(changed({'EPUB/chapter1.xhtml':'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>テスト</title></head><body><p>天汽と天汽。</p></body></html>'.encode()}))
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',lambda *args:Reply('{"findings":[{"i":0,"o":"汽","r":"気"}]}',10,5))
    finish(job(c,root,paragraph_id=P1));s=state(c,root)
    assert s['jobs'][0]['failed']==0 and len(s['results'])==2
    assert details(c,root,P1)['editor_text']=='天汽と天汽。'
    for d in s['results']:
        assert d['replacement'] is None and d['match_count']==2
        assert c.post(root+f"/ai/results/{d['id']}/decision",json={'action':'approve','revision':0}).status_code==409
    restored=c.post('/api/projects/import',files={'file':('matching.eproof',c.get(root+'/project/export').content)})
    assert restored.status_code==200,restored.text
    other=state(c,'/api/books/'+restored.json()['id'])
    assert all(d['match_count']==2 and d['suggested_replacement']=='気' for d in other['results'])
    d=details(c,root,P1)
    response=c.patch(root+f'/paragraphs/{P1}',json={'revision':0,'expected_token':d['token'],'text':'天気と天汽。'})
    assert response.status_code==200,response.text
    assert details(c,root,P1)['editor_text']=='天気と天汽。'


def test_unique_candidate_is_only_applied_when_human_approves(session,monkeypatch):
    c,create=session;root=create()
    def generate(cfg,system,prompt):
        q=json.loads(prompt);u=next(u for u in q['units'] if '天汽' in u['text'])
        return Reply(json.dumps({'findings':[{'i':u['i'],'o':'汽','r':'気'}]}),10,5)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    finish(job(c,root));s=state(c,root);d=s['results'][0]
    assert s['jobs'][0]['failed']==0 and d['replacement']=='気' and d['match_count']==1
    assert '天汽' in details(c,root)['editor_text']
    result=c.post(root+f"/ai/results/{d['id']}/decision",json={'action':'approve','revision':0})
    assert result.status_code==200,result.text
    assert '天気' in details(c,root)['editor_text']
