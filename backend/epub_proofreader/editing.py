"""Protected text/ruby edits and explicit reversible paragraph operations."""
from __future__ import annotations
from collections import defaultdict
from difflib import SequenceMatcher
from datetime import datetime, timezone
import io
import hashlib
import copy
import json
import uuid
import zipfile
from lxml import etree
from .epub import Book, EpubError, NS, local, base_text, simple_ruby
from .segments import layout
from .working import WorkingFiles,materialize
from functools import lru_cache

SAFE_INLINE = {'h1','h2','h3','h4','h5','h6','p', 'li', 'blockquote', 'span', 'em', 'strong', 'b', 'i', 'a', 'sup', 'sub', 'br'}

class EditConflict(ValueError):
    pass

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def locate_paragraph(book, paragraph_id):
    for chapter in book.chapters:
        for record in [*chapter['paragraphs'],*chapter.get('headings',[])]:
            if record['id'] == paragraph_id:
                tree = book.trees[chapter['path']]
                # Match known locators; never evaluate a client-supplied XPath.
                node = next(e for e in tree.iter() if isinstance(e.tag, str) and tree.getroottree().getpath(e) == record['xpath'])
                return chapter, record, node
    raise EpubError('段落が見つかりません。')

def text_layout(book, paragraph_id):
    chapter, record, paragraph = locate_paragraph(book, paragraph_id)
    tree = book.trees[chapter['path']]
    pieces = []
    offset = 0
    def slot(node, field):
        nonlocal offset
        text = getattr(node, field) or ''
        pieces.append({'node': node, 'field': field, 'xpath': tree.getroottree().getpath(node), 'start': offset, 'end': offset + len(text), 'text': text, 'protected': False})
        offset += len(text)
    def walk(node):
        nonlocal offset
        if local(node) not in SAFE_INLINE:
            text = base_text(node, strip=False) if isinstance(node.tag, str) else ''
            pieces.append({'start': offset, 'end': offset + len(text), 'text': text, 'protected': True})
            offset += len(text)
            return
        slot(node, 'text')
        for child in node:
            walk(child)
            slot(child, 'tail')
    walk(paragraph)
    return chapter, record, paragraph, pieces, ''.join(piece['text'] for piece in pieces)

def ruby_limits(item):
    node,start,end=item
    previous=node.getprevious()
    left=(previous.tail if previous is not None else node.getparent().text) or ''
    right=node.tail or ''
    target=node.find('x:rb',NS)
    if target is None:target=node
    range_editable=simple_ruby(node) and layout(node)[0]==(target.text or '')
    return {'range_min':start-len(left),'range_max':end+len(right),'range_editable':range_editable}

def paragraph_details(book, paragraph_id, revision, *, include_tokens=True,include_chapter_token=True):
    chapter, record, _, pieces, text = text_layout(book, paragraph_id)
    _,_,ruby_ranges=layout(locate_paragraph(book,paragraph_id)[2])
    rubies=[{**ruby,'index':index,'start':ruby_ranges[index][1],'end':ruby_ranges[index][2],**ruby_limits(ruby_ranges[index])} for index,ruby in enumerate(record['rubies'])]
    tokens={}
    if include_tokens:
        tokens['token']=hashlib.sha256(etree.tostring(locate_paragraph(book,paragraph_id)[2],method='c14n',with_comments=True)).hexdigest()
        if include_chapter_token:tokens['chapter_token']=hashlib.sha256(etree.tostring(book.trees[chapter['path']],method='c14n',with_comments=True)+json.dumps([p['id'] for p in chapter['paragraphs']]).encode()).hexdigest()
    return {**record, **tokens,'rubies':rubies, 'path': chapter['path'], 'revision': revision, 'editor_text': text, 'protected_ranges': [{'start': p['start'], 'end': p['end']} for p in pieces if p['protected']]}

