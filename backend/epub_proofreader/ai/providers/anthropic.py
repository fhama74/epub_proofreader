from .base import Reply,request,schema

def headers(e):return {'x-api-key':e['api_key'],'anthropic-version':'2023-06-01'}
def generate(e,system,prompt):
    r=request(e,'POST','/v1/messages',headers=headers(e),json={'model':e['model'],'system':system,'messages':[{'role':'user','content':prompt}],'max_tokens':e['max_output_tokens'],'output_config':{'format':{'type':'json_schema','schema':schema(e)}}})
    u=r.get('usage',{});return Reply(''.join(c.get('text','') for c in r.get('content',[]) if c.get('type')=='text'),u.get('input_tokens'),u.get('output_tokens'))
def models(e):return [m['id'] for m in request(e,'GET','/v1/models',headers=headers(e)).get('data',[])]
