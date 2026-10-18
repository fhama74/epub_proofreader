"""Permanent project catalog and immutable, idempotent EPUB publications."""
import hashlib,json,re
from datetime import datetime,timezone
from lxml import etree
from .epub import Book,EpubError,NS,xml
from .editing import repack,timestamp

VOCAB='urn:epub-proofreader:metadata:'

def embedded_version(book):
    root=xml(book.get(book.opf_path));mapping=dict(re.findall(r'([\w.-]+):\s+(\S+)',root.get('prefix','')))
    values=[n.text or '' for n in root.xpath('opf:metadata/opf:meta[@property]',namespaces=NS) if ':' in n.get('property') and mapping.get(n.get('property').split(':',1)[0])==VOCAB and n.get('property').split(':',1)[1]=='version']
    if not values:return 0
    if len(values)!=1 or not values[0].isdigit() or not 0<=int(values[0])<=1000000000:raise EpubError('EPUBの校正版番号が不正です。')
    return int(values[0])

def create(con,book_id,name,original,base=None):
    from . import unit_store
    base=embedded_version(original) if base is None else base
    from datetime import timedelta
    added=timestamp()
    while con.execute('SELECT 1 FROM books WHERE name=? AND uploaded_at=?',(name,added)).fetchone():added=(datetime.fromisoformat(added)+timedelta(microseconds=1)).isoformat()
    con.execute('INSERT INTO books(id,name,original,uploaded_at,version_base) VALUES (?,?,?,?,?)',(book_id,name,original.original,added,base))
    if unit_store.USE_NEW_STORAGE:unit_store.initialize(con,book_id,original)

def info(con,book_id):
    row=con.execute('SELECT name,uploaded_at,version_base FROM books WHERE id=?',(book_id,)).fetchone()
    if row is None:raise EpubError('プロジェクトがありません。')
    current=con.execute('SELECT MAX(version) FROM publications WHERE book_id=?',(book_id,)).fetchone()[0]
    return {'filename':row[0],'uploaded_at':row[1],'version_base':row[2],'published_version':current or row[2]}

def stamp(data,version,project_id,publish_id,published_at):
    book=Book(data);root=xml(book.get(book.opf_path));before=xml(book.get(book.opf_path))
    metadata=root.find('opf:metadata',NS)
    if metadata is None:raise EpubError('OPFのmetadataがありません。')
    if not root.get('version','').startswith('3'):raise EpubError('版番号付き発行はEPUB 3を対象としています。')
    mapping=dict(re.findall(r'([\w.-]+):\s+(\S+)',root.get('prefix','')))
    prefix=next((key for key,value in mapping.items() if value==VOCAB),None)
    if prefix is None:
        prefix='eproof';number=1
        while prefix in mapping:prefix=f'eproof{number}';number+=1
        root.set('prefix',((root.get('prefix','')+' ').lstrip()+prefix+': '+VOCAB))
    for node in list(metadata):
        prop=node.get('property','');parts=prop.split(':',1)
        if len(parts)==2 and mapping.get(parts[0])==VOCAB and parts[1] in {'version','project-id','publish-id'}:metadata.remove(node)
    for key,value in [('version',str(version)),('project-id',project_id),('publish-id',publish_id)]:
        node=etree.SubElement(metadata,'{'+NS['opf']+'}meta',property=f'{prefix}:{key}');node.text=value
    modified=metadata.xpath('opf:meta[@property="dcterms:modified" and not(@refines)]',namespaces=NS)
    if not modified:modified=[etree.SubElement(metadata,'{'+NS['opf']+'}meta',property='dcterms:modified')]
    for node in modified:node.text=published_at
    result=repack(data,{book.opf_path:etree.tostring(root.getroottree(),encoding='UTF-8',xml_declaration=True)})
    checked=Book(result)
    if set(book.files)!=set(checked.files) or any(checked.files[path]!=content for path,content in book.files.items() if path!=book.opf_path):raise EpubError('発行メタデータ以外のファイルが変化しています。')
    for key in ('manifest','spine','toc','direction'):
        if getattr(book,key)!=getattr(checked,key):raise EpubError('発行時に書籍構成が変化しています。')
    # Independently compare the unmodified OPF fields, including identifiers.
    def strip_generated(tree):
        prefixes=dict(re.findall(r'([\w.-]+):\s+(\S+)',tree.get('prefix','')))
        md=tree.find('opf:metadata',NS)
        for n in list(md):
            prop=n.get('property','');parts=prop.split(':',1)
            if prop=='dcterms:modified' and not n.get('refines') or len(parts)==2 and prefixes.get(parts[0])==VOCAB and parts[1] in {'version','project-id','publish-id'}:md.remove(n)
        tree.attrib.pop('prefix',None)
        return etree.tostring(tree,method='c14n')
    if strip_generated(before)!=strip_generated(xml(checked.get(checked.opf_path))):raise EpubError('発行時に元のOPF情報が変化しています。')
    return result

def release_info(row):
    return {'version':row[0],'published_at':row[1],'revision':row[2],'sha256':row[3],'size':row[4],'validation':json.loads(row[5]),'request_id':row[6]}

def releases(con,book_id):
    return [release_info(row) for row in con.execute('SELECT version,published_at,revision,sha256,length(epub),validation,request_id FROM publications WHERE book_id=? ORDER BY version DESC',(book_id,))]
