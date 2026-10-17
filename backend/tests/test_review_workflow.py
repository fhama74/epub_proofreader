"""Human review, concurrent saves, ruby structure and the compact OCR contract."""
import json
import pytest
from test_editing import session,details,edit,P1,P2,P3
from test_epub import changed
from test_ai import mock_ai,job,finish,state
from epub_proofreader.ai import queries
from epub_proofreader.ai.providers import PROVIDERS,base
from epub_proofreader.ai.providers.base import Reply
from epub_proofreader import app as module


def confirm(c,root,pid=P2,target='body',index=None,token=None):
    return c.post(root+f'/paragraphs/{pid}/review',json={'target':target,'index':index,'expected_token':token or details(c,root,pid)['token']})


def save(c,root,d,text,**extra):
    return c.patch(root+'/paragraphs/'+d['id'],json={'revision':d['revision'],'expected_token':d['token'],'text':text,**extra})


def ruby_op(c,root,action,pid=P2,**extra):
    d=details(c,root,pid)
    return c.post(root+f'/paragraphs/{pid}/ruby-structure',json={'revision':d['revision'],'expected_token':d['token'],'action':action,**extra})


def test_different_paragraphs_merge_latest_xhtml_and_same_paragraph_conflicts(session):
    c,create=session;root=create();a=details(c,root,P2);b=details(c,root,P3)
    assert save(c,root,a,a['editor_text']+'甲。').status_code==200
    assert save(c,root,b,b['editor_text']+'乙。').status_code==200
    conflict=save(c,root,a,a['editor_text']+'上書き。')
    assert conflict.status_code==409 and '入力は保持' in conflict.text
    assert details(c,root,P2)['editor_text'].endswith('甲。')
    assert details(c,root,P3)['editor_text'].endswith('乙。')
    assert c.get(root+'/export').status_code==200
    assert confirm(c,root,P2,token=a['token']).status_code==409


def test_structure_uses_chapter_token_not_global_revision(session):
    c,create=session;root=create();d=details(c,root,P2);other=details(c,root,'chapter0002-p00002')
    assert save(c,root,other,other['editor_text']+'追記。').status_code==200
    payload={'revision':d['revision'],'expected_token':d['token'],'expected_chapter_token':d['chapter_token'],'action':'insert','paragraph_id':P2,'text':'新段落'}
    assert c.post(root+'/structure',json=payload).status_code==200
    assert c.post(root+'/structure',json=payload).status_code==409


def test_confirmation_and_update_skip_ai_independently_and_reset_keeps_edits(session,mock_ai):
    c,create=session;root=create()
    assert confirm(c,root).status_code==200
    finish(job(c,root,skip_confirmed=True));assert not mock_ai
    assert c.post(root+'/review/reset',json={'scope':'paragraph','paragraph_id':P2,'target':'body'}).status_code==200
    finish(job(c,root,skip_confirmed=True));assert len(mock_ai)==1
    assert edit(c,root,P2,details(c,root)['editor_text']+'追記。').status_code==200
    assert details(c,root)['review_state']['body']['confirmed']
    before=details(c,root)['editor_text'];history=c.get(root+'/history').json()
    assert c.post(root+'/review/reset',json={'scope':'book','target':'both'}).status_code==200
    assert not details(c,root)['review_state']['body']['confirmed']
    assert details(c,root)['editor_text']==before and c.get(root+'/history').json()==history
    # Body confirmation leaves ruby eligible; no ruby is sent after its own confirmation.
    assert confirm(c,root,P1).status_code==200
    mock_ai.clear();finish(job(c,root,paragraph_id=P1,skip_confirmed=True))
    assert [p['query_type'] for p in mock_ai]==['ruby']
    assert confirm(c,root,P1,'ruby',0).status_code==200
    mock_ai.clear();finish(job(c,root,paragraph_id=P1,skip_confirmed=True));assert not mock_ai


def long_book():
    return changed({'EPUB/chapter1.xhtml':('<html xmlns="http://www.w3.org/1999/xhtml"><head><title>長文</title></head><body><p>'+('長い本文を読みます。'*40)+'</p><p>別段落。</p></body></html>').encode()})


def test_sentence_reviews_aggregate_and_omit_confirmed_sentences_from_queries(session,mock_ai):
    c,create=session;root=create(long_book());d=details(c,root,P1)
    assert d['unit_mode']=='sentence' and len(d['sentences'])==40
    assert confirm(c,root,P1,index=0).status_code==200
    s=details(c,root,P1)['review_state']['body'];assert s['done']==1 and not s['confirmed']
    mock_ai.clear();finish(job(c,root,paragraph_id=P1,skip_confirmed=True))
    assert sum(len(q['units']) for q in mock_ai)==39
    assert all('start' not in u for q in mock_ai for u in q['units'])
    for i in range(1,40):assert confirm(c,root,P1,index=i).status_code==200
    assert details(c,root,P1)['review_state']['body']['confirmed']
    assert c.post(root+'/review/reset',json={'scope':'chapter','chapter_id':'chapter0001','target':'body'}).status_code==200
    assert details(c,root,P1)['review_state']['body']['done']==0


