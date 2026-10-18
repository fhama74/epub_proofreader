"""Short sentence IDs in, exact text search out; models never count characters."""
import json
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from ..segments import sentences

class Candidate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    i:int=Field(ge=0,strict=True)
    o:str=Field(min_length=1,max_length=3)
    r:str|None=Field(max_length=4000)
class Finding(Candidate):
    r:str|None=Field(default=None,max_length=4000)
class Result(BaseModel):
    model_config=ConfigDict(extra='forbid')
    findings:list[Candidate]=Field(max_length=100)


def slots(q,p=None):
    entries=q['_members'] if q.get('_batch') else [(p,q)]
    return [(paragraph,part,u) for paragraph,part in entries for u in part['_units']]


def wire(q):
    entries=q['_members'] if q.get('_batch') else [(None,q)]
    groups=[];i=0
    for _,part in entries:
        units=[]
        for u in part['_units']:
            units.append({'i':i,'text':u['text']});i+=1
        groups.append({'paragraph_id':part['paragraph_id'],'units':units})
    value={'query_type':'body',**({'paragraphs':groups} if q.get('_batch') else groups[0])}
    for key in ('previous','next'):
        if q.get(key):value[key]=q[key]
    return value


def matches(text,original):
    values=[];at=text.find(original)
    while at>=0:
        values.append(at);at=text.find(original,at+1)
    return values


def locate(s,p,part,unit):
    from .queries import seed
    if s.o not in unit['text']:raise ValueError('o（指摘原文）が指定した文にありません。入力の文から1〜3文字をそのまま返してください。')
    begin=part['_source']['offset']+unit['start']
    spans=sentences(p['text'],[(r['start'],r['end']) for r in p['rubies']])
    sentence=next((x for x in spans if x['start']<=begin<x['end']),None)
    if sentence is None:raise ValueError('指定した文を特定できません。')
    positions=matches(sentence['text'],s.o)
    if s.r==s.o:return []
    values=[]
    for at in positions:
        a=sentence['start']+at;b=a+len(s.o)
        d=seed(part,a,b,s.o,'AIが本文の異常を検知しました。','unnatural',0)
        d['match_count']=len(positions)
        if len(positions)>1:
            d['suggested_replacement']=s.r
            d['proposal_note']=f'同じ文に{len(positions)}箇所あります。すべて赤字で表示します。原本と照合して修正する箇所を選んでください。'
        elif s.r is not None and any(r['start']<b and r['end']>a for r in p['rubies']):
            d['proposal_note']='親文字を含む指摘です。ルビの訂正画面で原本と照合してください。'
        else:d['replacement']=s.r
        values.append(d)
    return values


def assess(reply,p,q):
    from .queries import validation_feedback,short_findings
    table=slots(q,p);members={paragraph['paragraph_id'] for paragraph,_,_ in table}
    try:decoded=json.loads(reply)
    except (ValueError,TypeError):raise ValueError('AI出力のJSONが不完全または不正です。候補を絞り、閉じ括弧まで含むJSONを返してください。') from None
    if not isinstance(decoded,dict) or set(decoded)!={'findings'} or not isinstance(decoded['findings'],list):
        raise ValueError('本文の返答はfindings配列だけのJSONにしてください。各項目はi（文ID）・o（1〜3文字）・r（任意の訂正案/null）です。')
    if len(decoded['findings'])>100:
        raise ValueError(f'候補上限100件に対し{len(decoded["findings"])}件あります。正常な文字は列挙せず、異常が確かな候補を100件以内に絞ってください。')
    values=[];issues={}
    for number,raw in enumerate(decoded['findings']):
        target=None
        try:
            finding=Finding.model_validate(raw)
            if finding.i>=len(table):raise ValueError(f'i（文ID）={finding.i}は入力にありません。入力の文ID（0〜{len(table)-1}）をそのまま使ってください。')
            paragraph,part,unit=table[finding.i];target=paragraph['paragraph_id']
            if finding.o not in unit['text']:
                other=[i for i,(_,_,u) in enumerate(table) if finding.o in u['text']]
                # Echo only validated IDs and short originals, never unknown
                # response fields. The text is from this request's snapshot.
                evidence={'i':finding.i,'o':finding.o,'一致する別の文ID':other,'指定した文の原文':unit['text'][:400]}
                raise ValueError('o（指摘原文）が指定した文にありません。iとoを確認し、原文を変えずに1〜3文字コピーしてください。検証対象：'+json.dumps(evidence,ensure_ascii=False))
            values.extend({**d,**({'_paragraph_id':target} if q.get('_batch') else {})} for d in locate(finding,paragraph,part,unit))
        except (ValidationError,ValueError) as exc:
            # Invalid value/type may still have a valid ID; fail only its owner.
            i=raw.get('i') if isinstance(raw,dict) else None
            if type(i) is int and 0<=i<len(table):target=table[i][0]['paragraph_id']
            message=validation_feedback(exc,'body') if isinstance(exc,ValidationError) else str(exc)
            for pid in ([target] if target else members):issues.setdefault(pid,[]).append(f'候補{number+1}: {message}')
    before=values;values,bad=short_findings(values)
    for index in bad:issues.setdefault(before[index].get('_paragraph_id',p['paragraph_id']),[]).append('連続4文字以上の指摘は採用しません。')
    return values,issues if q.get('_batch') else issues.get(p['paragraph_id'],[])
