from .base import Reply,request,schema

def generate(e,system,prompt):
    r=request(e,'POST','/v1beta/models/'+e['model'].removeprefix('models/')+':generateContent',headers={'x-goog-api-key':e['api_key']},json={'systemInstruction':{'parts':[{'text':system}]},'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'responseFormat':{'text':{'mimeType':'application/json','schema':schema(e)}},'maxOutputTokens':e['max_output_tokens'],'temperature':0}})
    u=r.get('usageMetadata',{});return Reply(''.join(p.get('text','') for c in r.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if not p.get('thought')),u.get('promptTokenCount'),(u.get('candidatesTokenCount',0)+u.get('thoughtsTokenCount',0)) if 'candidatesTokenCount' in u else None)
def models(e):return [m['name'].removeprefix('models/') for m in request(e,'GET','/v1beta/models',headers={'x-goog-api-key':e['api_key']}).get('models',[])]
