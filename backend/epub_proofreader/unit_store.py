"""Normalized XHTML storage. Order belongs to the tree; identity never does.

Editable leaves are complete paragraph/heading elements, including inline XML.
Other elements, attributes, comments, text and tails stay in a lossless skeleton.
No reconstruction or EPUB ZIP assembly is needed for an ordinary leaf update.
"""
import copy
import hashlib
import json
import sqlite3
import time
import uuid
import threading
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from collections.abc import Mapping
from types import SimpleNamespace
from contextvars import ContextVar
from lxml import etree
from .epub import Book, EpubError, NS, local, xml, base_text, simple_ruby
from .segments import describe, layout

DIGITS='0123456789abcdef'
EDITABLE={'p','h1','h2','h3','h4','h5','h6'}
DB_NAME='epub-proofreader-units.sqlite3'
USE_NEW_STORAGE=True
edit_owner=ContextVar('unit_edit_owner',default=None)
preparation_lock=threading.RLock()


def ensure(con):
    from . import proof_score
    proof_score.ensure(con)
    con.execute('CREATE TABLE IF NOT EXISTS unit_books(book_id TEXT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,revision INTEGER NOT NULL DEFAULT 0,edits INTEGER NOT NULL DEFAULT 0)')
    con.execute('CREATE TABLE IF NOT EXISTS unit_files(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,path TEXT NOT NULL,root_id TEXT NOT NULL,encoding TEXT NOT NULL,doctype TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(book_id,path))')
    con.execute('CREATE TABLE IF NOT EXISTS unit_nodes(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,id TEXT NOT NULL,file TEXT NOT NULL,parent TEXT,ordering TEXT NOT NULL COLLATE BINARY,kind TEXT NOT NULL,xml BLOB NOT NULL,tail TEXT,version INTEGER NOT NULL DEFAULT 1,active INTEGER NOT NULL DEFAULT 1,record TEXT,PRIMARY KEY(book_id,id))')
    con.execute('CREATE INDEX IF NOT EXISTS unit_children ON unit_nodes(book_id,parent,active,ordering)')
    con.execute('CREATE TABLE IF NOT EXISTS unit_locks(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,unit_id TEXT NOT NULL,owner TEXT NOT NULL,expires REAL NOT NULL,PRIMARY KEY(book_id,unit_id))')
    con.execute('CREATE TABLE IF NOT EXISTS unit_reviews(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,unit_id TEXT NOT NULL,version INTEGER NOT NULL,target TEXT NOT NULL,start INTEGER NOT NULL,end INTEGER NOT NULL,PRIMARY KEY(book_id,unit_id,version,target,start,end))')
    con.execute('CREATE TABLE IF NOT EXISTS unit_resources(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,path TEXT NOT NULL,data BLOB NOT NULL,PRIMARY KEY(book_id,path))')
    con.execute('CREATE TABLE IF NOT EXISTS ai_result_units(result_id TEXT NOT NULL REFERENCES ai_results(id) ON DELETE CASCADE,unit_id TEXT NOT NULL,version INTEGER NOT NULL,start INTEGER NOT NULL,end INTEGER NOT NULL,PRIMARY KEY(result_id,unit_id,start,end))')
    con.execute('CREATE TABLE IF NOT EXISTS unit_locations(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,unit_id TEXT NOT NULL,chapter_id TEXT NOT NULL,previous_id TEXT,next_id TEXT,PRIMARY KEY(book_id,unit_id))')
    con.execute('CREATE TABLE IF NOT EXISTS unit_file_joins(book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,path TEXT NOT NULL,PRIMARY KEY(book_id,path))')


def enabled(con,book_id):
    try:return con.execute('SELECT 1 FROM unit_books WHERE book_id=?',(book_id,)).fetchone() is not None
    except sqlite3.OperationalError as exc:
        if 'no such table: unit_books' in str(exc):return False
        raise
