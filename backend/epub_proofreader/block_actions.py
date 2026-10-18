"""Sentence boundaries, explicit blank paragraphs and reversible deletions."""
import copy
import re
import uuid
from lxml import etree
from .epub import EpubError, NS, local
from .segments import layout
from .structure import operate, split_element, encoded
from .working import WorkingFiles


def change(book, paragraph_id, action, position='after', text='', boundary=None, start=None, end=None, key=None):
    from .editing import locate_paragraph
    key = key or uuid.uuid4().hex
    if not re.fullmatch('[0-9a-f]{32}', key):
        raise EpubError('段落の識別子が不正です。')
    options = dict(position=position, text=text, boundary=boundary, start=start, end=end, key=key)
    if action in {'insert_boundary', 'blank'}:
        chapter, record, node = locate_paragraph(book, paragraph_id)
        content = layout(node)[0]
        if boundary is None:
            boundary = 0 if position == 'before' else len(content)
        options['boundary'] = boundary
        if action == 'insert_boundary' and not text.strip() and 0 < boundary < len(content):
            result = operate(book, paragraph_id, 'split', offset=boundary)
        else:
            result = operate(book, paragraph_id, 'insert', position=position,
                             text='' if action == 'blank' or not text.strip() else text,
                             boundary=boundary if local(node) == 'p' else None, key=key)
        source, snapshot, affected, before, after, focus = result
        stable = 'paragraph-' + key
        snapshot['ids_after'] = [stable if p == focus else p for p in snapshot['ids_after']]
        affected = [stable if p == focus else p for p in affected]
        return source, snapshot, affected, before, after, stable, options
    if action != 'delete':
        raise EpubError('段落の操作が不正です。')
    chapter, record, original_node = locate_paragraph(book, paragraph_id)
    if local(original_node) != 'p':
        raise EpubError('削除できるのは通常の本文段落です。見出しは章の削除を選んでください。')
    if sum(c['path'] == chapter['path'] for c in book.chapters) != 1:
        raise EpubError('共有されたXHTMLの段落は削除できません。')
    path = chapter['path']
    tree = copy.deepcopy(book.trees[path])
    node = tree.xpath(record['xpath'], namespaces=NS)[0]
    content = layout(node)[0]
    partial = start is not None or end is not None
    if partial and (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(content)):
        raise EpubError('削除する文の範囲が不正です。')
    records = chapter['paragraphs']
    elements = [tree.xpath(p['xpath'], namespaces=NS)[0] for p in records]
    identifiers = dict(zip(elements, (p['id'] for p in records)))
    parent = node.getparent()
    if partial and (start > 0 or end < len(content)):
        if any(a < cut < b for _, a, b in layout(node)[2] for cut in (start, end)):
            raise EpubError('ルビの途中では文を削除できません。')
        left, _ = split_element(node, start)
        _, right = split_element(node, end)
        # A wrapper retains surviving inline markup and ruby without flattening it.
        right.tag = '{' + NS['x'] + '}span'
        right.tail = None
        left.append(right)
        left.tail = node.tail
        parent.replace(node, left)
        identifiers[left] = paragraph_id
        focus = paragraph_id
        after = layout(left)[0]
        if after != content[:start] + content[end:]:
            raise EpubError('削除後の本文を検証できません。')
    else:
        # Keep explicit anchors as empty inline markers for existing links.
        anchors = node.xpath('.//@id | .//@xml:id | @id | @xml:id', namespaces={'xml': 'http://www.w3.org/XML/1998/namespace'})
        marker = etree.Element('{' + NS['x'] + '}span')
        for ident in dict.fromkeys(anchors):
            etree.SubElement(marker, '{' + NS['x'] + '}span', id=ident)
        marker.tail = node.tail
        if anchors:
            parent.replace(node, marker)
        else:
            index = parent.index(node)
            tail = node.tail
            parent.remove(node)
            if tail:
                if index:parent[index-1].tail = (parent[index-1].tail or '') + tail
                else:parent.text = (parent.text or '') + tail
        remaining = [p for p in records if p['id'] != paragraph_id]
        index = records.index(record)
        if remaining:
            focus = remaining[min(index, len(remaining)-1)]['id']
        else:
            blank = etree.SubElement(tree.find('x:body', NS), '{' + NS['x'] + '}p')
            focus = 'paragraph-' + key
            identifiers[blank] = focus
        after = ''
    elements = tree.xpath('//x:p | //x:li[not(.//x:p)] | //x:blockquote[not(.//x:p)]', namespaces=NS)
    after_ids = [identifiers[e] for e in elements]
    serialized = etree.tostring(tree.getroottree(), encoding=tree.getroottree().docinfo.encoding or 'UTF-8', xml_declaration=True)
    snapshot = dict(file=path, before_file=encoded(book.get(path)), after_file=encoded(serialized),
                    chapter_id=chapter['id'], ids_before=[p['id'] for p in records], ids_after=after_ids)
    return WorkingFiles.merge(book.original, {path: serialized}), snapshot, [paragraph_id], content, after, focus, options
