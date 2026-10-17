"""Explicit ruby insertion/removal, preserving base text, IDs and surrounding markup."""
import copy
from lxml import etree
from .epub import EpubError, NS, local
from .segments import layout
from .structure import encoded
from .working import WorkingFiles


def operate(book,pid,action,start=None,end=None,reading=None,index=None):
    from .editing import locate_paragraph
    chapter,_,_=locate_paragraph(book,pid)
    model=copy.copy(book);model.trees=dict(book.trees)
    path=chapter['path'];model.trees[path]=copy.deepcopy(book.trees[path].getroottree()).getroot()
    chapter,record,node=locate_paragraph(model,pid);before=model.get(path)
    text,slots,rubies=layout(node);namespace=etree.QName(node).namespace
    tag=lambda name:'{'+namespace+'}'+name if namespace else name
    if action=='ruby_add':
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text) or end-start>1000:
            raise EpubError('親文字にする範囲を選択してください（1000文字以内）。')
        if not reading or not reading.strip() or len(reading)>2000:raise EpubError('読みを入力してください（2000文字以内）。')
        if any(a<end and b>start for _,a,b in rubies):raise EpubError('既存のルビと重なる範囲には追加できません。')
        found=next(((owner,field,a,b) for owner,field,a,b in slots if a<=start<end<=b and not owner.xpath('ancestor-or-self::x:rt | ancestor-or-self::x:rp | ancestor-or-self::x:rtc',namespaces=NS)),None)
        if found is None:raise EpubError('装飾やリンクの境界をまたぐルビ追加はできません。範囲を短く選び直してください。')
        owner,field,a,b=found;value=getattr(owner,field) or '';ruby=etree.Element(tag('ruby'))
        try:
            ruby.text=text[start:end];etree.SubElement(ruby,tag('rt')).text=reading
        except ValueError:raise EpubError('読みにはXMLで使用できる文字を入力してください。')
        setattr(owner,field,value[:start-a] or None);ruby.tail=value[end-a:] or None
        if field=='text':owner.insert(0,ruby)
        else:owner.addnext(ruby)
        options={'start':start,'end':end,'reading':reading}
    elif action=='ruby_delete':
        values=node.xpath('.//x:ruby',namespaces=NS)
        if type(index) is not int or not 0<=index<len(values):raise EpubError('削除するルビが見つかりません。')
        ruby=values[index]
        for child in list(ruby.iterdescendants()):
            if local(child) not in {'rt','rp','rtc'}:continue
            if any(e.get('id') or e.get('{http://www.w3.org/XML/1998/namespace}id') for e in child.iter()):
                raise EpubError('読み部分に参照用IDがあるため、このルビは削除できません。')
        for child in list(ruby.iterdescendants()):
            if local(child) in {'rt','rp','rtc'} and child.getparent() is not None:
                parent=child.getparent();previous=child.getprevious();tail=child.tail or ''
                if previous is None:parent.text=(parent.text or '')+tail
                else:previous.tail=(previous.tail or '')+tail
                parent.remove(child)
        ruby.tag=tag('span')
        for rb in ruby.xpath('.//x:rb',namespaces=NS):rb.tag=tag('span')
        options={'index':index}
    else:raise EpubError('ルビ操作が不正です。')
    if layout(node)[0]!=text:raise EpubError('親文字の保持検証に失敗しました。操作を中止しました。')
    tree=model.trees[path].getroottree()
    after=etree.tostring(tree,encoding=tree.docinfo.encoding or 'UTF-8',xml_declaration=True)
    ids=[p['id'] for p in chapter['paragraphs']]
    snapshot={'file':path,'before_file':encoded(before),'after_file':encoded(after),'chapter_id':chapter['id'],'ids_before':ids,'ids_after':ids}
    return WorkingFiles.merge(book.original,{path:after}),snapshot,[pid],text,text,pid,options
