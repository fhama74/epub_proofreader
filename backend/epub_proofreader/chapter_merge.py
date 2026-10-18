"""Remove a chapter heading and move its contents into the previous chapter."""
import copy
import hashlib
import re
from urllib.parse import urlsplit, unquote
from lxml import etree
from .chapters import serialize, href, ids, NCX
from .epub import Book, EpubError, NS, local, reference, xml
from .structure import encoded
from .working import WorkingFiles


def merge(book, paragraph_id):
    from .editing import locate_paragraph
    chapter, record, heading = locate_paragraph(book, paragraph_id)
    index = book.chapters.index(chapter)
    if index == 0:
        raise EpubError('先頭の章には統合先の章がありません。')
    if not re.fullmatch('h[1-6]', local(heading)):
        raise EpubError('削除する章の見出しを選択してください。')
    previous = book.chapters[index-1]
    path, destination = chapter['path'], previous['path']
    if any(sum(c['path'] == p for c in book.chapters) != 1 for p in (path, destination)):
        raise EpubError('共有されたXHTMLの章は統合できません。')
    trees = {p: copy.deepcopy(t) for p, t in book.trees.items()}
    source = trees[path]
    body = source.find('x:body', NS)
    target = trees[destination].find('x:body', NS)
    suffix = hashlib.sha256(path.encode()).hexdigest()[:20]
    occupied = ids(body) | ids(target)
    remap = {}
    for ident in sorted(ids(body) & ids(target)):
        renamed = ident + '-merged-' + suffix
        while renamed in occupied:renamed += '-1'
        remap[ident] = renamed;occupied.add(renamed)
    node = source.xpath(record['xpath'], namespaces=NS)[0]
    # Preserve destinations of existing links to the removed heading.
    node.tag = '{' + NS['x'] + '}span'
    node.text = None
    child_anchors = node.xpath('.//*/@id | .//*/@xml:id', namespaces={'xml': 'http://www.w3.org/XML/1998/namespace'})
    for child in list(node):node.remove(child)
    for ident in dict.fromkeys(child_anchors):etree.SubElement(node, '{' + NS['x'] + '}span', id=ident)
    wrapper = copy.deepcopy(body)
    wrapper.tag = '{' + NS['x'] + '}div'
    for element in wrapper.iter():
        for attr in ('id', '{http://www.w3.org/XML/1998/namespace}id'):
            if element.get(attr) in remap:element.set(attr, remap[element.get(attr)])
    anchor = wrapper.get('id')
    if not anchor:
        anchor = 'merged-' + suffix
        while anchor in occupied:anchor += '-1'
        wrapper.set('id', anchor)
    # Relative image, stylesheet, and hyperlink references must use the old base.
    def relocated(value):
        parts = urlsplit(value)
        if parts.scheme or parts.netloc or not value or value.startswith('data:'):return value
        old = reference(path, value)
        fragment = unquote(parts.fragment)
        if old == path:fragment = remap.get(fragment, fragment) or anchor
        result = href(destination, destination if old == path else old, fragment)
        if parts.query:
            prefix, sep, frag = result.partition('#')
            result = prefix + '?' + parts.query + (sep + frag if sep else '')
        return result
    for element in wrapper.iter():
        for attr in ('href', 'src', 'poster', 'data', '{http://www.w3.org/1999/xlink}href'):
            value = element.get(attr)
            if value:element.set(attr, relocated(value))
        if element.get('srcset'):
            raise EpubError('複数解像度の画像を含む章の統合は保護されています。')
        if element.get('style'):
            element.set('style', re.sub(r'url\(\s*([\x22\x27]?)(.*?)\1\s*\)', lambda m: 'url("' + relocated(m[2]) + '")', element.get('style')))
    target.append(wrapper)
    # Bring over chapter-specific stylesheets without moving its title.
    head = trees[destination].find('x:head', NS)
    existing = {etree.tostring(e) for e in head}
    for element in source.find('x:head', NS):
        if local(element) not in {'link', 'style'}:continue
        clone = copy.deepcopy(element)
        if clone.get('href'):clone.set('href', relocated(clone.get('href')))
        if local(clone) == 'style' and clone.text:
            clone.text = re.sub(r'url\(\s*([\x22\x27]?)(.*?)\1\s*\)', lambda m: 'url("' + relocated(m[2]) + '")', clone.text)
        if etree.tostring(clone) not in existing:head.append(clone)
    opf = xml(book.get(book.opf_path))
    manifest, spine = opf.find('opf:manifest', NS), opf.find('opf:spine', NS)
    item = next(i for i in manifest if reference(book.opf_path, i.get('href', '')) == path)
    if item.get('media-overlay') or 'nav' in item.get('properties', '').split():
        raise EpubError('音声同期・目次の章は統合できません。')
    for ref in list(spine):
        if ref.get('idref') == item.get('id'):spine.remove(ref)
    manifest.remove(item)
    extras = {m['path']: xml(book.get(m['path'])) for m in book.manifest if m['media_type'] == 'application/x-dtbncx+xml'}
    for doc, tree in {**trees, **extras}.items():
        if doc == path:continue
        # Remove only navigation entries for this chapter's heading; retain and
        # promote any nested section entries.
        candidates = list(tree.xpath('//x:nav[@*[local-name()="type"]="toc"]//x:li', namespaces=NS))
        candidates += list(tree.iter('{' + NCX + '}navPoint'))
        for entry in candidates:
            ncx = entry.tag == '{' + NCX + '}navPoint'
            link = entry.find('{' + NCX + '}content') if ncx else entry.find('x:a', NS)
            value = link.get('src' if ncx else 'href', '') if link is not None else ''
            if not value:continue
            try:matches = reference(doc, value) == path and unquote(urlsplit(value).fragment) in {'', heading.get('id', '')}
            except EpubError:matches = False
            if matches:
                parent = entry.getparent();slot = parent.index(entry)
                children = entry.findall('{' + NCX + '}navPoint') if ncx else entry.xpath('x:ol/x:li', namespaces=NS)
                for child in children:parent.insert(slot, child);slot += 1
                parent.remove(entry)
                if local(parent) == 'ol' and not len(parent) and local(parent.getparent()) == 'li':parent.getparent().remove(parent)
        for element in tree.iter():
            for attr in ('href', 'src', '{http://www.w3.org/1999/xlink}href'):
                value = element.get(attr)
                if not value:continue
                try:matches = reference(doc, value) == path
                except EpubError:matches = False
                if matches:
                    fragment = unquote(urlsplit(value).fragment)
                    element.set(attr, href(doc, destination, remap.get(fragment, fragment) or anchor))
        if doc in extras:
            points = list(tree.iter('{' + NCX + '}navPoint'))
            for i, point in enumerate(points, 1):point.set('playOrder', str(i))
            depth = max((1 + sum(a.tag == '{' + NCX + '}navPoint' for a in p.iterancestors()) for p in points), default=0)
            for meta in tree.findall('.//{' + NCX + '}meta[@name="dtb:depth"]'):meta.set('content', str(depth))
    changes = {p: serialize(t) for p, t in {**trees, **extras}.items() if p != path and serialize(t) != book.get(p)}
    changes[book.opf_path] = serialize(opf)
    changes[path] = None
    working = WorkingFiles.merge(book.original, changes)
    result = Book(working)
    old_ids = {c['path']: [p['id'] for p in c['paragraphs']] for c in book.chapters}
    heads = {c['path']: [p['id'] for p in c['headings']] for c in book.chapters}
    old_ids[destination] += old_ids[path]
    heads[destination] += [p for p in heads[path] if p != paragraph_id]
    mapping = {}
    for c in result.chapters:
        mapping[c['id']] = old_ids[c['path']]
        mapping[c['id'] + ':headings'] = heads[c['path']]
    before_ids = {}
    for c in book.chapters:
        before_ids[c['id']] = [p['id'] for p in c['paragraphs']]
        before_ids[c['id'] + ':headings'] = [p['id'] for p in c['headings']]
    snapshot = dict(before_files={p: encoded(book.get(p)) if p in book.files else None for p in changes},
                    after_files={p: encoded(v) if v is not None else None for p, v in changes.items()}, ids_before=before_ids, ids_after=mapping)
    focus = (old_ids[path] or old_ids[destination] or heads[destination])[-1 if not old_ids[path] else 0]
    return working, snapshot, [paragraph_id], chapter['title'], previous['title'], focus
