"""Resolve EPUB writing-mode from local CSS only; never fetch external resources."""
from collections import Counter
import re
import cssselect2
import tinycss2

MODES={'horizontal-tb':'horizontal-tb','vertical-rl':'vertical-rl','vertical-lr':'vertical-lr',
       'lr-tb':'horizontal-tb','rl-tb':'horizontal-tb','tb-rl':'vertical-rl','tb-lr':'vertical-lr'}
PROPERTIES={'writing-mode','-epub-writing-mode','-webkit-writing-mode'}

def chapter_mode(tree,path,files,resolve):
    matcher=cssselect2.Matcher();order=0
    def declarations(tokens):
        return [(d.important,MODES.get(tinycss2.serialize(d.value).strip().lower(),tinycss2.serialize(d.value).strip().lower()))
                for d in tinycss2.parse_declaration_list(tokens,skip_comments=True,skip_whitespace=True)
                if d.type=='declaration' and d.lower_name in PROPERTIES]
    def rules(items,base,stack=()):
        nonlocal order
        for rule in items:
            if rule.type=='qualified-rule':
                try:selectors=cssselect2.compile_selector_list(rule.prelude)
                except cssselect2.SelectorError:continue
                values=declarations(rule.content)
                for important,value in values:
                    if value not in MODES.values() and value not in {'inherit','initial','unset','revert'}:continue
                    order+=1
                    for selector in selectors:
                        if selector.pseudo_element is None:matcher.add_selector(selector,(important,order,value))
            elif rule.type=='at-rule' and rule.lower_at_keyword=='import':
                tokens=[t for t in rule.prelude if t.type not in {'whitespace','comment'}]
                if not tokens:continue
                first=tokens[0];href=first.value if first.type in {'string','url'} else None
                if first.type=='function' and first.lower_name=='url':
                    args=[t for t in first.arguments if t.type not in {'whitespace','comment'}]
                    if len(args)==1 and args[0].type in {'string','ident'}:href=args[0].value
                media=tinycss2.serialize(tokens[1:]).strip()
                if href and screen(media):sheet(href,base,stack)
            elif rule.type=='at-rule' and rule.content is not None and rule.lower_at_keyword=='media' and screen(tinycss2.serialize(rule.prelude)):
                rules(tinycss2.parse_rule_list(rule.content,skip_comments=True,skip_whitespace=True),base,stack)
    def screen(media):
        # Width-dependent media needs a real viewport; use unconditional screen/all rules.
        return not media or any(part.strip().lower() in {'all','screen','only screen'} for part in media.split(','))
    def sheet(href,base,stack=()):
        try:target=resolve(base,href)
        except ValueError:return
        if target in stack or len(stack)>=12 or target not in files:return
        parsed,_=tinycss2.parse_stylesheet_bytes(files[target],skip_comments=True,skip_whitespace=True)
        rules(parsed,target,(*stack,target))
    for node in tree.iter():
        name=node.tag.rsplit('}',1)[-1] if isinstance(node.tag,str) else ''
        if name=='link' and 'stylesheet' in node.get('rel','').split() and 'alternate' not in node.get('rel','').split() and node.get('disabled') is None and screen(node.get('media','')):
            sheet(node.get('href',''),path)
        elif name=='style' and screen(node.get('media','')):
            rules(tinycss2.parse_stylesheet(''.join(node.itertext()),skip_comments=True,skip_whitespace=True),path)
    modes={};specified={};weights=Counter();body_mode=None
    for wrapper in cssselect2.ElementWrapper.from_xml_root(tree).iter_subtree():
        parent=modes.get(wrapper.parent,'horizontal-tb');choices=[]
        for specificity,_,pseudo,(important,position,value) in matcher.match(wrapper):
            choices.append((important,(0,*specificity),position,value))
        for position,(important,value) in enumerate(declarations(wrapper.etree_element.get('style',''))):
            if value in MODES.values() or value in {'inherit','initial','unset','revert'}:choices.append((important,(1,0,0,0),position,value))
        value=max(choices)[-1] if choices else 'inherit'
        mode=parent if value in {'inherit','unset'} else 'horizontal-tb' if value in {'initial','revert'} else value
        modes[wrapper]=mode;specified[wrapper]=bool(choices) or specified.get(wrapper.parent,False)
        if wrapper.local_name=='body' and specified[wrapper]:body_mode=mode
        if wrapper.local_name in {'p','li','blockquote'}:weights[mode]+=max(1,len(''.join(wrapper.etree_element.itertext())))
    return body_mode or (weights.most_common(1)[0][0] if weights else 'horizontal-tb')
