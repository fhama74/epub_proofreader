from .base import Reply,request,schema,ResponseFormatError
import json


def body_schema(e):
    value=schema(e)
    # A three-character bound is small enough for supported grammar parsers. Do not
    # pass large replacement/count bounds, which can reject the entire request.
    for definition in value.get('$defs',{}).values():
        props=definition.get('properties',{})
        if set(props)=={'i','o','r'}:props['o'].update(minLength=1,maxLength=3)
    return value


def generate(e,system,prompt):
    payload={'model':e['model'],'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],'stream':False,'think':False,'format':body_schema(e),'options':{'temperature':0,'num_predict':e['max_output_tokens']}}
    try:r=request(e,'POST','/api/chat',json=payload)
    except ValueError as exc:
        compatible=schema(e)
        if 'HTTP 400' not in str(exc) or payload['format']==compatible:raise
        # Old Ollama versions may reject even this small bound. Only retry the
        # rejected request; incoming candidates still undergo strict validation.
        payload={**payload,'format':compatible};r=request(e,'POST','/api/chat',json=payload)
    if not isinstance(r,dict) or not isinstance(r.get('message'),dict) or not isinstance(r['message'].get('content'),str):
        raise ResponseFormatError('AIの応答形式が不正です。Ollamaのmessage.contentがありません。',json.dumps(r,ensure_ascii=False))
    return Reply(r['message']['content'],r.get('prompt_eval_count'),r.get('eval_count'))


def models(e):return [m['name'] for m in request(e,'GET','/api/tags').get('models',[])]
