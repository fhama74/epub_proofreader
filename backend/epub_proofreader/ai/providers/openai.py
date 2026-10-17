from .base import Reply,request,schema

def generate(e,system,prompt):
    payload={'model':e['model'],'instructions':system,'input':prompt,'max_output_tokens':e['max_output_tokens'],'store':False,'text':{'format':{'type':'json_schema','name':'proofreading','strict':True,'schema':schema(e)}}}
    # Only explicitly supported models receive none; other models keep their defaults.
    if e['model']=='gpt-6-luna' or e['model'].startswith('gpt-6-luna-'):
        payload['reasoning']={'effort':'none'}
    r=request(e,'POST','/v1/responses',headers={'Authorization':'Bearer '+e['api_key']},json=payload)
    u=r.get('usage',{});return Reply(''.join(c.get('text','') for o in r.get('output',[]) for c in o.get('content',[]) if c.get('type')=='output_text'),u.get('input_tokens'),u.get('output_tokens'))
def models(e):return [m['id'] for m in request(e,'GET','/v1/models',headers={'Authorization':'Bearer '+e['api_key']}).get('data',[])]
