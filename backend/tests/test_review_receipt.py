import copy
from test_editing import session,details,P1,P2,edit
from test_ai import mock_ai,job,finish,state
from epub_proofreader import app as module,editing,projects

def request(c,root,pid=P2,**extra):
    return c.post(root+'/paragraphs/'+pid+'/review',json={'target':'body','expected_token':details(c,root,pid)['token'],'compact':True,**extra})

def test_compact_confirmation_only_changes_review_metadata_and_ai_flags(session,mock_ai,monkeypatch):
    c,create=session;root=create();finish(job(c,root));ident=root.split('/')[-1];d=details(c,root)
    with module.database() as con:
        before=editing.state(con,ident);files=list(con.execute('SELECT path,content FROM editing_files WHERE book_id=?',(ident,)))
    def forbidden(*args,**kwargs):raise AssertionError('Confirmation rebuilt a book snapshot or EPUB')
    original=editing.paragraph_details;calls=[]
    def tracked(*args,**kwargs):calls.append(kwargs);return original(*args,**kwargs)
    with monkeypatch.context() as m:
        m.setattr(module,'snapshot',forbidden);m.setattr(editing,'repack',forbidden);m.setattr(editing,'paragraph_details',tracked)
        r=c.post(root+'/paragraphs/'+P2+'/review',json={'target':'body','expected_token':d['token'],'compact':True})
    assert r.status_code==200,r.text
    receipt=r.json();assert receipt['revision']==0 and receipt['review_state']['body']['confirmed']
    assert 'chapters' not in receipt and 'book' not in receipt and 'history' not in receipt
    assert receipt['reviewed_ids'] and all(k.get('include_chapter_token') is False for k in calls)
    assert len(calls)==1
    with module.database() as con:
        after=editing.state(con,ident);assert after==before
        assert list(con.execute('SELECT path,content FROM editing_files WHERE book_id=?',(ident,)))==files
    assert state(c,root)['results'][0]['status']=='reviewed'
    assert request(c,root).json()['reviewed_ids']==receipt['reviewed_ids']

def test_confirmation_preserves_manual_draft_in_the_same_transaction(session):
    c,create=session;root=create();d=details(c,root)
    draft={'paragraphToken':d['token'],'revision':0,'text':'未保存の手修正。','rubies':{},'reason':'原本との照合','paragraphId':P2,'before':d['editor_text']}
    key='body:'+P2+':all'
    r=request(c,root,draft_patch={'key':key,'expected':None,'value':draft})
    assert r.status_code==200,r.text
    assert r.json()['project']['drafts'][key]==draft
    assert details(c,root)['editor_text']==d['editor_text']
    assert r.json()['revision']==0

def test_conflicting_draft_or_stale_body_does_not_mark_confirmed(session):
    c,create=session;root=create();d=details(c,root);key='body:'+P2+':all';ident=root.split('/')[-1]
    draft={'revision':0,'text':'別画面の入力','rubies':{},'reason':'原本との照合','paragraphId':P2,'before':d['editor_text']}
    with module.database() as con:
        meta=projects.read(con,ident);meta['drafts'][key]=draft;projects.write(con,ident,meta)
    r=request(c,root,draft_patch={'key':key,'expected':None,'value':None})
    assert r.status_code==409 and not details(c,root)['review_state']['body']['confirmed']
    r=request(c,root,draft_patch={'key':'body:'+P1+':all','expected':None,'value':None})
    assert r.status_code==409
    assert edit(c,root,P2,'更新後の本文。').status_code==200
    previous=c.get(root+'/project').json()
    r=c.post(root+'/paragraphs/'+P2+'/review',json={'compact':True,'target':'body','expected_token':d['token']})
    assert r.status_code==409 and c.get(root+'/project').json()==previous

def test_compact_ruby_confirmation_keeps_the_reading_and_legacy_api(session):
    c,create=session;root=create();d=details(c,root,P1)
    r=request(c,root,P1,target='ruby',index=0)
    assert r.status_code==200,r.text
    assert r.json()['review_state']['ruby']['confirmed']
    assert details(c,root,P1)['rubies']==d['rubies']
    legacy=c.post(root+'/paragraphs/'+P2+'/review',json={'target':'body','expected_token':details(c,root)['token']})
    assert legacy.status_code==200 and legacy.json()['chapters']