def text_changes(book, paragraph_id, after, span=None):
    chapter, _, _, pieces, full_before = text_layout(book, paragraph_id)
    offset=span[0] if span else 0
    before=full_before[span[0]:span[1]] if span else full_before
    full_after=full_before[:span[0]]+after+full_before[span[1]:] if span else after
    if len(after) > 20000 or len(before) > 20000:
        raise EpubError('1段落の編集は2万文字以内にしてください。')
    edits = defaultdict(list)
    for opcode, start, end, new_start, new_end in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if opcode == 'equal':
            continue
        replacement = after[new_start:new_end]
        start+=offset;end+=offset
        if start == end:
            if any(p['protected'] and p['start'] < start < p['end'] for p in pieces):
                raise EpubError('ルビの親文字は本文欄では変更できません。同じ編集画面の親文字・読み欄を使用してください。')
            candidates = [i for i,p in enumerate(pieces) if not p['protected'] and p['start'] <= start < p['end']]
            if not candidates:
                candidates = [i for i,p in enumerate(pieces) if not p['protected'] and p['start'] <= start <= p['end']]
            if not candidates:
                raise EpubError('保護された要素内への挿入はできません。')
            index = candidates[0]
            edits[index].append((start - pieces[index]['start'], start - pieces[index]['start'], replacement))
        else:
            affected = [i for i,p in enumerate(pieces) if p['end'] > start and p['start'] < end]
            if any(pieces[i]['protected'] for i in affected):
                raise EpubError('ルビ・保護された要素をまたぐ変更は適用できません。ルビは専用の編集欄で修正してください。')
            for number,index in enumerate(affected):
                piece = pieces[index]
                edits[index].append((max(start, piece['start'])-piece['start'], min(end,piece['end'])-piece['start'], replacement if number == 0 else ''))
    changes = []
    for index, operations in edits.items():
        piece = pieces[index]
        value = piece['text']
        for start,end,replacement in sorted(operations, reverse=True):
            value = value[:start] + replacement + value[end:]
        if value != piece['text']:
            changes.append({'file': chapter['path'], 'xpath': piece['xpath'], 'field': piece['field'], 'before': piece['text'], 'after': value, 'paragraph_id': paragraph_id})
    return changes, full_before, full_after

def ruby_changes(book, paragraph_id, ruby_index, base, reading, range_start=None, range_end=None):
    chapter, record, paragraph = locate_paragraph(book, paragraph_id)
    rubies = paragraph.xpath('.//x:ruby', namespaces=NS)
    if ruby_index < 0 or ruby_index >= len(rubies):
        raise EpubError('ルビが見つかりません。')
    ruby = rubies[ruby_index]
    children = list(ruby)
    rt = ruby.findall('x:rt', NS)
    rb = ruby.findall('x:rb', NS)
    # Conservative: exactly one plain base and plain reading. Preserve rp nodes.
    simple = simple_ruby(ruby)
    if not simple:
        raise EpubError('複雑なルビ構造は編集できません。元の構造を保持します。')
    if not base or not reading or len(base) > 1000 or len(reading) > 2000:
        raise EpubError('親文字と読みを入力してください（親文字1000文字・読み2000文字まで）。')
    target = rb[0] if rb else ruby
    tree = book.trees[chapter['path']]
    changes = []
    for node,value in [(target,base),(rt[0],reading)]:
        before = node.text or ''
        if before != value:
            changes.append({'file': chapter['path'], 'xpath': tree.getroottree().getpath(node), 'field': 'text', 'before': before, 'after': value, 'paragraph_id': paragraph_id})
    before={'base':record['rubies'][ruby_index]['base'],'reading':''.join(rt[0].itertext())}
    after={'base':base,'reading':reading}
    if range_start is not None or range_end is not None:
        _,_,ranges=layout(paragraph)
        item=next(item for item in ranges if item[0] is ruby);_,start,end=item
        limits=ruby_limits(item)
        if not limits['range_editable']:raise EpubError('空白や複雑な構造を含むルビの範囲変更は保護されています。')
        if type(range_start) is not int or type(range_end) is not int or not (limits['range_min']<=range_start<range_end<=limits['range_max'] and range_start<end and range_end>start):
            raise EpubError('ルビ範囲は元の親文字と重なり、隣接する本文の範囲内で指定してください。装飾や他のルビをまたぐ変更はできません。')
        previous=ruby.getprevious();owner=previous if previous is not None else ruby.getparent();field='tail' if previous is not None else 'text'
        left=getattr(owner,field) or '';right=ruby.tail or '';whole=left+before['base']+right
        prefix=whole[:range_start-limits['range_min']];suffix=whole[range_end-limits['range_min']:]
        for node,which,old,new in [(owner,field,left,prefix),(ruby,'tail',right,suffix)]:
            if old!=new:changes.append({'file':chapter['path'],'xpath':tree.getroottree().getpath(node),'field':which,'before':old,'after':new,'paragraph_id':paragraph_id})
        before.update(range_start=start,range_end=end);after.update(range_start=range_start,range_end=range_end)
    return changes,before,after

