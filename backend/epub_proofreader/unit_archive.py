"""Portable unit snapshots, without replay history or executable input."""
import base64
import json
from lxml import etree
from . import unit_store as store
from .epub import EpubError,Book,xml


def encode(value):
    source=value['working']
    nodes=[]
    for row in source.nodes:
        r=list(row);r[5]=base64.b64encode(r[5]).decode();nodes.append(r)
    return dict(storage_mode='units',revision=value['revision'],edits=value['unit_edits'],nodes=nodes,files=source.files,joins=source.joins,resources=[(p,base64.b64encode(v).decode()) for p,v in source.resources])


def decode(base,data):
    try:
        revision=data['revision'];edits=data['edits']
        if any(type(v) is not int or not 0<=v<2**63 for v in (revision,edits)):raise ValueError()
        nodes=[];seen=set();active=set()
        if not isinstance(data['nodes'],list) or len(data['nodes'])>500000:raise ValueError()
        original=Book(base);paths=set(original.trees)
        for r in data['nodes']:
            if not isinstance(r,list) or len(r)!=10:raise ValueError()
            ident,file,parent,order,kind,raw,tail,version,enabled,record=r
            if not isinstance(ident,str) or not ident or len(ident)>128 or ident in seen:raise ValueError()
            seen.add(ident)
            if file not in paths or parent is not None and (not isinstance(parent,str) or len(parent)>128):raise ValueError()
            if not isinstance(order,str) or not order or order.endswith('0') or len(order)>20000 or any(c not in store.DIGITS for c in order):raise ValueError()
            if kind not in {'unit','container','opaque'} or type(version) is not int or not 1<=version<2**63 or type(enabled) is not int or enabled not in {0,1}:raise ValueError()
            if tail is not None and not isinstance(tail,str):raise ValueError()
            raw=base64.b64decode(raw,validate=True)
            node=xml(b'<wrapper>'+raw+b'</wrapper>')[0] if kind=='opaque' else xml(raw)
            if kind=='container' and len(node):raise ValueError()
            if kind=='unit':
                original_record=json.loads(record)
                if any(not isinstance(original_record.get(k),str) for k in ('original_xml','original_text')):raise ValueError()
                _,_,fresh=store.fragment(raw,ident,version,original_record)
                record=json.dumps(fresh,ensure_ascii=False)
            elif record is not None:raise ValueError()
            if enabled:
                key=(file,parent,order)
                if key in active:raise ValueError()
                active.add(key)
            nodes.append((ident,file,parent,order,kind,raw,tail,version,enabled,record))
        files=tuple(tuple(r) for r in data['files'])
        if {r[0] for r in files}!=paths or len(files)!=len(paths):raise ValueError()
        info={r[0]:r for r in nodes};children={}
        for r in nodes:
            if r[2] is not None and (r[2] not in info or info[r[2]][1]!=r[1] or info[r[2]][4]!='container'):raise ValueError()
            if r[8]:children.setdefault(r[2],[]).append(r[0])
        visited=set()
        def visit(ident,path,depth=0):
            if depth>200 or ident in visited or ident not in info or info[ident][1]!=path or not info[ident][8]:raise ValueError()
            visited.add(ident)
            for child in children.get(ident,[]):visit(child,path,depth+1)
        for path,root,encoding,doctype,version in files:
            if info[root][2] is not None or type(version) is not int or version<1 or not isinstance(encoding,str) or not isinstance(doctype,str):raise ValueError()
            visit(root,path)
        if visited!={r[0] for r in nodes if r[8]}:raise ValueError()
        resources=tuple((p,base64.b64decode(v,validate=True)) for p,v in data.get('resources',[]))
        if len(dict(resources))!=len(resources) or any(p not in original.files for p,v in resources):raise ValueError()
        joins=data.get('joins',[])
        if not isinstance(joins,list) or len(joins)!=len(set(joins)) or any(p not in paths for p in joins):raise ValueError()
        source=store.Source(base,'archive',revision,tuple(nodes),files,resources,tuple(joins))
        # Force structural reconstruction independently of file version fast paths.
        for path in paths:
            rebuilt,_=source.model().build_tree(path)
            if store.canonical(rebuilt)!=store.canonical(xml(source.model().get(path))):raise ValueError()
        return dict(working=source,revision=revision,unit_edits=edits,commands=[],cursor=0,history=[],ids={})
    except (ValueError,TypeError,KeyError,IndexError,RecursionError,OverflowError):
        raise EpubError('本文DBのバックアップ形式・識別ID・構造が不正です。') from None


def restore(con,book_id,value):
    source=value['working']
    for table in ('unit_nodes','unit_files','unit_resources','unit_reviews','unit_locks','unit_file_joins'):
        con.execute('DELETE FROM '+table+' WHERE book_id=?',(book_id,))
    con.executemany('INSERT INTO unit_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)',[(book_id,*r) for r in source.nodes])
    con.executemany('INSERT INTO unit_files VALUES (?,?,?,?,?,?)',[(book_id,*r) for r in source.files])
    con.executemany('INSERT INTO unit_resources VALUES (?,?,?)',[(book_id,*r) for r in source.resources])
    con.executemany('INSERT INTO unit_file_joins VALUES (?,?)',[(book_id,path) for path in source.joins])
    con.execute('UPDATE unit_books SET revision=?,edits=? WHERE book_id=?',(value['revision'],value['unit_edits'],book_id))
    store.update_locations(con,book_id)
    # The source of truth for confirmations is the per-unit version-bound row.
    from . import projects
    meta=projects.read(con,book_id)
    for ident,targets in meta.get('reviews',{}).items():
        try:d=store.direct_details(con,book_id,ident)
        except ValueError:continue
        if targets.get('version')!=d['unit_version']:continue
        for target in ('body','ruby'):
            marks=targets.get(target,{})
            if 'all' in marks:con.execute('INSERT OR IGNORE INTO unit_reviews VALUES (?,?,?,?,?,?)',(book_id,ident,d['unit_version'],target,0,len(d['editor_text'])))
            for index in (int(k) for k in marks if k.isdigit()):
                units=d['sentences'] if target=='body' else d['rubies']
                if index<len(units):
                    u=units[index];con.execute('INSERT OR IGNORE INTO unit_reviews VALUES (?,?,?,?,?,?)',(book_id,ident,d['unit_version'],target,u['start'],u['end']))
