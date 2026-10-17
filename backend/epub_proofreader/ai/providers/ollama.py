from .base import Reply,request,schema

def generate(e,system,prompt):
    r=request(e,'POST','/api/chat',json={'model':e['model'],'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],'stream':False,'think':False,'format':schema(e),'options':{'temperature':0,'num_predict':e['max_output_tokens']}})
    return Reply(r['message']['content'],r.get('prompt_eval_count'),r.get('eval_count'))
def models(e):return [m['name'] for m in request(e,'GET','/api/tags').get('models',[])]