def apply_changes(book, changes, reverse=False):
    book=copy.copy(book);book.trees=dict(book.trees)
    for path in {c['file'] for c in changes}:
        if path not in book.trees:raise EpubError('変更データの参照先が不正です。')
        book.trees[path]=copy.deepcopy(book.trees[path].getroottree()).getroot()
    files = set()
    indexes = {}
    for change in changes:
        path = change['file']
        if path not in book.trees or change['field'] not in {'text','tail'}:
            raise EpubError('変更データの参照先が不正です。')
        tree = book.trees[path]
        if path not in indexes:
            indexes[path] = {tree.getroottree().getpath(e): e for e in tree.iter()}
        node = indexes[path].get(change['xpath'])
        expected = change['after'] if reverse else change['before']
        value = change['before'] if reverse else change['after']
        if node is None or (getattr(node,change['field']) or '') != expected:
            raise EditConflict('変更前の内容が一致しません。最新の段落を再読み込みしてください。')
        try:
            setattr(node, change['field'], value or None)
        except (ValueError, TypeError) as exc:
            raise EpubError('XMLで使用できない文字が含まれています。') from exc
        files.add(path)
    replacements = {}
    for path in files:
        tree = book.trees[path].getroottree()
        replacements[path] = etree.tostring(tree, encoding=tree.docinfo.encoding or 'UTF-8', xml_declaration=True)
    return WorkingFiles.merge(book.original,replacements)

