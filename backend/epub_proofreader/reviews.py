"""Content-bound human review marks; paragraph IDs survive insertions and deletions."""
import hashlib
import json
from . import editing, projects


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def summary(meta, details, target='body'):
    marks=meta.get('reviews',{}).get(details['id'],{}).get(target,{})
    if target=='body':
        units=details['sentences'] if details['unit_mode']=='sentence' else [{'text':details['editor_text']}]
        units=units or [{'text':details['editor_text']}]
        whole=digest(details['editor_text'])
        legacy=details['id'] not in meta.get('reviews',{}) and meta['statuses'].get(details['id'])=='human_checked'
        full=marks.get('all')==whole or legacy
        checked=[full or marks.get(str(i))==digest(u['text']) for i,u in enumerate(units)]
    else:
        units=details['rubies']
        whole=digest([details['editor_text'],[(r['base'],r['readings']) for r in units]])
        full=marks.get('all')==whole
        checked=[full or marks.get(str(i))==digest([details['editor_text'],r['base'],r['readings']]) for i,r in enumerate(units)]
    return {'total':len(units),'done':sum(checked),'confirmed':all(checked),'units':checked}


def record_details(record):
    text=''.join(s['text'] for s in record['sentences'])
    if not record['sentences']:
        from lxml import etree
        from .epub import base_text
        xml=record.get('current_xml') or record.get('original_xml')
        text=base_text(etree.fromstring(xml.encode()),strip=False) if xml else record.get('text','')
    return {**record,'editor_text':text}


def both(meta,details):
    return {target:summary(meta,details,target) for target in ('body','ruby')}


def mark(con,book_id,paragraph_id,target='body',index=None,expected_token=None):
    value=editing.state(con,book_id)
    d=editing.paragraph_details(editing.working_model(value),paragraph_id,value['revision'])
    if expected_token is not None and expected_token!=d['token']:
        raise editing.EditConflict('この段落が変更されています。入力は保持したまま最新の段落を確認してください。')
    meta=projects.read(con,book_id)
    row=meta.setdefault('reviews',{}).setdefault(paragraph_id,{})
    # Preserve an existing whole-paragraph confirmation when marking ruby only.
    if meta['statuses'].get(paragraph_id)=='human_checked' and not row.get('body'):
        row['body']={'all':digest(d['editor_text'])}
    marks=row.setdefault(target,{})
    if target=='body':
        if index is None or d['unit_mode']!='sentence':
            marks['all']=digest(d['editor_text']);a,b=0,len(d['editor_text'])
        else:
            if not 0<=index<len(d['sentences']):raise editing.EditConflict('文の構成が変わっています。段落を読み込み直してください。')
            s=d['sentences'][index];marks[str(index)]=digest(s['text']);a,b=s['start'],s['end']
    else:
        if index is None:
            marks['all']=digest([d['editor_text'],[(r['base'],r['readings']) for r in d['rubies']]])
        else:
            if not 0<=index<len(d['rubies']):raise editing.EditConflict('ルビの構成が変わっています。')
            r=d['rubies'][index];marks[str(index)]=digest([d['editor_text'],r['base'],r['readings']])
    for ident,raw in con.execute("SELECT id,data FROM ai_results WHERE book_id=? AND paragraph_id=? AND status IN ('pending','held','undone')",(book_id,paragraph_id)).fetchall():
        item=json.loads(raw)
        covered=(item['target']=='text' and a<=item['start']<=item['end']<=b) if target=='body' else item['target']=='ruby' and (index is None or item.get('ruby_index')==index)
        if covered:con.execute("UPDATE ai_results SET status='reviewed',updated_at=? WHERE id=?",(editing.timestamp(),ident))
    meta['statuses'][paragraph_id]='human_checked' if summary(meta,d)['confirmed'] else 'review'
    meta['version']+=1;projects.write(con,book_id,meta)
    return meta


def query_needed(con,book_id,p,q,skip=True):
    if not skip:return q
    try:d=editing.paragraph_details(editing.working_model(editing.state(con,book_id)),p['paragraph_id'],0,include_tokens=False)
    except ValueError:return None
    # A queued snapshot no longer represents this paragraph. Do not send obsolete text.
    if d['editor_text']!=p['text']:return None
    meta=projects.read(con,book_id);state=summary(meta,d,'body' if q['query_type']=='body' else 'ruby')
    if state['confirmed']:return None
    if q['query_type']=='ruby':
        rubies=[r for r in q['rubies'] if r['ruby_index']>=len(state['units']) or not state['units'][r['ruby_index']]]
        return {**q,'rubies':rubies,'_source':{**q['_source'],'rubies':[r for r in q['_source']['rubies'] if r['index'] in {x['ruby_index'] for x in rubies}]}} if rubies else None
    if d['unit_mode']!='sentence':return q
    units=[u for u in q['_units'] if not any(s['start']<=q['_source']['offset']+u['start']<s['end'] and state['units'][s['index']] for s in d['sentences'])]
    ids={u['index'] for u in units}
    return {**q,'_units':units,'units':[u for u in q['units'] if u['unit_id'] in ids]} if units else None


def allows_result(con,book_id,pid,item):
    try:d=editing.paragraph_details(editing.working_model(editing.state(con,book_id)),pid,0,include_tokens=False)
    except ValueError:return False
    meta=projects.read(con,book_id);target='body' if item['target']=='text' else 'ruby';s=summary(meta,d,target)
    if s['confirmed']:return False
    if target=='ruby':return item['ruby_index']>=len(s['units']) or not s['units'][item['ruby_index']]
    return not any(sentence['start']<=item['start']<sentence['end'] and s['units'][sentence['index']] for sentence in d['sentences']) if d['unit_mode']=='sentence' else True
