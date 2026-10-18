"""Bounded, same-chapter batches with paragraph-owned findings and no clean rows."""
import json
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from . import queries as single

class BodyCandidate(single.TextCandidate):
    paragraph_id:str
class RubyCandidate(single.RubyCandidate):
    paragraph_id:str
class BodyFinding(single.TextFinding):
    paragraph_id:str
class RubyFinding(single.RubyFinding):
    paragraph_id:str
class BodyResult(BaseModel):
    model_config=ConfigDict(extra='forbid')
    findings:list[BodyCandidate]=Field(max_length=100)
class RubyResult(BaseModel):
    model_config=ConfigDict(extra='forbid')
    findings:list[RubyCandidate]=Field(max_length=100)
class Envelope(BaseModel):
    model_config=ConfigDict(extra='forbid')
    findings:list[dict]=Field(max_length=100)


def groups(items,count,size):
    group=[];length=0
    for p in items:
        if group and (len(group)>=count or p['chapter_id']!=group[0]['chapter_id'] or length+len(p['text'])>size):
            yield group;group=[];length=0
        group.append(p);length+=len(p['text'])
    if group:yield group


def plans(items,count,size):
    for group in groups(items,count,size):
        by_type={'body':[],'ruby':[]}
        for p in group:
            for q in single.queries(p,size):
                if q['query_type']=='ruby' and len(q['rubies'])>40:
                    for start in range(0,len(q['rubies']),40):
                        rubies=q['rubies'][start:start+40];ids={r['ruby_index'] for r in rubies}
                        part={**q,'rubies':rubies,'_source':{**q['_source'],'rubies':[r for r in q['_source']['rubies'] if r['index'] in ids]}}
                        by_type['ruby'].append((p,part))
                else:by_type[q['query_type']].append((p,q))
        for kind,entries in by_type.items():
            members=[];length=0;rubies=0
            for p,q in entries:
                n=len(q['_source']['target']);r=len(q.get('rubies',[]))
                if members and (p['paragraph_id'] in {a['paragraph_id'] for a,_ in members} or length+n>size or rubies+r>40):
                    yield pack(kind,members);members=[];length=0;rubies=0
                members.append((p,q));length+=n;rubies+=r
            if members:yield pack(kind,members)


def pack(kind,members):
    paragraphs=[{k:v for k,v in q.items() if not k.startswith('_') and k not in {'previous','next','query_type'}} for _,q in members]
    return {'_batch':True,'query_type':kind,'_members':members,'paragraphs':paragraphs,'previous':members[0][1]['previous'],'next':members[-1][1]['next']}


def system(q,policy=None):return single.system(q,policy)

def output_schema(q):
    if q['query_type']=='body':
        from .body import Result
        return Result.model_json_schema()
    return RubyResult.model_json_schema()


def assess(reply,q):
    if q['query_type']=='body':
        try:decoded=json.loads(reply)
        except (ValueError,TypeError):
            from .body import assess as assess_body
            return assess_body(reply,q['_members'][0][0],q)
        if isinstance(decoded,dict) and isinstance(decoded.get('findings'),list) and (not decoded['findings'] or any(isinstance(r,dict) and ('i' in r or 'o' in r) for r in decoded['findings'])):
            from .body import assess as assess_body
            return assess_body(reply,q['_members'][0][0],q)
    members={p['paragraph_id']:(p,part) for p,part in q['_members']};accepted=[];issues={}
    try:response=Envelope.model_validate_json(reply)
    except ValidationError:raise ValueError('まとめ検査のJSON構造が不正です。findings配列だけを返してください。') from None
    for i,raw in enumerate(response.findings):
        pid=raw.get('paragraph_id')
        if not isinstance(pid,str) or pid not in members:
            for target in members:issues.setdefault(target,[]).append(f'候補{i+1}: 入力にない段落IDです。')
            continue
        try:
            model=BodyFinding if q['query_type']=='body' else RubyFinding
            value=model.model_validate(raw);p,part=members[pid]
            finding=single.body_finding(value,p,part) if q['query_type']=='body' else single.ruby_finding(value,p,part)
            if finding is not None:accepted.append({**finding,'_paragraph_id':pid})
        except ValidationError as exc:issues.setdefault(pid,[]).append(f'候補{i+1}: {single.validation_feedback(exc,q["query_type"])}')
        except ValueError as exc:issues.setdefault(pid,[]).append(f'候補{i+1}: {exc}')
    accepted,bad=single.short_findings(accepted)
    if bad:
        for pid in members:issues.setdefault(pid,[]).append('連続4文字以上の指摘は採用しません。')
    return accepted,issues