def key_between(left=None,right=None):
    """Dense hexadecimal fractional keys. No floating point or renumbering."""
    if left is not None and right is not None and left>=right:raise EpubError('並び順の範囲が不正です。')
    prefix='';i=0
    while True:
        lo=DIGITS.index(left[i]) if left and i<len(left) else 0
        hi=DIGITS.index(right[i]) if right and i<len(right) else 16
        if hi-lo>1:return prefix+DIGITS[(lo+hi)//2]
        prefix+=DIGITS[lo]
        if lo<hi:right=None
        i+=1


def identifier():return 'unit-'+uuid.uuid4().hex
def dump(node):return etree.tostring(node,encoding='UTF-8',with_tail=False)
def canonical(node):
    # Serialize/reparse the standalone root first. libxml's C14N namespace
    # context differs for roots that originally had PI/comment siblings.
    return etree.tostring(xml(dump(node)),method='c14n')


def leaf_record(node,ident,version=1,original=None):
    root=node.getroottree();rubies=[]
    for r in node.xpath('.//x:ruby',namespaces=NS):
        rubies.append(dict(xpath=root.getpath(r),base=base_text(r),readings=[''.join(t.itertext()) for t in r.xpath('.//x:rt',namespaces=NS)],editable=simple_ruby(r),original_xml=etree.tostring(r,encoding='unicode',with_tail=False)))
    content=etree.tostring(node,encoding='unicode',with_tail=False)
    original=original or dict(original_xml=content,original_text=base_text(node))
    return dict(id=ident,element_tag=local(node),xpath=root.getpath(node),text=base_text(node),rubies=rubies,status='unchecked',revision=0,unit_version=version,
                original_xml=original['original_xml'],original_text=original.get('original_text',''),current_xml=content,edited=content!=original['original_xml'],**describe(node)[0])


def fragment(data,ident,version=1,original=None):
    node=xml(data);node.tail=None
    root=etree.Element('{'+NS['x']+'}html',nsmap={None:NS['x']});etree.SubElement(root,'{'+NS['x']+'}head');body=etree.SubElement(root,'{'+NS['x']+'}body');body.append(node)
    return root,node,leaf_record(node,ident,version,original)


def initialize(con,book_id,book):
    con.execute('INSERT INTO unit_books VALUES (?,0,0)',(book_id,))
    identities={}
    for c in book.chapters:
        for p in [*c['paragraphs'],*c['headings']]:identities[(c['path'],p['xpath'])]=p['id']
    # Every XHTML is retained, including navigation and unspined resources.
    for path,tree in book.trees.items():
        def visit(node,parent,order):
            ident=identities.get((path,tree.getroottree().getpath(node)),identifier())
            editable=isinstance(node.tag,str) and local(node) in EDITABLE
            # Lists/quotes containing paragraphs remain skeleton containers.
            if not editable and (path,tree.getroottree().getpath(node)) in identities:editable=True
            kind='unit' if editable else 'container' if isinstance(node.tag,str) and any(isinstance(c.tag,str) for c in node) else 'opaque'
            cloned=copy.deepcopy(node)
            if kind=='container':
                for child in list(cloned):cloned.remove(child)
            record=None
            if editable:_,_,r=fragment(dump(node),ident);record=json.dumps(r,ensure_ascii=False)
            con.execute('INSERT INTO unit_nodes VALUES (?,?,?,?,?,?,?,?,1,1,?)',(book_id,ident,path,parent,order,kind,dump(cloned),node.tail,record))
            if kind=='container':
                for i,child in enumerate(node,1):visit(child,ident,f'{i:012x}8')
            return ident
        root=visit(tree,None,'8');doc=tree.getroottree().docinfo
        con.execute('INSERT INTO unit_files VALUES (?,?,?,?,?,1)',(book_id,path,root,doc.encoding or 'UTF-8',doc.doctype or ''))
    update_locations(con,book_id)
    rebuilt=state(con,book_id,book.normalized)['working'].model()
    for path,tree in book.trees.items():
        restored,_=rebuilt.build_tree(path)
        if canonical(restored)!=canonical(tree):raise EpubError('本文の分割保存と復元が一致しません。移行を中止しました。')


def update_locations(con,book_id):
    book=state(con,book_id,con.execute('SELECT original FROM books WHERE id=?',(book_id,)).fetchone()[0])['working'].model()
    paragraphs=[(c,p) for c in book.chapters for p in c['paragraphs']]
    con.execute('DELETE FROM unit_locations WHERE book_id=?',(book_id,))
    for i,(c,p) in enumerate(paragraphs):
        con.execute('INSERT INTO unit_locations VALUES (?,?,?,?,?)',(book_id,p['id'],c['id'],paragraphs[i-1][1]['id'] if i else None,paragraphs[i+1][1]['id'] if i+1<len(paragraphs) else None))
    from . import proof_score
    proof_score.rebuild(con,book_id,book)


def rows(con,book_id):
    return tuple(tuple(r) for r in con.execute('SELECT id,file,parent,ordering,kind,xml,tail,version,active,record FROM unit_nodes WHERE book_id=? ORDER BY file,ordering,id',(book_id,)))


@dataclass(frozen=True)
class Source:
    base:bytes
    book_id:str
    revision:int
    nodes:tuple
    files:tuple
    resources:tuple=()
    joins:tuple=()
    @property
    def fingerprint(self):return hashlib.sha256((hashlib.sha256(self.base).hexdigest()+':'+self.book_id+':'+str(self.revision)).encode()).hexdigest()
    def model(self):return model(self)
    def materialize(self):
        from .editing import repack
        b=self.model();return repack(self.base,{**{p:b.get(p) for p,*_ in self.files},**dict(self.resources)})


class Trees(Mapping):
    def __init__(self,book):self.book=book;self.cache={}
    def __iter__(self):return iter(self.book.file_info)
    def __len__(self):return len(self.book.file_info)
    def __getitem__(self,path):
        if path not in self.cache:self.cache[path]=xml(self.book.get(path),path)
        return self.cache[path]


class Files(Mapping):
    def __init__(self,book,base):self.book=book;self.base=base
    def __iter__(self):return iter(self.base)
    def __len__(self):return len(self.base)
    def __getitem__(self,path):return self.book.get(path)


@lru_cache(maxsize=4)
def model(source):return UnitBook(source)


class UnitBook(Book):
    def __init__(self,source):
        from .working import baseline
        original=baseline(source.base)
        self.baseline=original
        self.__dict__.update(original.__dict__)
        self.original=source;self.fingerprint=source.fingerprint;self.source=source
        self.file_info={r[0]:r[1:] for r in source.files};self.node_info={r[0]:r for r in source.nodes};self.children={}
        for r in source.nodes:
            if r[8]:self.children.setdefault(r[2],[]).append(r)
        for children in self.children.values():children.sort(key=lambda r:r[3])
        self.files=Files(self,original.files);self.trees=Trees(self);self.chapters=[];self.unit_records={}
        current=None
        for old in original.chapters:
            if old['path'] not in source.joins:current=None
            file=old['path'];ordered=[]
            def walk(ident):
                row=self.node_info[ident]
                if row[4]=='unit':ordered.append(row)
                else:
                    for child in self.children.get(ident,[]):walk(child[0])
            walk(self.file_info[file][0])
            for row in ordered:
                rec=json.loads(row[9]);tag=rec['element_tag']
                rec.update(unit_version=row[7],revision=source.revision);self.unit_records[row[0]]=rec
                heading=tag in {'h1','h2','h3','h4','h5','h6'}
                if current is None or heading:
                    current=dict(id='section-'+(row[0] if heading else hashlib.sha256(file.encode()).hexdigest()[:16]),path=file,parts=[file],title=rec['text'] if heading else old['title'],heading_level=int(tag[1]) if heading else old.get('heading_level',1),paragraphs=[],headings=[],writing_mode=old['writing_mode'])
                    self.chapters.append(current)
                if file not in current['parts']:current['parts'].append(file)
                if heading:current['headings'].append({**rec,'next_paragraph_index':0})
                else:current['paragraphs'].append(rec)
            if not ordered:
                if current is not None:current['parts'].append(file)
                else:self.chapters.append({**old,'id':'section-'+hashlib.sha256(file.encode()).hexdigest()[:16],'parts':[file],'paragraphs':[],'headings':[]})
        self.refresh_units()
        self.unit_chapters={p['id']:c for c in self.chapters for p in [*c['paragraphs'],*c['headings']]}
        self.toc=copy.deepcopy(original.toc)
        from .epub import reference
        from urllib.parse import urlsplit
        for m in self.manifest:
            if 'nav' in m['properties'].split() and self.file_info.get(m['path'],(None,None,None,1))[3]>1:
                self.toc=[dict(label=''.join(a.itertext()),path=reference(m['path'],a.get('href','')),fragment=urlsplit(a.get('href','')).fragment) for a in xml(self.get(m['path'])).xpath('//x:nav[@*[local-name()="type"]="toc"]//x:a',namespaces=NS)]

    def get(self,path):
        if path in dict(self.source.resources):return dict(self.source.resources)[path]
        if path not in self.file_info:return self.files.base[path]
        rootid,encoding,doctype,version=self.file_info[path]
        if version==1:return self.files.base[path]
        root,_=self.build_tree(path);root.tail=None
        template=self.baseline.trees[path]
        before=[];node=template.getprevious()
        while node is not None:before.append(node);node=node.getprevious()
        for node in reversed(before):root.addprevious(copy.deepcopy(node))
        after=[];node=template.getnext()
        while node is not None:after.append(node);node=node.getnext()
        for node in reversed(after):root.addnext(copy.deepcopy(node))
        declaration=re.match(br'\s*<\?xml\s+[^?]*\?>',self.files.base[path])
        standalone=None
        if declaration:
            match=re.search(br'''standalone\s*=\s*['"](yes|no)['"]''',declaration[0])
            if match:standalone=match[1]==b'yes'
        return etree.tostring(root.getroottree(),encoding=encoding,xml_declaration=bool(declaration),doctype=doctype or None,standalone=standalone)

    def build_tree(self,path):
        mapping={}
        def build(ident):
            row=self.node_info[ident];node=copy.deepcopy(xml(b'<wrapper>'+row[5]+b'</wrapper>')[0]) if row[4]=='opaque' else xml(row[5])
            mapping[ident]=node
            node.tail=row[6]
            if row[4]=='container':
                for child in self.children.get(ident,[]):node.append(build(child[0]))
            return node
        return build(self.file_info[path][0]),mapping

    def apply_ids(self,mapping):return self

    def summary(self):return {**super().summary(),'storage_mode':'units'}

    def preview(self,chapter_id,book_id):
        c=next((c for c in self.chapters if c['id']==chapter_id),None)
        if c is None:raise EpubError('章がありません。')
        return ''.join(self.preview_part(c,path,book_id) for path in c.get('parts',[c['path']]))

    def preview_part(self,c,path,book_id):
        # Prune only outside the logical section; retain images, tables, wrapper
        # attributes and non-paragraph text in the rendered section.
        root,mapping=self.build_tree(path);body=root.find('x:body',NS)
        wanted={p['id'] for p in [*c['paragraphs'],*c['headings']] if self.node_info[p['id']][1]==path}
        inverse={node:ident for ident,node in mapping.items()};positions={node:i for i,node in enumerate(root.iter())}
        group=[ch for ch in self.chapters if path in ch.get('parts',[ch['path']])];at=group.index(c)
        start=min((positions[mapping[pid]] for pid in wanted),default=0) if at else 0
        nextids={p['id'] for p in [*group[at+1]['paragraphs'],*group[at+1]['headings']] if self.node_info[p['id']][1]==path} if at+1<len(group) else set()
        end=min((positions[mapping[pid]] for pid in nextids),default=float('inf'))
        def keep(node):
            ident=inverse.get(node);r=self.node_info.get(ident)
            if r and r[4]=='unit':return ident in wanted
            children=list(node)
            for child in children:
                if not keep(child):node.remove(child)
            inside=start<=positions[node]<end
            if not inside:node.text=None
            return bool(len(node)) or inside
        for child in list(body):
            if not keep(child):body.remove(child)
        temp=copy.copy(self);temp.trees={path:root};parsed=Book.analyze_chapter(temp,path,1)
        for key in ('paragraphs','headings'):
            records=[]
            for rec in parsed[key]:
                node=root.xpath(rec['xpath'],namespaces=NS)[0]
                # A leaf may contain nested list items/headings. They remain
                # part of that leaf rather than gaining a second storage ID.
                if node not in inverse or inverse[node] not in wanted:continue
                rec['id']=inverse[node];records.append(rec)
            parsed[key]=records
        parsed['id']=c['id'];temp.chapters=[parsed]
        return Book.preview(temp,c['id'],book_id)

    def document_rows(self,path):
        result=[]
        def walk(ident):
            r=self.node_info[ident];result.append(r)
            for child in self.children.get(ident,[]):walk(child[0])
        walk(self.file_info[path][0]);return result


def state(con,book_id,base):
    from .editing import initial_working
    base=initial_working(base)
    rev,edits=con.execute('SELECT revision,edits FROM unit_books WHERE book_id=?',(book_id,)).fetchone()
    files=tuple(tuple(r) for r in con.execute('SELECT path,root_id,encoding,doctype,version FROM unit_files WHERE book_id=? ORDER BY path',(book_id,)))
    resources=tuple(tuple(r) for r in con.execute('SELECT path,data FROM unit_resources WHERE book_id=? ORDER BY path',(book_id,)))
    joins=tuple(r[0] for r in con.execute('SELECT path FROM unit_file_joins WHERE book_id=? ORDER BY path',(book_id,)))
    from . import proof_score
    return dict(working=Source(base,book_id,rev,rows(con,book_id),files,resources,joins),revision=rev,commands=[],cursor=0,history=[],ids={},unit_edits=edits,proof_score=proof_score.read(con,book_id))


def details(book,pid,revision,include_tokens=True,include_chapter_token=True):
    from .editing import ruby_limits
    row=book.node_info.get(pid)
    if not row or not row[8] or row[4]!='unit':raise EpubError('段落が見つかりません。')
    root,node,record=fragment(row[5],pid,row[7],json.loads(row[9]));_,_,ranges=layout(node)
    rubies=[{**r,'index':i,'start':ranges[i][1],'end':ranges[i][2],**ruby_limits(ranges[i])} for i,r in enumerate(record['rubies'])]
    result={**record,'rubies':rubies,'path':row[1],'revision':revision,'editor_text':layout(node)[0],'protected_ranges':[]}
    if include_tokens:result['token']=token(row)
    if include_tokens and include_chapter_token:result['chapter_token']=hashlib.sha256((row[1]+':'+str(book.file_info[row[1]][3])).encode()).hexdigest()
    return result


def token(row):return hashlib.sha256(str(row[7]).encode()+b':'+row[5]).hexdigest()


def row(con,book_id,pid):
    r=con.execute('SELECT id,file,parent,ordering,kind,xml,tail,version,active,record FROM unit_nodes WHERE book_id=? AND id=?',(book_id,pid)).fetchone()
    if not r or not r[8] or r[4]!='unit':raise EpubError('段落が見つかりません。')
    return tuple(r)


def lock(con,book_id,pid,owner,release=False):
    from .editing import EditConflict
    if not owner or len(owner)>128:raise EditConflict('編集用ブラウザーIDがありません。画面を再読み込みしてください。')
    row(con,book_id,pid);now=time.time()
    prior=con.execute('SELECT owner,expires FROM unit_locks WHERE book_id=? AND unit_id=?',(book_id,pid)).fetchone()
    if release:
        con.execute('DELETE FROM unit_locks WHERE book_id=? AND unit_id=? AND owner=?',(book_id,pid,owner));return
    if prior and prior[0]!=owner and prior[1]>now:raise EditConflict('この箇所は別のブラウザーで編集中です。入力内容は保持しています。')
    con.execute('INSERT INTO unit_locks VALUES (?,?,?,?) ON CONFLICT(book_id,unit_id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',(book_id,pid,owner,now+60))


def write(con,book_id,old,node):
    from .editing import EditConflict
    data=dump(node);_,_,record=fragment(data,old[0],old[7]+1,json.loads(old[9]))
    n=con.execute('UPDATE unit_nodes SET xml=?,version=version+1,record=? WHERE book_id=? AND id=? AND version=? AND active=1',(data,json.dumps(record,ensure_ascii=False),book_id,old[0],old[7])).rowcount
    if n!=1:raise EditConflict('本文が別の画面で更新されました。入力内容は保持しています。')
    con.execute('UPDATE unit_files SET version=version+1 WHERE book_id=? AND path=?',(book_id,old[1]))
    con.execute('UPDATE unit_books SET revision=revision+1,edits=edits+1 WHERE book_id=?',(book_id,))
    from . import projects
    meta=projects.read(con,book_id);meta.setdefault('reviews',{}).pop(old[0],None);meta['statuses'][old[0]]='unchecked';projects.write(con,book_id,meta)
    from . import proof_score
    proof_score.refresh_unit(con,book_id,old[0],{**record,'editor_text':layout(node)[0]},meta)
    return record


def direct_details(con,book_id,pid):
    r=row(con,book_id,pid);root,node,record=fragment(r[5],pid,r[7],json.loads(r[9]))
    from .editing import ruby_limits
    _,_,ranges=layout(node)
    record['rubies']=[{**v,'index':i,'start':ranges[i][1],'end':ranges[i][2],**ruby_limits(ranges[i])} for i,v in enumerate(record['rubies'])]
    revision=con.execute('SELECT revision FROM unit_books WHERE book_id=?',(book_id,)).fetchone()[0]
    fv=con.execute('SELECT version FROM unit_files WHERE book_id=? AND path=?',(book_id,r[1])).fetchone()[0]
    record.update(token=token(r),chapter_token=hashlib.sha256((r[1]+':'+str(fv)).encode()).hexdigest(),revision=revision,path=r[1],editor_text=layout(node)[0],protected_ranges=[])
    from .editing import text_layout
    fake,_=fake_book(r);pieces=text_layout(fake,pid)[-2]
    record['protected_ranges']=[{'start':p['start'],'end':p['end']} for p in pieces if p['protected']]
    from . import reviews,projects
    record['review_state']=reviews.both(projects.read(con,book_id),record)
    return record


def fake_book(r):
    root,node,record=fragment(r[5],r[0],r[7],json.loads(r[9]));chapter=dict(path=r[1],paragraphs=[record],headings=[])
    return SimpleNamespace(trees={r[1]:root},chapters=[chapter]),node


def apply_patches(fake,node,patches):
    from .editing import EditConflict
    root=node.getroottree();index={root.getpath(e):e for e in root.iter()}
    for p in patches:
        target=index[p['xpath']]
        if (getattr(target,p['field']) or '')!=p['before']:raise EditConflict('編集対象の本文が一致しません。')
        try:setattr(target,p['field'],p['after'] or None)
        except ValueError:raise EpubError('XMLで使用できない文字が含まれています。') from None


def confirm(con,book_id,pid,target='body',index=None,expected_token=None,compact=True,draft_patch=None):
    from . import reviews,projects,editing
    r=row(con,book_id,pid)
    if expected_token and expected_token!=token(r):raise editing.EditConflict('この箇所が別の画面で更新されました。')
    lock(con,book_id,pid,edit_owner.get())
    d=direct_details(con,book_id,pid);meta=projects.read(con,book_id)
    marks=meta.setdefault('reviews',{}).get(pid,{})
    if marks.get('version')!=r[7]:marks={'version':r[7]};meta['reviews'][pid]=marks
    ranges=marks.setdefault(target,{})
    if target=='body':
        if index is None or d['unit_mode']!='sentence':a,b=0,len(d['editor_text']);ranges['all']=reviews.digest(d['editor_text'])
        else:
            if not 0<=index<len(d['sentences']):raise EpubError('文が見つかりません。')
            s=d['sentences'][index];a,b=s['start'],s['end'];ranges[str(index)]=reviews.digest(s['text'])
    else:
        if index is None:
            a,b=0,len(d['editor_text']);ranges['all']=reviews.digest([d['editor_text'],[(v['base'],v['readings']) for v in d['rubies']]])
        else:
            if not 0<=index<len(d['rubies']):raise EpubError('ルビが見つかりません。')
            v=d['rubies'][index];a,b=v['start'],v['end'];ranges[str(index)]=reviews.digest([d['editor_text'],v['base'],v['readings']])
    con.execute('INSERT OR IGNORE INTO unit_reviews VALUES (?,?,?,?,?,?)',(book_id,pid,r[7],target,a,b))
    reviewed=[]
    for ident,data,status in con.execute("SELECT id,data,status FROM ai_results WHERE book_id=? AND paragraph_id=? AND status IN ('pending','held','undone','reviewed')",(book_id,pid)).fetchall():
        v=json.loads(data)
        if (target=='body' and v['target']=='text' and a<=v['start']<=v['end']<=b) or (target=='ruby' and v['target']=='ruby' and (index is None or v.get('ruby_index')==index)):
            con.execute("UPDATE ai_results SET status='reviewed',updated_at=? WHERE id=?",(editing.timestamp(),ident));reviewed.append(ident)
    if draft_patch:
        key=draft_patch['key'];expected=f'body:{pid}:{index if index is not None else "all"}' if target=='body' else f'ruby-review:{pid}:{index}'
        if key!=expected:raise editing.EditConflict('未保存入力の対象が一致しません。')
        old=meta['drafts'].get(key);new=draft_patch.get('value')
        if old!=draft_patch.get('expected') and old!=new:raise editing.EditConflict('未保存入力が別の画面で変更されています。')
        if new is not None and new.get('paragraphId')!=pid:raise editing.EditConflict('未保存入力の段落が一致しません。')
        if new is None:meta['drafts'].pop(key,None)
        else:meta['drafts'][key]=new
    meta['statuses'][pid]='human_checked' if reviews.summary(meta,d)['confirmed'] else 'review';meta['version']+=1;projects.write(con,book_id,meta)
    from . import proof_score
    proof_score.refresh_unit(con,book_id,pid,d,meta)
    return dict(book_id=book_id,revision=d['revision'],paragraph_id=pid,review_state=reviews.both(meta,d),status=meta['statuses'][pid],reviewed_ids=reviewed,project=meta,proof_score=proof_score.read(con,book_id))


def patch(con,book_id,pid):
    from . import projects,editing,proof_score
    d=direct_details(con,book_id,pid);revision,edits=con.execute('SELECT revision,edits FROM unit_books WHERE book_id=?',(book_id,)).fetchone()
    return dict(kind='unit_patch',book_id=book_id,paragraph=d,project=projects.read(con,book_id),file=d['path'],proof_score=proof_score.read(con,book_id),
                edit_state=dict(revision=revision,can_undo=False,can_redo=False,edit_count=edits,history_count=0))


def append_node(con,book_id,source,node,before=False):
    siblings=[tuple(r) for r in con.execute('SELECT id,ordering FROM unit_nodes WHERE book_id=? AND parent=? AND active=1 ORDER BY ordering',(book_id,source[2]))]
    at=sum(r[1]<source[3] or (not before and r[1]==source[3]) for r in siblings)
    left=siblings[at-1][1] if at else None;right=siblings[at][1] if at<len(siblings) else None
    ident=identifier();data=dump(node);_,_,record=fragment(data,ident,original=dict(original_xml='',original_text=''))
    con.execute('INSERT INTO unit_nodes VALUES (?,?,?,?,?,?,?,?,1,1,?)',(book_id,ident,source[1],source[2],key_between(left,right),'unit',data,node.tail,json.dumps(record,ensure_ascii=False)))
    return ident


def bump(con,book_id,path):
    con.execute('UPDATE unit_files SET version=version+1 WHERE book_id=? AND path=?',(book_id,path))
    con.execute('UPDATE unit_books SET revision=revision+1,edits=edits+1 WHERE book_id=?',(book_id,))


def mutate(con,book_id,kind,request,**kw):
    from . import editing,projects
    from .structure import split_element
    pid=kw.get('paragraph_id');r=row(con,book_id,pid);owner=edit_owner.get()
    expected=getattr(request,'expected_token',None)
    if not expected or token(r)!=expected:raise editing.EditConflict('この箇所の版が変わっています。最新版を確認してください。入力は保持しています。')
    lock(con,book_id,pid,owner);fake,node=fake_book(r);d=direct_details(con,book_id,pid);sentence_index=kw.get('sentence_index');span=None
    before_edits=con.execute('SELECT edits FROM unit_books WHERE book_id=?',(book_id,)).fetchone()[0]
    def finish_count():
        con.execute('UPDATE unit_books SET edits=? WHERE book_id=? AND revision>?',(before_edits+1,book_id,d['revision']))
    if sentence_index is not None:
        if not 0<=sentence_index<len(d['sentences']):raise EpubError('選択した文が見つかりません。')
        s=d['sentences'][sentence_index];span=(s['start'],s['end'])
    if kw.get('span_start') is not None:
        a,b=kw['span_start'],kw.get('span_end')
        if type(a) is not int or type(b) is not int or not 0<=a<=b<=len(d['editor_text']) or d['editor_text'][a:b]!=kw.get('expected_span'):raise editing.EditConflict('AIの対象文字列が一致しません。')
        span=(a,b)
    structural=kind not in {'text','sentence','combined','ruby','ruby_add','ruby_delete'}
    if not structural:
        changes=[]
        if kind in {'text','sentence','combined'}:
            if span and kw.get('expected_sentence') not in {None,d['editor_text'][span[0]:span[1]]}:raise editing.EditConflict('選択した文が変更されています。')
            patches,_,_=editing.text_changes(fake,pid,kw.get('text') or '',span);changes+=patches
        if kind=='ruby':
            patches,_,_=editing.ruby_changes(fake,pid,kw.get('ruby_index'),kw.get('base'),kw.get('reading'),kw.get('range_start'),kw.get('range_end'));changes+=patches
        for ruby in kw.get('rubies') or []:
            patches,_,_=editing.ruby_changes(fake,pid,ruby['index'],ruby['base'],ruby['reading']);changes+=patches
        apply_patches(fake,node,changes)
        if kind in {'ruby_add','ruby_delete'}:
            ruby_node(node,kind,kw.get('range_start'),kw.get('range_end'),kw.get('reading'),kw.get('ruby_index'))
        if dump(node)!=r[5]:write(con,book_id,r,node)
        target='ruby' if kind.startswith('ruby') else 'body'
        confirm(con,book_id,pid,target,kw.get('ruby_index') if kind=='ruby' else sentence_index)
        if local(node) in {'h1','h2','h3','h4','h5','h6'}:
            update_navigation(con,book_id)
            update_locations(con,book_id)
            confirm(con,book_id,pid,target,sentence_index)
            finish_count()
            return pid,True
        finish_count()
        return patch(con,book_id,pid),False
    # Structural edits serialize only the affected leaves. Adjacent leases are
    # acquired in the same transaction as all versions and ordering changes.
    focus=pid;position=kw.get('position','after');text=kw.get('text') or ''
    chapter_token=getattr(request,'expected_chapter_token',None)
    if chapter_token and chapter_token!=d['chapter_token']:raise editing.EditConflict('章の構造が変更されました。再読み込みしてください。')
    boundary=(span[0] if position=='before' else span[1]) if span else 0 if position=='before' else len(d['editor_text'])
    if kind=='split':
        boundary=kw.get('offset')
        if type(boundary) is not int or not 0<boundary<len(d['editor_text']):raise EpubError('段落の途中にカーソルを置いてください。')
    if kind=='chapter_split':
        level=kw.get('chapter_level') or 1;position=kw.get('chapter_position') or 'before'
        boundary=(span[0] if position=='before' else span[1]) if span else 0 if position=='before' else len(d['editor_text'])
        if not 1<=level<=6 or not text.strip():raise EpubError('章名と見出しレベルを指定してください。')
        if not any('nav' in m['properties'].split() or m['media_type']=='application/x-dtbncx+xml' for m in Book(state(con,book_id,con.execute('SELECT original FROM books WHERE id=?',(book_id,)).fetchone()[0])['working'].base).manifest):raise EpubError('このEPUBには更新可能な目次ファイルがありません。')
    if kind in {'insert','insert_boundary','blank','split','chapter_split'}:
        parent=con.execute('SELECT xml FROM unit_nodes WHERE book_id=? AND id=?',(book_id,r[2])).fetchone()
        if parent and local(xml(parent[0])) not in {'body','section','article','div','blockquote','aside','main','li','td','th','dd','figure'}:raise EpubError('この位置は段落・見出しを追加できない構造です。通常の本文段落を選択してください。')
        if type(boundary) is not int or not 0<=boundary<=len(d['editor_text']):raise EpubError('分割位置が不正です。')
        middle=0<boundary<len(d['editor_text'])
        insert_source=r;insert_before=boundary==0
        if middle:
            if local(node)!='p':raise EpubError('見出しの途中では分割できません。')
            if any(a<boundary<b for _,a,b in layout(node)[2]):raise EpubError('ルビの途中では分割できません。')
            left,right=split_element(node,boundary);write(con,book_id,r,left)
            right.tail=r[6]
            con.execute('UPDATE unit_nodes SET tail=NULL WHERE book_id=? AND id=?',(book_id,pid))
            rightid=append_node(con,book_id,r,right);focus=rightid;insert_source=row(con,book_id,rightid);insert_before=True
            meta=projects.read(con,book_id)
            if pid in meta['mappings']:meta['mappings'][rightid]=copy.deepcopy(meta['mappings'][pid]);projects.write(con,book_id,meta)
        if kind=='split' or kind=='insert_boundary' and not text.strip() and middle:pass
        else:
            new=etree.Element('{'+NS['x']+'}'+('h'+str(kw.get('chapter_level') or 1) if kind=='chapter_split' else 'p'),nsmap=node.nsmap)
            try:new.text=text.strip() if kind=='chapter_split' else None if kind=='blank' or not text.strip() else text
            except ValueError:raise EpubError('XMLで使用できない文字が含まれています。') from None
            if kind=='chapter_split':new.set('id','chapter-'+uuid.uuid4().hex)
            focus=append_node(con,book_id,insert_source,new,insert_before)
        bump(con,book_id,r[1])
    elif kind in {'merge','merge_next'}:
        siblings=[tuple(v) for v in con.execute('SELECT id,kind,xml FROM unit_nodes WHERE book_id=? AND parent=? AND active=1 ORDER BY ordering',(book_id,r[2]))]
        at=next(i for i,v in enumerate(siblings) if v[0]==pid);other=at-1 if kind=='merge' else at+1
        if not 0<=other<len(siblings) or siblings[other][1]!='unit':raise EpubError('隣接する段落がありません。')
        otherrow=row(con,book_id,siblings[other][0]);lock(con,book_id,otherrow[0],owner)
        prior,later=(otherrow,r) if kind=='merge' else (r,otherrow)
        a=xml(prior[5]);b=xml(later[5])
        if local(a)!='p' or local(b)!='p':raise EpubError('見出し・画像をまたぐ統合はできません。')
        if (prior[6] or '').strip():raise EpubError('段落の間に段落外の文字があるため、統合を保護しています。')
        b.tag='{'+NS['x']+'}span';a.append(b);write(con,book_id,prior,a)
        con.execute('UPDATE unit_nodes SET tail=? WHERE book_id=? AND id=?',((prior[6] or '')+(later[6] or ''),book_id,prior[0]))
        con.execute('UPDATE unit_nodes SET active=0,version=version+1 WHERE book_id=? AND id=?',(book_id,later[0]));focus=prior[0]
    elif kind in {'delete','chapter_merge'}:
        if kind=='chapter_merge':
            if local(node) not in {'h1','h2','h3','h4','h5','h6'}:raise EpubError('章の見出しを選択してください。')
            model=state(con,book_id,con.execute('SELECT original FROM books WHERE id=?',(book_id,)).fetchone()[0])['working'].model()
            if model.chapters[0]['id']==model.unit_chapters[pid]['id']:raise EpubError('先頭の章は削除できません。')
            section=model.unit_chapters[pid];index=model.chapters.index(section);previous=model.chapters[index-1]
            if section['path']!=previous['path']:
                # Logical chapter joins leave both original XHTML resources in
                # place. Relative images/links and the OPF spine remain intact.
                for path in section.get('parts',[section['path']]):
                    con.execute('INSERT OR IGNORE INTO unit_file_joins VALUES (?,?)',(book_id,path))
        if span and (span[0]>0 or span[1]<len(d['editor_text'])):
            a,b=span
            if any(x<cut<y for _,x,y in layout(node)[2] for cut in (a,b)):raise EpubError('ルビの途中では削除できません。')
            left,_=split_element(node,a);_,right=split_element(node,b);right.tag='{'+NS['x']+'}span';left.append(right)
            ids=lambda n:set(n.xpath('descendant-or-self::*/@id | descendant-or-self::*/@xml:id',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'}))
            for ident in sorted(ids(node)-ids(left)):etree.SubElement(left,'{'+NS['x']+'}span',id=ident)
            write(con,book_id,r,left)
        else:
            anchors=node.xpath('descendant-or-self::*/@id | descendant-or-self::*/@xml:id',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'})
            con.execute('UPDATE unit_nodes SET active=0,version=version+1 WHERE book_id=? AND id=?',(book_id,pid))
            if anchors or r[6]:
                marker=etree.Element('{'+NS['x']+'}span',nsmap=node.nsmap)
                for ident in dict.fromkeys(anchors):etree.SubElement(marker,'{'+NS['x']+'}span',id=ident)
                con.execute('INSERT INTO unit_nodes VALUES (?,?,?,?,?,?,?,?,1,1,NULL)',(book_id,identifier(),r[1],r[2],r[3],'opaque',dump(marker),r[6]))
            focus=None
            bump(con,book_id,r[1])
            # Keep an editable empty paragraph in a section that has no body.
            current=state(con,book_id,con.execute('SELECT original FROM books WHERE id=?',(book_id,)).fetchone()[0])['working'].model()
            if kind=='delete' and not any(c['paragraphs'] for c in current.chapters if c['path']==r[1]):
                focus=append_node(con,book_id,r,etree.Element('{'+NS['x']+'}p',nsmap=node.nsmap))
    else:raise EpubError('この編集操作は新しい保存方式に対応していません。')
    meta=projects.read(con,book_id);meta.setdefault('reviews',{}).pop(pid,None);meta['statuses'][pid]='unchecked';meta['version']+=1;projects.write(con,book_id,meta)
    if kind in {'chapter_split','chapter_merge'} or local(node) in {'h1','h2','h3','h4','h5','h6'}:update_navigation(con,book_id)
    update_locations(con,book_id)
    finish_count()
    return focus,True


def ruby_node(node,kind,start,end,reading,index):
    content,slots,rubies=layout(node);ns='{'+NS['x']+'}'
    if kind=='ruby_add':
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(content) or not reading or not reading.strip():raise EpubError('親文字と読みを指定してください。')
        if any(a<end and b>start for _,a,b in rubies):raise EpubError('既存のルビと範囲が重なっています。')
        found=next(((e,f,a,b) for e,f,a,b in slots if a<=start<end<=b and not e.xpath('ancestor-or-self::x:rt | ancestor-or-self::x:rp',namespaces=NS)),None)
        if found is None:raise EpubError('装飾やリンクをまたぐルビ追加はできません。')
        e,f,a,b=found;value=getattr(e,f) or '';r=etree.Element(ns+'ruby');r.text=content[start:end];etree.SubElement(r,ns+'rt').text=reading;r.tail=value[end-a:] or None;setattr(e,f,value[:start-a] or None)
        if f=='text':e.insert(0,r)
        else:e.addnext(r)
    else:
        if type(index) is not int or not 0<=index<len(rubies):raise EpubError('ルビが見つかりません。')
        r=rubies[index][0]
        for e in list(r.iterdescendants()):
            if local(e) not in {'rt','rp','rtc'}:continue
            if any(n.get('id') for n in e.iter()):raise EpubError('読みの参照用IDを保護しています。')
            parent=e.getparent()
            if parent is not None:
                previous=e.getprevious();tail=e.tail or ''
                if previous is None:parent.text=(parent.text or '')+tail
                else:previous.tail=(previous.tail or '')+tail
                parent.remove(e)
        r.tag=ns+'span'
        for rb in r.xpath('.//x:rb',namespaces=NS):rb.tag=ns+'span'
    if layout(node)[0]!=content:raise EpubError('ルビの親文字保持検証に失敗しました。')


def replace(con,book_id,request,pid,target,replacement):
    from . import editing,projects
    current=con.execute('SELECT revision FROM unit_books WHERE book_id=?',(book_id,)).fetchone()[0]
    if current!=request.revision:raise editing.EditConflict('本文が変更されています。置換画面を開き直してください。')
    edits=con.execute('SELECT edits FROM unit_books WHERE book_id=?',(book_id,)).fetchone()[0]
    if not target or target==replacement:return
    records=con.execute("SELECT id FROM unit_nodes WHERE book_id=? AND kind='unit' AND active=1"+(" AND id=?" if pid else ''),(book_id,pid) if pid else (book_id,)).fetchall()
    for ident, in records:
        r=row(con,book_id,ident);fake,node=fake_book(r);*_,pieces,content=editing.text_layout(fake,ident)
        positions=[];offset=0
        while (start:=content.find(target,offset))>=0:
            end=start+len(target);offset=end
            if not any(p['protected'] and p['end']>start and p['start']<end for p in pieces):positions.append((start,end))
        after=content
        for a,b in reversed(positions):after=after[:a]+replacement+after[b:]
        if after==content:continue
        lock(con,book_id,ident,edit_owner.get())
        patches,_,_=editing.text_changes(fake,ident,after);apply_patches(fake,node,patches)
        write(con,book_id,r,node);confirm(con,book_id,ident)
        if local(node) in {'h1','h2','h3','h4','h5','h6'}:update_navigation(con,book_id)
    con.execute('UPDATE unit_books SET edits=? WHERE book_id=? AND revision>?',(edits+1,book_id,current))


def update_navigation(con,book_id):
    from .chapters import href,NCX
    base=con.execute('SELECT original FROM books WHERE id=?',(book_id,)).fetchone()[0]
    book=state(con,book_id,base)['working'].model()
    for c in book.chapters:
        for h in c['headings'][:1]:
            r=row(con,book_id,h['id']);node=xml(r[5])
            if not node.get('id'):node.set('id','heading-'+h['id']);write(con,book_id,r,node)
    book=state(con,book_id,base)['working'].model()
    entries=[]
    for c in book.chapters:
        head=c['headings'][0] if c['headings'] else None
        fragment=xml(book.node_info[head['id']][5]).get('id') if head else ''
        entries.append((c,c['heading_level'] if head else 1,fragment))
    for item in book.manifest:
        ncx=item['media_type']=='application/x-dtbncx+xml'
        if 'nav' not in item['properties'].split() and not ncx:continue
        path=item['path']
        if ncx:
            tree=xml(book.get(path));navmap=tree.find('{'+NCX+'}navMap')
            if navmap is None:raise EpubError('NCXの目次構造を解釈できません。')
            for child in list(navmap):navmap.remove(child)
            stack=[]
            for i,(c,level,fragment) in enumerate(entries,1):
                while stack and stack[-1][1]>=level:stack.pop()
                parent=stack[-1][0] if stack else navmap
                point=etree.SubElement(parent,'{'+NCX+'}navPoint',id='toc-'+str(i),playOrder=str(i))
                etree.SubElement(etree.SubElement(point,'{'+NCX+'}navLabel'),'{'+NCX+'}text').text=c['title']
                etree.SubElement(point,'{'+NCX+'}content',src=href(path,c['path'],fragment));stack.append((point,level))
            depth=max((1+sum(a.tag=='{'+NCX+'}navPoint' for a in p.iterancestors()) for p in navmap.iter('{'+NCX+'}navPoint')),default=0)
            for meta in tree.findall('.//{'+NCX+'}meta[@name="dtb:depth"]'):meta.set('content',str(depth))
            con.execute('INSERT INTO unit_resources VALUES (?,?,?) ON CONFLICT(book_id,path) DO UPDATE SET data=excluded.data',(book_id,path,dump(tree)))
            continue
        tree=xml(book.get(path));toc=tree.xpath('//x:nav[@*[local-name()="type"]="toc"]',namespaces=NS)
        if not toc:raise EpubError('目次を解釈できないため章の変更を中止しました。')
        ol=toc[0].find('x:ol',NS)
        if ol is None:raise EpubError('目次に一覧がありません。')
        for child in list(ol):ol.remove(child)
        stack=[]
        for c,level,fragment in entries:
            while stack and stack[-1][1]>=level:stack.pop()
            parent=ol
            if stack:
                parent=stack[-1][0].find('x:ol',NS)
                if parent is None:parent=etree.SubElement(stack[-1][0],'{'+NS['x']+'}ol')
            li=etree.SubElement(parent,'{'+NS['x']+'}li');etree.SubElement(li,'{'+NS['x']+'}a',href=href(path,c['path'],fragment)).text=c['title'];stack.append((li,level))
        # Navigation is protected from paragraph editing; replace its complete
        # skeleton, with no new EPUB resource and no modification of the OPF.
        rootid=book.file_info[path][0]
        con.execute('DELETE FROM unit_nodes WHERE book_id=? AND file=?',(book_id,path))
        con.execute('INSERT INTO unit_nodes VALUES (?,?,?,?,?,?,?,?,1,1,NULL)',(book_id,rootid,path,None,'8','opaque',dump(tree),None))
        con.execute('UPDATE unit_files SET version=version+1 WHERE book_id=? AND path=?',(book_id,path))


def prepare_database(folder):
    """New filename, with the legacy database left byte-for-byte untouched."""
    with preparation_lock:
        new=folder/DB_NAME;old=folder/'library.sqlite3'
        if new.exists() or not old.exists():return
        temp=folder/('.'+DB_NAME+'.migrating')
        source=sqlite3.connect('file:'+str(old)+'?mode=ro',uri=True);target=sqlite3.connect(temp)
        try:source.backup(target)
        finally:source.close();target.close()
        temp.replace(new)


def migrate_all(con):
    from . import editing,projects
    for book_id,original in con.execute('SELECT id,original FROM books WHERE id NOT IN (SELECT book_id FROM unit_books)').fetchall():
        value=editing.state(con,book_id);working=editing.working_model(value)
        data=editing.materialize(value['working']);checked=Book(data).apply_ids(value['ids'])
        # The edited EPUB becomes the new baseline. The untouched old SQLite
        # file is the recovery source, including old originals and edit history.
        con.execute('UPDATE books SET original=? WHERE id=?',(data,book_id))
        initialize(con,book_id,checked)
        meta=projects.read(con,book_id);meta['statuses']={};meta['reviews']={};meta['candidates']=[];meta['version']+=1;projects.write(con,book_id,meta)
        con.execute("UPDATE ai_jobs SET status='archived',error='新しい本文管理方式への移行により、再検査が必要です。' WHERE book_id=?",(book_id,))
        con.execute('INSERT OR IGNORE INTO ai_cleared_results SELECT id FROM ai_results WHERE book_id=?',(book_id,))
        con.execute('DELETE FROM editing_files WHERE book_id=?',(book_id,));con.execute('DELETE FROM editing_removed WHERE book_id=?',(book_id,));con.execute('DELETE FROM editing WHERE book_id=?',(book_id,))