def test_insert_preserves_anchor_and_shifted_ids_split_merge_reset_only_affected(session):
    c,create=session;root=create()
    for pid in (P1,P2,P3):assert confirm(c,root,pid).status_code==200
    d=details(c,root,P2)
    r=c.post(root+'/structure',json={'revision':0,'action':'insert','paragraph_id':P2,'text':'新段落。','position':'before','expected_chapter_token':d['chapter_token']})
    assert r.status_code==200,r.text
    added=r.json()['focus_paragraph_id']
    assert not details(c,root,added)['review_state']['body']['confirmed']
    assert all(details(c,root,p)['review_state']['body']['confirmed'] for p in (P1,P2,P3))
    d=details(c,root,P2)
    assert c.post(root+'/structure',json={'revision':d['revision'],'action':'split','paragraph_id':P2,'offset':11,'expected_chapter_token':d['chapter_token']}).status_code==200
    assert not details(c,root,P2)['review_state']['body']['confirmed']
    assert details(c,root,P3)['review_state']['body']['confirmed']


def test_confirmation_while_request_inflight_discards_incoming_result(session,mock_ai,monkeypatch):
    c,create=session;root=create();good=PROVIDERS['ollama'].generate
    def generate(*args):
        assert confirm(c,root).status_code==200
        return good(*args)
    monkeypatch.setattr(PROVIDERS['ollama'],'generate',generate)
    finish(job(c,root,skip_confirmed=True));assert state(c,root)['results']==[]


def test_confirmation_before_queued_request_prevents_call(session,mock_ai):
    c,create=session;root=create();ident=job(c,root,skip_confirmed=True)
    assert confirm(c,root).status_code==200
    finish(ident);assert not mock_ai and state(c,root)['jobs'][0]['done']==1


def test_ruby_add_delete_preserve_body_export_backup_and_no_structural_undo(session):
    c,create=session;root=create();d=details(c,root);text=d['editor_text']
    assert confirm(c,root).status_code==200
    added=ruby_op(c,root,'add',start=0,end=2,reading='きょう')
    assert added.status_code==200,added.text
    now=details(c,root);assert now['editor_text']==text
    assert now['rubies'][0]['base']=='今日' and now['rubies'][0]['readings']==['きょう']
    assert now['review_state']['body']['confirmed'] and now['review_state']['ruby']['confirmed']
    assert not added.json()['edit_state']['can_undo']
    assert c.post(root+'/undo',json={'revision':1}).status_code==409
    # Subsequent ordinary edits can still be undone without removing the new ruby.
    assert save(c,root,now,text+'追加。').status_code==200
    assert c.post(root+'/undo',json={'revision':2}).status_code==200
    assert details(c,root)['editor_text']==text and details(c,root)['rubies']
    backup=c.get(root+'/project/export').content
    imported=c.post('/api/projects/import',files={'file':('ruby.eproof',backup)})
    assert imported.status_code==200,imported.text
    other='/api/books/'+imported.json()['id']
    assert details(c,other)['rubies']==details(c,root)['rubies']
    deleted=ruby_op(c,root,'delete',index=0);assert deleted.status_code==200,deleted.text
    assert details(c,root)['editor_text']==text and details(c,root)['rubies']==[]
    assert details(c,root)['review_state']['body']['confirmed'] is False # preceding Undo reset the affected review
    assert c.get(root+'/export').status_code==200
    assert c.post('/api/projects/import',files={'file':('delete.eproof',c.get(root+'/project/export').content)}).status_code==200


def test_ruby_add_validates_overlap_empty_reading_and_stale_token(session):
    c,create=session;root=create();d=details(c,root,P1)
    for args in ({'start':0,'end':2,'reading':'よみ'},{'start':3,'end':5,'reading':' '},{'start':3,'end':500,'reading':'よみ'},{'start':3,'end':4,'reading':'\x00'}):
        assert ruby_op(c,root,'add',pid=P1,**args).status_code==422
    assert save(c,root,d,d['editor_text']+'追加。').status_code==200
    assert c.post(root+f'/paragraphs/{P1}/ruby-structure',json={'revision':0,'expected_token':d['token'],'action':'delete','index':0}).status_code==409


@pytest.mark.parametrize('items,expected',[
    ([{'start':1,'original':'汽','replacement':'気'},{'start':4,'original':'7','replacement':''}],2),
    ([{'start':1,'original':'汽','replacement':None}],1),
    ([{'start':0,'original':'天汽と','replacement':None}],0),
    ([{'start':0,'original':'天汽','replacement':None},{'start':2,'original':'と','replacement':None}],0),
    ([{'start':0,'original':'不存在','replacement':None}],0),
    ([{'start':1,'original':None,'replacement':None}],0),
])
def test_body_findings_are_exact_short_independent_locations(items,expected):
    p={'paragraph_id':'p','text':'天汽と字7。','rubies':[],'previous':'','next':''};q=next(queries.queries(p,1200))
    values,issues=queries.assess(json.dumps({'paragraph_id':'p','findings':items}),p,q)
    assert len(values)==expected
    assert bool(issues)==(expected==0)
    assert all(len(v['original'])<=2 for v in values)


@pytest.mark.parametrize('exception,message',[(base.httpx.ConnectError,'接続エラー'),(base.httpx.ConnectTimeout,'接続エラー'),(base.httpx.ReadTimeout,'処理の長期化、サービス停止、通信断')])
def test_ai_connection_and_response_failures_have_distinct_messages(monkeypatch,exception,message):
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):raise exception('secret details')
        def __exit__(self,*args):pass
    monkeypatch.setattr(base.httpx,'Client',Client)
    with pytest.raises(ValueError,match=message) as exc:
        base.request({'url':'http://localhost:11434','provider':'ollama'},'POST','/api/chat')
    assert 'secret details' not in str(exc.value)
