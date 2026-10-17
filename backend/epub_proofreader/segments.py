"""Lossless proofreading units; sentence boundaries never cut a ruby base."""
from lxml import etree
THRESHOLD = 300
READINGS = {'rt','rp','rtc'}
ENDINGS = set('。！？!?')
CLOSERS = set('」』）】〉》〕］｝”’\"\'')

def name(node):
    return etree.QName(node).localname if isinstance(node.tag,str) else ''

def layout(element):
    text_parts=[]; slots=[]; rubies=[]; offset=0
    def slot(node,field):
        nonlocal offset
        text=getattr(node,field) or ''
        slots.append((node,field,offset,offset+len(text)))
        text_parts.append(text);offset+=len(text)
    def walk(node,in_ruby=False):
        if not isinstance(node.tag,str) or name(node) in READINGS:return
        start=offset
        slot(node,'text')
        for child in node:
            walk(child,in_ruby or name(node)=='ruby')
            slot(child,'tail')
        if name(node)=='ruby':rubies.append((node,start,offset))
    walk(element)
    return ''.join(text_parts),slots,rubies

def sentences(text,protected=()):
    if not text.strip():return []
    results=[];start=0;index=0
    while index<len(text):
        if text[index] not in ENDINGS:index+=1;continue
        end=index+1
        while end<len(text) and text[end] in ENDINGS:end+=1
        quote_end=end
        while end<len(text) and text[end] in CLOSERS:end+=1
        # Keep common quoted speech plus its reporting clause together.
        if end>quote_end and (text.startswith('と',end) or text.startswith('って',end)):
            index=end;continue
        while end<len(text) and text[end].isspace():end+=1
        if any(left<end<right for left,right in protected):
            index=end;continue
        results.append({'index':len(results),'start':start,'end':end,'text':text[start:end]})
        start=end;index=end
    if start<len(text):
        if text[start:].strip():results.append({'index':len(results),'start':start,'end':len(text),'text':text[start:]})
        elif results:results[-1]['end']=len(text);results[-1]['text']+=text[start:]
    return results or [{'index':0,'start':0,'end':len(text),'text':text}]

def describe(element):
    text,slots,rubies=layout(element)
    spans=sentences(text,[(start,end) for _,start,end in rubies])
    count=sum(not char.isspace() for char in text)
    return {'character_count':count,'sentences':spans,'unit_mode':'sentence' if count>=THRESHOLD else 'paragraph','structure_editable':name(element)=='p'},slots,rubies
