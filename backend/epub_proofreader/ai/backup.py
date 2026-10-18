"""Portable AI evidence, without credentials or executable/resumable jobs."""
import json,sqlite3
from uuid import uuid4
from pydantic import BaseModel,Field,ConfigDict
from .models import Engine,StoredSuggestion
from .prompts import Policy
from .engine_manager import OWNER
from ..epub import EpubError

class Archive(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version:int
    jobs:list[dict]=Field(max_length=5000)
    items:list[dict]=Field(max_length=100000)
    results:list[dict]=Field(max_length=100000)
    decisions:list[dict]=Field(max_length=200000)
    usage:list[dict]=Field(max_length=200000)
    cleared:list[dict]=Field(default_factory=list,max_length=100000)
TABLES={'jobs':('ai_jobs','id,book_id,owner_id,engine_id,config,scope,status,created_at,finished_at,request_id,budget,error'), 'items':('ai_items','job_id,ordinal,paragraph_id,chapter_id,payload,status,error'),'results':('ai_results','id,job_id,book_id,owner_id,engine_id,model_name,paragraph_id,chapter_id,data,source_hash,status,created_at,updated_at,command_id'),'decisions':('ai_decisions','id,result_id,owner_id,action,created_at'),'usage':('ai_usage','id,job_id,owner_id,input_tokens,output_tokens,cost,created_at'),'cleared':('ai_cleared_results','result_id')}

def export(con,book_id):
    previous=con.row_factory;con.row_factory=sqlite3.Row
    try:
        data={'schema_version':1}
        for key,(table,cols) in TABLES.items():
            clause='book_id=?' if key in {'jobs','results'} else 'job_id IN (SELECT id FROM ai_jobs WHERE book_id=?)' if key in {'items','usage'} else 'result_id IN (SELECT id FROM ai_results WHERE book_id=?)'
            data[key]=[dict(r) for r in con.execute(f'SELECT {cols} FROM {table} WHERE {clause}',(book_id,))]
        return data
    finally:con.row_factory=previous

def restore(con,book_id,data,value):
    try:
        archive=Archive.model_validate(data)
        if archive.schema_version!=1:raise ValueError()
        jobmap={r['id']:str(uuid4()) for r in archive.jobs};resultmap={r['id']:str(uuid4()) for r in archive.results};commands={c['id'] for c in value['commands']}
        if len(jobmap)!=len(archive.jobs) or len(resultmap)!=len(archive.results):raise ValueError()
        for key,(table,columns) in TABLES.items():
            for original in getattr(archive,key):
                if set(original)!=set(columns.split(',')):raise ValueError()
                r=dict(original)
                if key=='jobs':
                    raw=json.loads(r['config']);cfg=Engine(**raw).model_dump(exclude={'api_key'});
                    if 'prompt_policy' in raw:cfg['prompt_policy']=Policy.model_validate(raw['prompt_policy']).model_dump()
                    r.update(id=jobmap[r['id']],book_id=book_id,owner_id=OWNER,config=json.dumps(cfg),status='archived',request_id=str(uuid4()))
                elif key=='results':
                    suggestion=json.loads(r['data']);StoredSuggestion.model_validate({k:v for k,v in suggestion.items() if k!='ruby_before'})
                    if not isinstance(suggestion['start'],int) or not isinstance(suggestion['end'],int) or not 0<=suggestion['start']<=suggestion['end']:raise ValueError()
                    if r['command_id'] and r['command_id'] not in commands:raise ValueError()
                    if r['status'] not in {'pending','approved','rejected','held','reviewed'}:raise ValueError()
                    r.update(id=resultmap[r['id']],book_id=book_id,owner_id=OWNER)
                elif key=='decisions':
                    if r['action'] not in {'approve','reject','hold','confirm'}:raise ValueError()
                    r.update(id=str(uuid4()),result_id=resultmap[r['result_id']],owner_id=OWNER)
                elif key=='cleared':r.update(result_id=resultmap[r['result_id']])
                elif key=='usage':r.update(id=str(uuid4()),owner_id=OWNER)
                if 'job_id' in r:r['job_id']=jobmap[r['job_id']]
                # Snapshot jobs stay archived: imported files can never initiate network calls.
                cols=columns.split(',');con.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in cols)})",[r[k] for k in cols])
                if key=='results':
                    from .. import unit_store
                    from .proofreading import fingerprint
                    if unit_store.enabled(con,book_id):
                        try:d=unit_store.direct_details(con,book_id,r['paragraph_id'])
                        except ValueError:continue
                        if fingerprint(d)==r['source_hash']:con.execute('INSERT INTO ai_result_units VALUES (?,?,?,?,?)',(r['id'],r['paragraph_id'],d['unit_version'],suggestion['start'],suggestion['end']))
    except (ValueError,TypeError,KeyError,sqlite3.Error):raise EpubError('AI校正バックアップの形式・関連IDが不正です。') from None
