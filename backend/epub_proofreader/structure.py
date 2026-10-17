"""Explicit reversible paragraph operations. Original EPUB is never modified."""
import base64
import copy
import uuid
from lxml import etree
from .epub import EpubError, NS, local
from .segments import layout

def encoded(data):return base64.b64encode(data).decode('ascii')
def decoded(data):return base64.b64decode(data,validate=True)
def new_id():return 'paragraph-'+uuid.uuid4().hex

def ruby_values(tree):
    return [etree.tostring(r,method='c14n',exclusive=True,with_comments=True,with_tail=False) for r in tree.xpath('//x:ruby',namespaces=NS)]

def split_element(node,offset):
    text,_,rubies=layout(node)
    if local(node)=='ruby' or local(node) not in {'p','span','em','strong','b','i','a','sup','sub'}:
        raise EpubError('ルビ・保護された要素の途中では段落を分割できません。')
    left=etree.Element(node.tag,dict(node.attrib),nsmap=node.nsmap)
    attributes={k:v for k,v in node.attrib.items() if k not in {'id','{http://www.w3.org/XML/1998/namespace}id'}}
    right=etree.Element(node.tag,attributes,nsmap=node.nsmap)
    position=0
    def append(parent,value):
        if not value:return
        if len(parent):parent[-1].tail=(parent[-1].tail or '')+value
        else:parent.text=(parent.text or '')+value
    def text_part(value):
        nonlocal position
        value=value or '';cut=max(0,min(len(value),offset-position))
        append(left,value[:cut]);append(right,value[cut:]);position+=len(value)
    text_part(node.text)
    for child in node:
        length=len(layout(child)[0]) if isinstance(child.tag,str) else 0
        if offset<=position:
            result=copy.deepcopy(child);result.tail=None;right.append(result)
        elif offset>=position+length:
            result=copy.deepcopy(child);result.tail=None;left.append(result)
        else:
            l,r=split_element(child,offset-position);left.append(l);right.append(r)
        position+=length
        text_part(child.tail)
    return left,right

def operate(book,paragraph_id,action,position='after',text='',offset=None):
    from .editing import locate_paragraph
    from .working import WorkingFiles
    chapter,_,_=locate_paragraph(book,paragraph_id)
    book=copy.copy(book);book.trees=dict(book.trees);book.trees[chapter['path']]=copy.deepcopy(book.trees[chapter['path']].getroottree()).getroot()
    chapter,record,node=locate_paragraph(book,paragraph_id)
    if local(node)!='p' or node.getparent() is None:
        raise EpubError('段落の構造編集はp要素を対象にしています。リストや引用要素は保護対象です。')
    path=chapter['path'];tree=book.trees[path]
    if sum(c['path']==path for c in book.chapters)!=1:
        raise EpubError('同じXHTMLが複数の章に使われているため、この章の構造編集は保護されています。')
    records=chapter['paragraphs']
    elements=[next(e for e in tree.iter() if isinstance(e.tag,str) and tree.getroottree().getpath(e)==p['xpath']) for p in records]
    identifiers={element:p['id'] for element,p in zip(elements,records)}
    before_ids=[p['id'] for p in records]
    before=book.get(path);original_rubies=ruby_values(tree)
    parent=node.getparent();index=parent.index(node);content=layout(node)[0]
    affected=[paragraph_id]
    if action=='insert':
        if position not in {'before','after'}:raise EpubError('挿入位置が不正です。')
        created=etree.Element(node.tag,nsmap=node.nsmap)
        try:created.text=text or None
        except ValueError as exc:raise EpubError('XMLで使用できない文字が含まれています。') from exc
        parent.insert(index+(position=='after'),created)
        focus=new_id();identifiers[created]=focus
        previous='';following=text;affected.append(focus)
    elif action=='split':
        if offset is None or not 0<offset<len(content):raise EpubError('段落の先頭・末尾以外にカーソルを置いてください。')
        for _,start,end in layout(node)[2]:
            if start<offset<end:raise EpubError('ルビの途中では分割できません。親文字の前後を選択してください。')
        left,right=split_element(node,offset)
        left.tail=None;right.tail=node.tail
        parent.replace(node,left);parent.insert(index+1,right)
        identifiers[left]=paragraph_id;focus=new_id();identifiers[right]=focus
        previous=content;following=[layout(left)[0],layout(right)[0]];affected.append(focus)
        if ''.join(following)!=content:raise EpubError('分割後の本文が一致しません。操作を中止しました。')
    elif action=='merge':
        paragraph_index=records.index(record)
        if paragraph_index==0:raise EpubError('この章の先頭段落は前の段落に結合できません。')
        prior=elements[paragraph_index-1]
        if local(prior)!='p' or prior.getparent() is not parent or prior.getnext() is not node:
            raise EpubError('見出し・画像・区切り・別セクションをまたぐ結合はできません。')
        focus=records[paragraph_index-1]['id'];affected=[focus,paragraph_id]
        previous=[layout(prior)[0],content]
        tail=node.tail;node.tail=None;parent.remove(node)
        # Keep the former paragraph's ID, class, style, links and ruby on an inline wrapper.
        node.tag='{'+etree.QName(node).namespace+'}span' if etree.QName(node).namespace else 'span'
        prior.append(node);prior.tail=(prior.tail or '')+(tail or '')
        following=layout(prior)[0]
        if following!=''.join(previous):raise EpubError('結合後の本文が一致しません。操作を中止しました。')
    else:raise EpubError('段落の操作が不正です。')
    if ruby_values(tree)!=original_rubies:raise EpubError('ルビの保持検証に失敗しました。操作を中止しました。')
    after_elements=tree.xpath('//x:p | //x:li[not(.//x:p)] | //x:blockquote[not(.//x:p)]',namespaces=NS)
    after_ids=[identifiers.get(element) for element in after_elements]
    if any(ident is None for ident in after_ids):raise EpubError('段落IDを再計算できません。')
    serialized=etree.tostring(tree.getroottree(),encoding=tree.getroottree().docinfo.encoding or 'UTF-8',xml_declaration=True)
    snapshot={'file':path,'before_file':encoded(before),'after_file':encoded(serialized),'chapter_id':chapter['id'],'ids_before':before_ids,'ids_after':after_ids}
    return WorkingFiles.merge(book.original,{path:serialized}),snapshot,affected,previous,following,focus