def repack(data, replacements=None):
    replacements = replacements or {}
    if isinstance(data,WorkingFiles):
        replacements={**dict(data.replacements),**replacements};data=data.base
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(buffer, 'w') as out:
        out.comment = source.comment
        mimetype=copy.copy(source.getinfo('mimetype'));mimetype.compress_type=zipfile.ZIP_STORED
        out.writestr(mimetype, b'application/epub+zip')
        for info in source.infolist():
            if info.filename != 'mimetype':
                if info.filename in replacements and replacements[info.filename] is None:continue
                info = copy.copy(info)
                if info.compress_type not in {zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED}:
                    info.compress_type = zipfile.ZIP_DEFLATED
                out.writestr(info, replacements.get(info.filename, source.read(info)))
        for path,content in replacements.items():
            if path not in source.namelist() and content is not None:
                from .epub import safe_name
                out.writestr(safe_name(path),content,compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()

def structure(tree):
    return [(e.tag if isinstance(e.tag,str) else type(e).__name__, sorted(e.attrib.items()), len(e)) for e in tree.iter()]

def validate_export(original, working, commands=()):
    result = repack(working.original)
    checked = Book(result)
    if any(c.get('action')=='chapter_split' for c in commands):
        return validate_chapter_export(original,checked,result,commands)
    if set(original.files) != set(checked.files):
        raise EpubError('出力検証: EPUB内のファイル一覧が変化しています。')
    from .structure import decoded
    from .epub import xml
    expected={command['snapshot']['file']:structure(xml(decoded(command['snapshot']['after_file']))) for command in commands if 'snapshot' in command}
    changed = []
    for path,data in original.files.items():
        if checked.files[path] != data:
            if path not in original.trees or path not in checked.trees or expected.get(path,structure(original.trees[path])) != structure(checked.trees[path]):
                raise EpubError(f'出力検証: 許可されていない構造変更があります: {path}')
            changed.append(path)
    for path,tree in original.trees.items():
        def ids(root):return sorted((key,value) for e in root.iter() for key,value in e.attrib.items() if key in {'id','{http://www.w3.org/XML/1998/namespace}id'})
        if ids(tree)!=ids(checked.trees[path]):raise EpubError(f'出力検証: 元のXHTML IDが失われています: {path}')
    for key in ['manifest' ,'spine','metadata','direction','toc']:
        if getattr(original,key) != getattr(checked,key):
            raise EpubError(f'出力検証: {key}が変更されています。')
    return result, {'status':'passed', 'changed_xhtml':changed, 'file_count':len(checked.files), 'structure_preserved':True}

def validate_chapter_export(original,checked,result,commands):
    from .structure import decoded
    expected_files=dict(original.files)
    for command in commands:
        snapshot=command.get('snapshot',{})
        if command.get('action')=='chapter_split':
            for path,data in snapshot['after_files'].items():expected_files[path]=decoded(data)
        elif 'file' in snapshot:expected_files[snapshot['file']]=decoded(snapshot['after_file'])
    expected=Book(repack(original.original,expected_files))
    if set(expected.files)!=set(checked.files):raise EpubError('出力検証: 章作成の履歴とファイル一覧が一致しません。')
    changed=[]
    for path,data in checked.files.items():
        if path in expected.trees:
            a,b=expected.trees[path],checked.trees[path]
            if structure(a)!=structure(b):raise EpubError('出力検証: 許可されていない構造変更があります: '+path)
        elif data!=expected.files[path]:raise EpubError('出力検証: 章作成の履歴と変更内容が一致しません: '+path)
        if original.files.get(path)!=data:changed.append(path)
    for key in ['manifest','spine','metadata','direction','toc']:
        if getattr(expected,key)!=getattr(checked,key):raise EpubError('出力検証: 章作成の履歴と'+key+'が一致しません。')
    return result,{'status':'passed','changed_xhtml':[p for p in changed if p in checked.trees],'file_count':len(checked.files),'structure_preserved':True,'chapters_updated':True}

@lru_cache(maxsize=2)
def initial_working(data):return Book(data,repair_import=True).normalized

def state(con, book_id):
    row = con.execute('SELECT working,revision,commands,cursor,history,ids FROM editing WHERE book_id=?',(book_id,)).fetchone()
    if row is None:
        row = con.execute('SELECT original FROM books WHERE id=?',(book_id,)).fetchone()
        if row is None:
            raise EpubError('書籍がありません。')
        return {'working':initial_working(row[0]), 'revision':0, 'commands':[], 'cursor':0, 'history':[], 'ids':{}}
    files=tuple(con.execute('SELECT path,content FROM editing_files WHERE book_id=? ORDER BY path',(book_id,)).fetchall())
    return {'working':WorkingFiles(row[0],files),'_stored_base':row[0], 'revision':row[1], 'commands':json.loads(row[2]), 'cursor':row[3], 'history':json.loads(row[4]), 'ids':json.loads(row[5])}

@lru_cache(maxsize=4)
def cached_model(source,ids):
    return Book(source).apply_ids(json.loads(ids))

def working_model(value):
    source=WorkingFiles.merge(value['working'])
    return cached_model(source,json.dumps(value.get('ids',{}),sort_keys=True))

def edit_info(value):
    return {'revision':value['revision'], 'can_undo':value['cursor'] > 0 and value['commands'][value['cursor']-1].get('undoable',True), 'can_redo':value['cursor'] < len(value['commands']), 'edit_count':value['cursor'], 'history_count':len(value['history'])}

def save_state(con, book_id, value):
    base=value['working'].base if isinstance(value['working'],WorkingFiles) else value['working']
    fields=(value['revision'],json.dumps(value['commands'],ensure_ascii=False),value['cursor'],json.dumps(value['history'],ensure_ascii=False),json.dumps(value['ids'],ensure_ascii=False))
    if value.get('_stored_base')==base:
        con.execute('UPDATE editing SET revision=?,commands=?,cursor=?,history=?,ids=? WHERE book_id=?',(*fields,book_id))
    else:
        con.execute('INSERT INTO editing (book_id,working,revision,commands,cursor,history,ids) VALUES (?,?,?,?,?,?,?) ON CONFLICT(book_id) DO UPDATE SET working=excluded.working,revision=excluded.revision,commands=excluded.commands,cursor=excluded.cursor,history=excluded.history,ids=excluded.ids',(book_id,base,*fields))
    desired=dict(value['working'].replacements) if isinstance(value['working'],WorkingFiles) else {}
    existing=dict(con.execute('SELECT path,content FROM editing_files WHERE book_id=?',(book_id,)))
    for path in existing.keys()-desired.keys():con.execute('DELETE FROM editing_files WHERE book_id=? AND path=?',(book_id,path))
    for path,content in desired.items():
        if existing.get(path)!=content:con.execute('INSERT INTO editing_files VALUES (?,?,?) ON CONFLICT(book_id,path) DO UPDATE SET content=excluded.content',(book_id,path,content))

def commit_edit(con, book_id, revision, kind, paragraph_id=None, text=None, ruby_index=None, base=None, reading=None, reason='手動校正', target=None, replacement=None, sentence_index=None, expected_sentence=None, position='after', offset=None, rubies=None, source='manual', candidate_id=None, engine_id=None, span_start=None, span_end=None, expected_span=None, range_start=None, range_end=None, expected_token=None, expected_chapter_token=None, chapter_level=None, chapter_position=None):
    value = state(con,book_id)
    book = working_model(value)
    granular=False
    if paragraph_id and (expected_token or expected_chapter_token):
        current=paragraph_details(book,paragraph_id,value['revision'])
        if expected_token and current['token']!=expected_token:raise EditConflict('この段落は別のブラウザーで変更されています。入力は保持しています。最新版を確認してください。')
        if expected_chapter_token and current['chapter_token']!=expected_chapter_token:raise EditConflict('この章の内容・構造が変更されています。入力は保持しています。章を再読み込みしてください。')
        granular=kind in {'text','sentence','ruby','combined','ruby_add','ruby_delete'} and bool(expected_token) or kind in {'insert','split','merge','merge_next'} and bool(expected_chapter_token)
    if value['revision']!=revision and (not granular or revision>value['revision']):
        raise EditConflict('別の画面で編集されています。入力は保持しています。最新の内容を再読み込みしてください。')
    if kind in {'undo','redo'}:
        reverse = kind == 'undo'
        index = value['cursor']-1 if reverse else value['cursor']
        if index < 0 or index >= len(value['commands']):
            raise EpubError('元に戻す・やり直す操作がありません。')
        command = value['commands'][index]
        if not command.get('undoable',True):raise EditConflict('ルビの追加・削除はUndo／Redoの対象外です。その操作より前には戻せません。')
        if command['action']=='chapter_split':
            from .chapters import apply_snapshot
            value['working']=apply_snapshot(book,command['snapshot'],reverse)
            value['ids']=copy.deepcopy(command['snapshot']['ids_before' if reverse else 'ids_after'])
            value['focus_id']=command['paragraph_ids'][0]
        elif 'snapshot' in command:
            from .structure import decoded
            snapshot=command['snapshot']
            expected=decoded(snapshot['after_file'] if reverse else snapshot['before_file'])
            if book.get(snapshot['file'])!=expected:raise EditConflict('段落の構造が変更されています。操作を中止しました。')
            value['working']=WorkingFiles.merge(book.original,{snapshot['file']:decoded(snapshot['before_file'] if reverse else snapshot['after_file'])})
            value['ids'][snapshot['chapter_id']]=snapshot['ids_before'] if reverse else snapshot['ids_after']
        else:
            value['working'] = apply_changes(book, command['changes'], reverse=reverse)
        value['cursor'] += -1 if reverse else 1
        if reverse and value['cursor'] == 0:
            value['working'] = initial_working(con.execute('SELECT original FROM books WHERE id=?',(book_id,)).fetchone()[0])
            value['ids']={}
        value['history'].append({'id':str(uuid.uuid4()),'timestamp':timestamp(),'action':kind,'command_id':command['id'],'paragraph_ids':command['paragraph_ids'],'before':command['after'] if reverse else command['before'],'after':command['before'] if reverse else command['after'],'source':'manual','state':'undone' if reverse else 'approved','reason':reason})
    else:
        snapshot=None
        ruby_options=None
        chapter_options=None
        if kind=='chapter_split':
            from .chapters import split as chapter_split
            boundary=None
            if chapter_position is not None:
                d=paragraph_details(book,paragraph_id,value['revision']);span=None
                if sentence_index is not None:
                    if not 0<=sentence_index<len(d['sentences']):raise EpubError('選択した文が見つかりません。')
                    span=d['sentences'][sentence_index]
                boundary=(span['start'] if span else 0) if chapter_position=='before' else (span['end'] if span else len(d['editor_text']))
            value['working'],snapshot,paragraphs,before,after,focus,chapter_options=chapter_split(book,paragraph_id,text or '',level=chapter_level,boundary=boundary,boundary_after=chapter_position=='after')
            value['ids']=snapshot['ids_after'];value['focus_id']=focus;changes=[]
        elif kind in {'ruby_add','ruby_delete'}:
            from .ruby_structure import operate as ruby_operate
            value['working'],snapshot,paragraphs,before,after,focus,ruby_options=ruby_operate(book,paragraph_id,kind,range_start,range_end,reading,ruby_index)
            value['focus_id']=focus;changes=[]
        elif kind in {'insert','split','merge','merge_next'}:
            from .structure import operate
            boundary=None
            if kind=='insert' and sentence_index is not None:
                d=paragraph_details(book,paragraph_id,value['revision'])
                if not 0<=sentence_index<len(d['sentences']):raise EpubError('選択した文が見つかりません。')
                boundary=d['sentences'][sentence_index]['start' if position=='before' else 'end']
            value['working'],snapshot,paragraphs,before,after,focus=operate(book,paragraph_id,kind,position=position,text=text or '',offset=offset,boundary=boundary)
            value['ids'][snapshot['chapter_id']]=snapshot['ids_after']
            value['focus_id']=focus
            changes=[]
        elif kind == 'combined':
            details=paragraph_details(book,paragraph_id,value['revision'])
            span=None
            if sentence_index is not None:
                if not 0<=sentence_index<len(details['sentences']):raise EpubError('文が見つかりません。')
                sentence=details['sentences'][sentence_index]
                if expected_sentence!=sentence['text']:raise EditConflict('選択した文が変更されています。')
                span=(sentence['start'],sentence['end'])
            # The body field retains the original ruby bases. Dedicated paired fields
            # change base/reading atomically, after calculating text-node differences.
            changes,before_text,after_text=text_changes(book,paragraph_id,text,span)
            before={'text':before_text,'rubies':[]};after={'text':after_text,'rubies':[]}
            seen=set()
            for ruby in rubies or []:
                index=ruby['index']
                if index in seen:raise EpubError('同じルビの指定が重複しています。')
                seen.add(index)
                if not 0<=index<len(details['rubies']):raise EpubError('ルビが見つかりません。')
                current=details['rubies'][index]
                if span and not (span[0]<=current['start'] and current['end']<=span[1]):raise EpubError('選択した文の外のルビは変更できません。')
                patch,b,a=ruby_changes(book,paragraph_id,index,ruby['base'],ruby['reading'])
                changes.extend(patch);before['rubies'].append({'index':index,**b});after['rubies'].append({'index':index,**a})
            paragraphs=[paragraph_id]
        elif kind == 'sentence':
            details=paragraph_details(book,paragraph_id,value['revision'])
            if sentence_index is None or sentence_index<0 or sentence_index>=len(details['sentences']):raise EpubError('文が見つかりません。章を読み込み直してください。')
            sentence=details['sentences'][sentence_index]
            if expected_sentence is not None and expected_sentence!=sentence['text']:raise EditConflict('選択した文が変更されています。')
            changes,before,after=text_changes(book,paragraph_id,text,(sentence['start'],sentence['end']))
            paragraphs=[paragraph_id]
        elif kind == 'text':
            span=None
            if span_start is not None:
                current=text_layout(book,paragraph_id)[-1]
                if span_end is None or not 0<=span_start<=span_end<=len(current) or current[span_start:span_end]!=expected_span:raise EditConflict('AI候補の対象範囲が一致しません。')
                span=(span_start,span_end)
            changes,before,after = text_changes(book,paragraph_id,text,span)
            paragraphs = [paragraph_id]
        elif kind == 'ruby':
            changes,before,after = ruby_changes(book,paragraph_id,ruby_index,base,reading,range_start,range_end)
            paragraphs = [paragraph_id]
        elif kind == 'replace':
            if not target or target == replacement or len(target) > 1000 or len(replacement) > 1000:
                raise EpubError('異なる検索文字列・置換文字列を指定してください（各1000文字まで）。')
            changes,before,after,paragraphs = [],{}, {},[]
            ids = [paragraph_id] if paragraph_id else [p['id'] for c in book.chapters for p in c['paragraphs']]
            for ident in ids:
                *_,pieces,current = text_layout(book,ident)
                # Replace only occurrences wholly inside editable runs, without guessing ruby boundaries.
                positions = []
                offset = 0
                while (start := current.find(target,offset)) >= 0:
                    end = start + len(target); offset = end
                    if not any(p['protected'] and p['end'] > start and p['start'] < end for p in pieces):
                        positions.append((start,end))
                result = current
                for start,end in reversed(positions):
                    result = result[:start] + replacement + result[end:]
                if result != current:
                    patch,b,a = text_changes(book,ident,result)
                    changes.extend(patch); before[ident]=b; after[ident]=a; paragraphs.append(ident)
            if len(changes) > 10000:
                raise EpubError('置換件数が多すぎます。対象を段落単位に絞ってください。')
        else:
            raise EpubError('未対応の編集操作です。')
        if not changes and snapshot is None:
            return value
        if snapshot is None:value['working'] = apply_changes(book,changes)
        command = {'id':str(uuid.uuid4()), 'timestamp':timestamp(), 'action':kind, 'changes':changes, 'paragraph_ids':paragraphs, 'before':before, 'after':after, 'source':source, 'state':'approved', 'reason':reason}
        if ruby_options is not None:command.update(undoable=False,ruby_options=ruby_options)
        if chapter_options is not None:command['chapter_options']=chapter_options
        if candidate_id:command.update(candidate_id=candidate_id,engine_id=engine_id)
        if snapshot is not None:command['snapshot']=snapshot
        value['commands'] = value['commands'][:value['cursor']] + [command]
        value['cursor'] += 1
        value['history'].append({k:v for k,v in command.items() if k not in {'changes','snapshot'}})
    # Reject invalid XML/EPUB before committing anything.
    working_model(value)
    value['revision'] += 1
    save_state(con,book_id,value)
    return value
