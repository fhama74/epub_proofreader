"""Explicit chapter splits; preserve source markup and rebuild navigation."""
import copy,posixpath,re,uuid
from urllib.parse import urlsplit,quote,unquote
from lxml import etree
from .epub import Book,EpubError,NS,local,reference,xml
from .structure import encoded,decoded
from .working import WorkingFiles

EPUB='http://www.idpf.org/2007/ops'
NCX='http://www.daisy.org/z3986/2005/ncx/'

def serialize(node):return etree.tostring(node.getroottree(),encoding='UTF-8',xml_declaration=True)
def ids(node):return set(node.xpath('//@id | //@xml:id',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'}))
def href(base,target,fragment=''):
    path=posixpath.relpath(target,posixpath.dirname(base) or '.')
    return quote(path,safe='/')+('#'+quote(fragment,safe='') if fragment else '')

def insert_outline(root,entry,doc,trees,path,node,level,ncx=False,boundary=None,boundary_after=False):
    """Insert in reading order, retaining existing entries and their relative nesting."""
    tag='{'+NCX+'}navPoint' if ncx else '{'+NS['x']+'}li'
    entries=list(root.iter(tag))
    positions={element:index for index,element in enumerate(trees[path].iter())}
    cut=positions[node]
    from .segments import layout
    slots=layout(node)[1]
    records=[];insert_at=None;levels={}
    for item in entries:
        link=item.find('{'+NCX+'}content') if ncx else item.find('x:a',NS)
        value=link.get('src' if ncx else 'href','') if link is not None else ''
        target=None;fragment=unquote(urlsplit(value).fragment)
        try:target=reference(doc,value) if value else None
        except EpubError:pass
        parent=next((a for a in item.iterancestors() if a.tag==tag),None)
        depth=levels[parent]+1 if parent is not None else 1
        # Imported navigation retains its nesting. Our added headings carry an
        # explicit semantic level, including levels skipped in the visible TOC.
        if target in trees and (parent is None or fragment.startswith('chapter-')):
            matches=trees[target].xpath('//*[@id=$ident]',ident=fragment) if fragment else []
            if not matches and parent is None:matches=trees[target].xpath('//x:body//x:h1 | //x:body//x:h2 | //x:body//x:h3 | //x:body//x:h4 | //x:body//x:h5 | //x:body//x:h6',namespaces=NS)
            if matches and re.fullmatch('h[1-6]',local(matches[0])):depth=int(local(matches[0])[1])
        levels[item]=depth
        if target==path:
            points=trees[path].xpath('//*[@id=$ident or @xml:id=$ident]',ident=fragment,namespaces={'xml':'http://www.w3.org/XML/1998/namespace'}) if fragment else []
            precedes=not fragment or bool(points and positions[points[0]]<cut)
            if points and boundary is not None and (points[0] is node or node in points[0].iterancestors()):
                start=next((start for element,field,start,end in slots if element is points[0] and field=='text'),0)
                precedes=start<boundary or boundary_after and boundary==len(layout(node)[0])
            if precedes:insert_at=len(records)+1
        clone=copy.deepcopy(item)
        for child in list(clone):
            if child.tag==(tag if ncx else '{'+NS['x']+'}ol'):clone.remove(child)
        records.append((clone,depth))
    if insert_at is None:
        # No link to the old chapter: append rather than discard any TOC entries.
        insert_at=len(records)
    records.insert(insert_at,(entry,level))
    for child in list(root):
        if child.tag==tag:root.remove(child)
    stack=[]
    for item,depth in records:
        while stack and stack[-1][1]>=depth:stack.pop()
        if stack:
            parent=stack[-1][0]
            if not ncx:
                children=parent.find('x:ol',NS)
                if children is None:children=etree.SubElement(parent,'{'+NS['x']+'}ol')
                parent=children
            parent.append(item)
        else:root.append(item)
        stack.append((item,depth))

def divide(node,target,after=False):
    """Split at a complete block, retaining the ancestor chain on both sides."""
    left=copy.deepcopy(node);right=copy.deepcopy(node)
    for child in list(left):left.remove(child)
    for child in list(right):right.remove(child)
    right.text=None
    left.tail=None
    found=False
    for child in node:
        if child is target:found=True;(left if after else right).append(copy.deepcopy(child))
        elif target in child.iterdescendants():
            a,b=divide(child,target,after);left.append(a);right.append(b);found=True
        else:(right if found else left).append(copy.deepcopy(child))
    if not found:raise EpubError('選択位置で章を分けられません。')
    return left,right

def apply_snapshot(book,snapshot,reverse=False):
    expected=snapshot['after_files' if reverse else 'before_files']
    for path,content in expected.items():
        if book.files.get(path)!=(decoded(content) if content is not None else None):
            from .editing import EditConflict
            raise EditConflict('章の構造が変更されています。操作を中止しました。')
    changes=snapshot['before_files' if reverse else 'after_files']
    return WorkingFiles.merge(book.original,{p:decoded(v) if v is not None else None for p,v in changes.items()})

def split(book,paragraph_id,title,key=None,level=None,boundary=None,boundary_after=False):
    from .editing import locate_paragraph
    title=title.strip()
    legacy=level is None
    if not legacy and (type(level) is not int or not 1<=level<=6):raise EpubError('章のレベルはh1〜h6で指定してください。')
    heading_level=1 if legacy else level
    if not xml(book.get(book.opf_path)).get('version','').startswith('3'):raise EpubError('章の作成はEPUB 3に対応しています。')
    if not title or len(title)>200:raise EpubError('章名を1〜200文字で入力してください。')
    key=key or uuid.uuid4().hex
    if not re.fullmatch(r'[0-9a-f]{32}',key):raise EpubError('章の識別子が不正です。')
    chapter,record,node=locate_paragraph(book,paragraph_id);path=chapter['path']
    if sum(c['path']==path for c in book.chapters)!=1:raise EpubError('同じXHTMLが複数の章で共有されているため、章の分割はできません。')
    body=book.trees[path].find('x:body',NS)
    # Do not cut a list/table/figure or a ruby in half.
    if local(node) not in {'p','h1','h2','h3','h4','h5','h6'} or any(local(a) in {'li','table','figure','ruby','a'} for a in node.iterancestors() if a is not body):
        raise EpubError('箇条書き・表・図・ルビの内側では章を分けられません。通常の本文段落を選択してください。')
    from .segments import layout
    from .structure import split_element
    content=layout(node)[0];middle=boundary is not None and 0<boundary<len(content)
    if boundary is not None and (type(boundary) is not int or not 0<=boundary<=len(content)):raise EpubError('章を追加する文の位置が不正です。')
    at_end=boundary is not None and boundary==len(content) and (boundary>0 or boundary_after)
    if middle:
        if local(node)!='p':raise EpubError('見出しの途中には章を追加できません。')
        if any(start<boundary<end for _,start,end in layout(node)[2]):raise EpubError('ルビの途中には章を追加できません。')
        work=copy.deepcopy(body);target=list(work.iter())[list(body.iter()).index(node)]
        a,b=split_element(target,boundary);a.tail=None;b.tail=target.tail
        parent=target.getparent();index=parent.index(target);parent.replace(target,a);parent.insert(index+1,b)
        left,right=divide(work,b)
    else:left,right=divide(body,node,after=at_end)
    if ''.join(left.itertext())+''.join(right.itertext())!=''.join(body.itertext()):raise EpubError('章分割後の本文保持を検証できません。')
    newpath=posixpath.join(posixpath.dirname(path),'chapter-'+key+'.xhtml')
    if newpath in book.files:raise EpubError('追加先の章ファイルが既に存在します。')
    oldtree=copy.deepcopy(book.trees[path]);oldtree.replace(oldtree.find('x:body',NS),left)
    newtree=copy.deepcopy(book.trees[path]);newtree.replace(newtree.find('x:body',NS),right)
    head=newtree.find('x:head',NS);label=head.find('x:title',NS)
    if label is None:label=etree.SubElement(head,'{'+NS['x']+'}title')
    label.text=title
    heading=etree.Element('{'+NS['x']+'}h'+str(heading_level),id='chapter-'+key);heading.text=title;right.insert(0,heading)
    empty=boundary is not None and not right.xpath('.//x:p | .//x:li | .//x:blockquote',namespaces=NS)
    if empty:etree.SubElement(right,'{'+NS['x']+'}p')
    trees={p:copy.deepcopy(t) for p,t in book.trees.items()};trees[path]=oldtree;trees[newpath]=newtree
    moved=ids(right)-ids(left)
    opf=xml(book.get(book.opf_path));manifest=opf.find('opf:manifest',NS);spine=opf.find('opf:spine',NS)
    item=next(i for i in manifest if reference(book.opf_path,i.get('href',''))==path)
    if item.get('media-overlay'):raise EpubError('音声と同期する章の分割は未対応です。')
    new_id='eproof-'+key
    if manifest.xpath('opf:item[@id=$ident]',ident=new_id,namespaces=NS):raise EpubError('章の識別子が既に使われています。')
    entry=etree.Element('{'+NS['opf']+'}item',id=new_id,href=href(book.opf_path,newpath),attrib={'media-type':'application/xhtml+xml'})
    manifest.insert(manifest.index(item)+1,entry)
    oldref=next(i for i in spine if i.get('idref')==item.get('id'))
    newref=copy.deepcopy(oldref);newref.set('idref',new_id);newref.attrib.pop('id',None);spine.insert(spine.index(oldref)+1,newref)
    navs=[m for m in book.manifest if 'nav' in m['properties'].split()]
    if not navs:
        navpath=posixpath.join(posixpath.dirname(book.opf_path),'navigation-'+key+'.xhtml')
        navtree=etree.Element('{'+NS['x']+'}html',nsmap={None:NS['x'],'epub':EPUB},lang='ja')
        h=etree.SubElement(navtree,'{'+NS['x']+'}head');etree.SubElement(h,'{'+NS['x']+'}title').text='目次'
        b=etree.SubElement(navtree,'{'+NS['x']+'}body');nav=etree.SubElement(b,'{'+NS['x']+'}nav',attrib={'{'+EPUB+'}type':'toc'});ol=etree.SubElement(nav,'{'+NS['x']+'}ol')
        for c in book.chapters:
            li=etree.SubElement(ol,'{'+NS['x']+'}li');etree.SubElement(li,'{'+NS['x']+'}a',href=href(navpath,c['path'])).text=c['title']
        trees[navpath]=navtree
        etree.SubElement(manifest,'{'+NS['opf']+'}item',id='nav-'+key,href=href(book.opf_path,navpath),attrib={'media-type':'application/xhtml+xml','properties':'nav'})
        navs=[{'path':navpath}]
    for m in navs:
        navpath=m['path'];tree=trees[navpath]
        toc=tree.xpath('//x:nav[@*[local-name()="type"]="toc"]',namespaces=NS)
        if not toc:raise EpubError('目次の構造を解釈できないため、章の分割を中止しました。')
        ol=toc[0].find('x:ol',NS)
        if ol is None:raise EpubError('目次に項目一覧がありません。')
        links=[a for a in toc[0].xpath('.//x:a',namespaces=NS) if reference(navpath,a.get('href',''))==path]
        anchor=links[0].getparent() if links else None
        li=etree.Element('{'+NS['x']+'}li');etree.SubElement(li,'{'+NS['x']+'}a',href=href(navpath,newpath,heading.get('id'))).text=title
        if not legacy:insert_outline(ol,li,navpath,book.trees,path,node,level,boundary=boundary,boundary_after=boundary_after)
        elif anchor is not None and local(anchor)=='li':anchor.addnext(li)
        else:ol.append(li)
    # Rewrite references to moved anchors, including links in the new chapter
    # back to anchors that stayed in the original chapter.
    extra={}
    for m in book.manifest:
        if m['media_type']=='application/x-dtbncx+xml':extra[m['path']]=xml(book.get(m['path']))
    for doc,tree in {**trees,**extra}.items():
        ncx_anchors=[e for e in tree.iter('{'+NCX+'}navPoint') if any(reference(doc,c.get('src',''))==path for c in e.findall('{'+NCX+'}content'))] if doc in extra else []
        for e in tree.iter():
            for attr in ('href','src'):
                value=e.get(attr)
                if not value:continue
                try:target=reference(path if doc==newpath else doc,value)
                except EpubError:continue
                fragment=unquote(urlsplit(value).fragment)
                if target!=path or not fragment:continue
                destination=newpath if fragment in moved or doc==newpath and fragment in ids(right) else path
                if destination!=target or doc==newpath:e.set(attr,href(doc,destination,fragment))
        if doc in extra:
            navmap=tree.find('{'+NCX+'}navMap')
            point=etree.Element('{'+NCX+'}navPoint',id='chapter-'+key)
            etree.SubElement(etree.SubElement(point,'{'+NCX+'}navLabel'),'{'+NCX+'}text').text=title
            etree.SubElement(point,'{'+NCX+'}content',src=href(doc,newpath,heading.get('id')))
            if not legacy and navmap is not None:insert_outline(navmap,point,doc,book.trees,path,node,level,ncx=True,boundary=boundary,boundary_after=boundary_after)
            elif ncx_anchors:ncx_anchors[0].addnext(point)
            elif navmap is not None:navmap.append(point)
            for index,p in enumerate(tree.iter('{'+NCX+'}navPoint'),1):
                p.set('playOrder',str(index))
            if not legacy:
                depth=max((1+sum(a.tag=='{'+NCX+'}navPoint' for a in p.iterancestors()) for p in tree.iter('{'+NCX+'}navPoint')),default=0)
                for meta in tree.findall('.//{'+NCX+'}meta[@name="dtb:depth"]'):meta.set('content',str(depth))
    changes={p:serialize(t) for p,t in {**trees,**extra}.items() if p not in book.files or serialize(t)!=book.get(p)}
    changes[book.opf_path]=serialize(opf)
    source=WorkingFiles.merge(book.original,changes);result=Book(source)
    # Paragraph identity is independent of chapter numbering. Keep review states,
    # PDF mappings and drafts attached to the original paragraphs.
    old_ids={c['path']:[p['id'] for p in c['paragraphs']] for c in book.chapters}
    old_heads={c['path']:[p['id'] for p in c.get('headings',[])] for c in book.chapters}
    cut=next((i for i,p in enumerate(chapter['paragraphs']) if p['id']==paragraph_id),record.get('next_paragraph_index',0))
    if (middle or at_end) and paragraph_id in old_ids[path]:cut+=1
    heading_cut=len(oldtree.xpath('//x:body//x:h1 | //x:body//x:h2 | //x:body//x:h3 | //x:body//x:h4 | //x:body//x:h5 | //x:body//x:h6',namespaces=NS))
    old_ids[newpath]=old_ids[path][cut:];old_ids[path]=old_ids[path][:cut]
    focus=paragraph_id
    if middle:focus='paragraph-'+key;old_ids[newpath].insert(0,focus)
    elif old_ids[newpath]:focus=old_ids[newpath][0]
    if empty:focus='paragraph-'+key+'-empty';old_ids[newpath].append(focus)
    old_heads[newpath]=['heading-'+key]+old_heads[path][heading_cut:];old_heads[path]=old_heads[path][:heading_cut]
    mapping={}
    for c in result.chapters:
        mapping[c['id']]=old_ids[c['path']];mapping[c['id']+':headings']=old_heads[c['path']]
    before_map={c['id']:[p['id'] for p in c['paragraphs']] for c in book.chapters}
    before_map.update({c['id']+':headings':[p['id'] for p in c['headings']] for c in book.chapters})
    snapshot={'before_files':{p:encoded(book.get(p)) if p in book.files else None for p in changes},'after_files':{p:encoded(v) for p,v in changes.items()},'ids_before':before_map,'ids_after':mapping}
    options={'key':key,'title':title}
    if not legacy:options['level']=level
    if boundary is not None:options.update(boundary=boundary,boundary_after=boundary_after)
    return source,snapshot,[paragraph_id],chapter['title'],title,focus,options
