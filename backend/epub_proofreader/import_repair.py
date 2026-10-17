"""Narrow, lossless recovery of numeric references split by jisui2epub TCY tags."""
import re

SPAN=rb'<span\s+class\s*=\s*(?:"tcy"|\'tcy\')\s*>[x0-9A-Fa-f]+</span\s*>'
BROKEN=re.compile(rb'&#(?:[x0-9A-Fa-f]|'+SPAN+rb')+;')
TAG=re.compile(rb'</?span\b[^>]*>')
# References inside attributes, comments, CDATA, declarations or PIs are not prose.
MARKUP=re.compile(rb'<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|<(?:(?:"[^"]*"|\'[^\']*\')|[^\'">])*>')
VALID=re.compile(rb'&#(?:[0-9]+|x[0-9a-fA-F]+);')

def repair_numeric_references(data,path):
    excluded=[m.span() for m in MARKUP.finditer(data)]
    fixes=[];ranges=[];index=0
    for match in BROKEN.finditer(data):
        start,end=match.span()
        while index<len(excluded) and excluded[index][1]<=start:index+=1
        if index<len(excluded) and excluded[index][0]<=start<excluded[index][1]:continue
        old=match.group();new=TAG.sub(b'',old)
        if old==new or not VALID.fullmatch(new):continue
        try:code=int(new[3:-1],16) if new.startswith(b'&#x') else int(new[2:-1])
        except ValueError:continue
        if not (code in (9,10,13) or 0x20<=code<=0xD7FF or 0xE000<=code<=0xFFFD or 0x10000<=code<=0x10FFFF):continue
        line=data.count(b'\n',0,start)+1
        fixes.append({'path':path,'line':line,'kind':'tcy_numeric_reference','before':old.decode('ascii'),'after':new.decode('ascii')})
        ranges.append((start,end,new))
    if not fixes:return data,[]
    result=data
    for start,end,new in reversed(ranges):result=result[:start]+new+result[end:]
    return result,fixes
