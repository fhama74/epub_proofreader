"""Versioned local projects, strict replay of imported edits and PDF attachments."""
from __future__ import annotations
import copy,hashlib,io,json,zipfile,math
from . import editing
from .epub import Book,EpubError
from .structure import operate,decoded

SCHEMA=1
MAX_PROJECT=512*1024*1024
STATUSES={'unchecked','ai_checked','human_checked','review'}

def fresh():return {'schema_version':SCHEMA,'version':0,'statuses':{},'mappings':{},'drafts':{},'view':{},'candidates':[],'pdf':None}
def read(con,book_id):
    row=con.execute('SELECT metadata FROM projects WHERE book_id=?',(book_id,)).fetchone()
    return json.loads(row[0]) if row else fresh()
def write(con,book_id,value):
    con.execute('INSERT INTO projects(book_id,metadata) VALUES (?,?) ON CONFLICT(book_id) DO UPDATE SET metadata=excluded.metadata',(book_id,json.dumps(value,ensure_ascii=False)))
def pdf_data(con,book_id):
    row=con.execute('SELECT pdf FROM projects WHERE book_id=?',(book_id,)).fetchone()
    return row[0] if row and row[0] else None

def validate_metadata(meta,book,pdf=None):
    if not isinstance(meta,dict) or meta.get('schema_version')!=SCHEMA:raise EpubError('未対応のプロジェクト形式です。')
    result=fresh()
    if type(meta.get('version')) is not int or meta['version']<0:raise EpubError('プロジェクトの版番号が不正です。')
    result['version']=meta['version']
    for key in ('statuses','mappings','drafts','view'):
        if not isinstance(meta.get(key,{}),dict):raise EpubError(f'{key}の形式が不正です。')
        result[key]=copy.deepcopy(meta.get(key,{}))
    if len(json.dumps(result,ensure_ascii=False))>4*1024*1024:raise EpubError('プロジェクト設定・未保存入力が大きすぎます。')
    for pid,status in result['statuses'].items():
        if not isinstance(pid,str) or len(pid)>128 or not isinstance(status,str) or status not in STATUSES:raise EpubError('確認状態が不正です。')
    for pid,items in result['mappings'].items():
        if not isinstance(pid,str) or len(pid)>128 or not isinstance(items,list) or len(items)>100:raise EpubError('PDF対応の形式が不正です。')
        for item in items:
            if not isinstance(item,dict) or not isinstance(item.get('page'),int) or not 1<=item['page']<=1000000:raise EpubError('PDFページが不正です。')
            if not isinstance(item.get('pdf_sha256'),str) or len(item['pdf_sha256'])!=64:raise EpubError('対応PDFの識別子が不正です。')
            rect=item.get('rectangle')
            if rect is not None and (not isinstance(rect,list) or len(rect)!=4 or any(type(n) not in (int,float) or not 0<=n<=1 for n in rect) or not(rect[0]<rect[2] and rect[1]<rect[3])):raise EpubError('PDFの範囲は0〜1の座標で指定してください。')
    for key,draft in result['drafts'].items():
        if len(key)>256 or not isinstance(draft,dict) or not isinstance(draft.get('text'),str) or len(draft['text'])>20000 or not isinstance(draft.get('revision'),int):raise EpubError('未保存入力の形式が不正です。')
        if not isinstance(draft.get('rubies',{}),dict) or not isinstance(draft.get('reason',''),str):raise EpubError('未保存入力のルビ・理由が不正です。')
    view=result['view']
    # Saved values are data, never HTML or paths. Browser validates live IDs again.
    if 'fontSize' in view and (type(view['fontSize']) not in (int,float) or not 14<=view['fontSize']<=32):raise EpubError('文字サイズが不正です。')
    for key in ('left','right'):
        if key in view and (type(view[key]) not in (int,float) or not 10<=view[key]<=60):raise EpubError('ペイン幅が不正です。')
    for key in ('chapterId','paragraphId'):
        if key in view and (not isinstance(view[key],str) or len(view[key])>128):raise EpubError('表示位置のIDが不正です。')
    if view.get('sentenceIndex') is not None and (type(view['sentenceIndex']) is not int or view['sentenceIndex']<0):raise EpubError('文の位置が不正です。')
    for key in ('hidePdf','hideInfo'):
        if key in view and type(view[key]) is not bool:raise EpubError('表示設定が不正です。')
    if view.get('epubScroll') is not None and (type(view['epubScroll']) not in (int,float) or not math.isfinite(view['epubScroll']) or abs(view['epubScroll'])>1e9):raise EpubError('本文の表示位置が不正です。')
    if 'pdf' in view:
        settings=view['pdf']
        if not isinstance(settings,dict) or set(settings)-{'page','zoom','mode','scrollLeft','scrollTop','followText'}:raise EpubError('PDF表示設定が不正です。')
        if 'followText' in settings and type(settings['followText']) is not bool:raise EpubError('PDF追従の設定が不正です。')
        if type(settings.get('page')) is not int or not 1<=settings['page']<=1000000 or settings.get('mode') not in {'width','page','custom'}:raise EpubError('PDFページ・表示モードが不正です。')
        if type(settings.get('zoom')) not in (int,float) or not .1<=settings['zoom']<=5:raise EpubError('PDF倍率が不正です。')
        for key in ('scrollLeft','scrollTop'):
            value=settings.get(key,0)
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1e9:raise EpubError('PDF表示位置が不正です。')
    for draft in result['drafts'].values():
        if not isinstance(draft.get('paragraphId'),str) or len(draft['paragraphId'])>128 or not isinstance(draft.get('before'),str) or len(draft['before'])>20000:raise EpubError('未保存入力の参照先が不正です。')
        span=draft.get('rubyRange')
        if span is not None:
            if not isinstance(span,dict) or any(type(span.get(k)) is not int for k in ('index','start','end')) or not 0<=span['index']<=10000 or not 0<=span['start']<span['end']<=len(draft['before']):raise EpubError('未保存入力のルビ範囲が不正です。')
            if any(not isinstance(span.get(k),str) or len(span[k])>2000 for k in ('baseBefore','readingBefore')):raise EpubError('未保存入力のルビ参照元が不正です。')
        for index,ruby in draft['rubies'].items():
            if not isinstance(index,str) or not index.isdigit() or not isinstance(ruby,dict) or not isinstance(ruby.get('base'),str) or not isinstance(ruby.get('reading'),str) or len(ruby['base'])>1000 or len(ruby['reading'])>2000:raise EpubError('未保存ルビの形式が不正です。')
    if 'catalog' in meta:
        catalog=meta['catalog']
        if not isinstance(catalog,dict) or type(catalog.get('published_version')) is not int or not 0<=catalog['published_version']<=1000000000:raise EpubError('発行版の引継ぎ情報が不正です。')
        result['catalog']=copy.deepcopy(catalog)
    result['candidates']=meta.get('candidates',[])
    if not isinstance(result['candidates'],list) or result['candidates']:raise EpubError('この版ではAI候補の読み込みは未対応です。')
    result['pdf']=meta.get('pdf')
    if pdf is not None:
        if len(pdf)>256*1024*1024 or b'%PDF-' not in pdf[:1024]:raise EpubError('PDF添付が不正です。')
        if not isinstance(result['pdf'],dict) or result['pdf'].get('sha256')!=hashlib.sha256(pdf).hexdigest() or result['pdf'].get('size')!=len(pdf) or not isinstance(result['pdf'].get('name'),str) or len(result['pdf']['name'])>256:raise EpubError('PDF添付のハッシュが一致しません。')
    elif result['pdf'] is not None:raise EpubError('添付PDFが見つかりません。')
    return result

def progress(book,meta):
    counts={key:0 for key in STATUSES}
    for chapter in book.chapters:
        for paragraph in chapter['paragraphs']:counts[meta['statuses'].get(paragraph['id'],'unchecked')]+=1
    total=sum(counts.values())
    return {**counts,'total':total,'percent':round(100*counts['human_checked']/total,1) if total else 0}

def invalidate(con,book_id,value):
    if not value['history']:return
    meta=read(con,book_id);event=value['history'][-1];changed=False
    for pid in event['paragraph_ids']:
        if meta['statuses'].get(pid,'unchecked')!='unchecked':meta['statuses'][pid]='review';changed=True
    if event['action']=='split' and len(event['paragraph_ids'])==2:
        old,new=event['paragraph_ids']
        if old in meta['mappings']:meta['mappings'][new]=copy.deepcopy(meta['mappings'][old]);changed=True
    if event['action']=='merge' and len(event['paragraph_ids'])==2:
        prior,current=event['paragraph_ids']
        if current in meta['mappings']:
            meta['mappings'][prior]=meta['mappings'].get(prior,[])+[m for m in meta['mappings'][current] if m not in meta['mappings'].get(prior,[])];changed=True
    if changed:meta['version']+=1;write(con,book_id,meta)

def checked_body_changes(book,value,command,pids,before,after):
    allowed=set()
    for pid in pids:
        chapter,_,_,pieces,text=editing.text_layout(book,pid)
        if text!=before[pid]:raise EpubError('履歴の変更前本文が一致しません。')
        allowed.update((chapter['path'],piece['xpath'],piece['field']) for piece in pieces if not piece['protected'])
    patches=[patch for patch in command.get('changes',[]) if (patch.get('file'),patch.get('xpath'),patch.get('field')) in allowed]
    checked=Book(editing.apply_changes(editing.working_model(value),patches)).apply_ids(value['ids'])
    for pid in pids:
        if editing.text_layout(checked,pid)[-1]!=after[pid]:raise EpubError('履歴の変更後本文が一致しません。')
    return patches

def replay(original,state):
    """Rebuild each command through allowed operations; never trust imported XPath/shape."""
    if not isinstance(state,dict):raise EpubError('編集履歴の形式が不正です。')
    commands=state.get('commands');cursor=state.get('cursor');history=state.get('history');revision=state.get('revision')
    if not isinstance(commands,list) or len(commands)>5000 or type(cursor) is not int or not 0<=cursor<=len(commands) or not isinstance(history,list) or type(revision) is not int or revision!=len(history):raise EpubError('履歴・Undo位置・版番号が不正です。')
    value={'working':original.normalized,'ids':{}};at_cursor=copy.deepcopy(value) if cursor==0 else None
    command_ids=set()
    for number,command in enumerate(commands):
        if not isinstance(command,dict) or not isinstance(command.get('id'),str) or command['id'] in command_ids:raise EpubError('履歴コマンドIDが不正です。')
        command_ids.add(command['id']);kind=command.get('action');pids=command.get('paragraph_ids')
        if not isinstance(pids,list) or not pids:raise EpubError('履歴の段落指定が不正です。')
        book=editing.working_model(value);changes=[]
        if kind in {'insert','split','merge'}:
            snap=command.get('snapshot',{});pid=pids[0]
            if kind=='merge':pid=pids[1]
            options={}
            if kind=='insert':
                if len(pids)!=2:raise EpubError('挿入履歴が不正です。')
                after_ids=snap.get('ids_after',[])
                options={'text':command['after'],'position':'before' if after_ids.index(pids[1])<after_ids.index(pids[0]) else 'after'}
            elif kind=='split':options={'offset':len(command['after'][0])}
            rebuilt,expected,affected,before,after,focus=operate(book,pid,kind,**options)
            if kind in {'insert','split'}:expected['ids_after']=[pids[1] if ident==focus else ident for ident in expected['ids_after']]
            if expected!=snap or before!=command['before'] or after!=command['after']:raise EpubError('段落構造の履歴が一致しません。')
            value['working']=rebuilt;value['ids'][snap['chapter_id']]=snap['ids_after']
        else:
            before=command.get('before');after=command.get('after')
            if kind in {'text','sentence'}:
                changes=checked_body_changes(book,value,command,pids,{pids[0]:before},{pids[0]:after})
            elif kind=='replace':
                if not isinstance(after,dict) or set(after)!=set(pids):raise EpubError('置換履歴が不正です。')
                changes=checked_body_changes(book,value,command,pids,before,after)
            elif kind in {'ruby','combined'}:
                details=editing.paragraph_details(book,pids[0],0)
                if kind=='combined':
                    changes=checked_body_changes(book,value,command,pids,{pids[0]:before['text']},{pids[0]:after['text']})
                    updates=after['rubies'];old=before['rubies']
                else:
                    matches=[]
                    for index,ruby in enumerate(details['rubies']):
                        if not ruby['editable']:continue
                        patch,_,_=editing.ruby_changes(book,pids[0],index,after['base'],after['reading'],after.get('range_start'),after.get('range_end'))
                        if patch==command.get('changes'):matches.append(index)
                    if len(matches)!=1:raise EpubError('ルビ履歴の位置を照合できません。')
                    updates=[{'index':matches[0],**after}];old=[{'index':matches[0],**before}]
                for update,previous in zip(updates,old,strict=True):
                    patch,b,a=editing.ruby_changes(book,pids[0],update['index'],update['base'],update['reading'],update.get('range_start'),update.get('range_end'))
                    if previous!={'index':update['index'],**b}:raise EpubError('ルビ履歴の変更前が一致しません。')
                    changes+=patch
            else:raise EpubError('未対応の編集履歴です。')
            # Original recorded patches may resolve repeated strings differently.
            # Accept only an identical resulting tree to a safe reconstructed edit.
            safe=Book(editing.apply_changes(book,changes))
            recorded=Book(editing.apply_changes(editing.working_model(value),command.get('changes',[])))
            if safe.files!=recorded.files:raise EpubError('許可された編集と履歴の変更内容が一致しません。')
            value['working']=recorded.original
        editing.working_model(value)
        if number+1==cursor:at_cursor=copy.deepcopy(value)
    for event in history:
        if not isinstance(event,dict) or event.get('action') not in {'text','sentence','ruby','combined','replace','insert','split','merge','undo','redo'} or not isinstance(event.get('id'),str):raise EpubError('操作履歴の形式が不正です。')
    result={**copy.deepcopy(state),**at_cursor}
    actual=editing.working_model(result)
    supplied=Book(result['working']).apply_ids(state.get('ids',{}))
    if [[p['id'] for p in c['paragraphs']] for c in actual.chapters]!=[[p['id'] for p in c['paragraphs']] for c in supplied.chapters]:raise EpubError('段落IDの履歴が一致しません。')
    result['ids']=copy.deepcopy(state.get('ids',{}))
    editing.validate_export(original,editing.working_model(result),commands[:cursor])
    return result

def content_hash(book):
    return hashlib.sha256(json.dumps({path:hashlib.sha256(data).hexdigest() for path,data in sorted(book.files.items())},sort_keys=True).encode()).hexdigest()

def history_export(original,value):
    return {'schema_version':2,'original_sha256':original.fingerprint,'working_sha256':hashlib.sha256(editing.materialize(value['working'])).hexdigest(),'working_content_sha256':content_hash(editing.working_model(value)),'revision':value['revision'],'events':value['history'],'state':{k:value[k] for k in ('commands','cursor','history','revision','ids')}}

def encode_project(original,value,meta,pdf,name,ai=None):
    files={'original.epub':original.original,'working.epub':editing.materialize(value['working']),'editing.json':json.dumps({k:value[k] for k in ('commands','cursor','history','revision','ids')},ensure_ascii=False).encode(),'project.json':json.dumps(meta,ensure_ascii=False).encode()}
    if pdf is not None:files['source.pdf']=pdf
    if ai is not None:files['ai.json']=json.dumps(ai,ensure_ascii=False).encode()
    manifest={'format':'epub-proofreader','schema_version':SCHEMA,'name':name,'files':{path:hashlib.sha256(data).hexdigest() for path,data in files.items()}}
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        for path,data in files.items():archive.writestr(path,data)
    return output.getvalue()

def decode_project(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries=archive.infolist();names=[e.filename for e in entries]
            allowed={'manifest.json','original.epub','working.epub','editing.json','project.json','source.pdf','ai.json'}
            if len(names)!=len(set(names)) or not set(names)<=allowed or not allowed-{'source.pdf','ai.json'}<=set(names):raise EpubError('プロジェクト内のファイル一覧が不正です。')
            if any(e.flag_bits&1 or e.file_size>256*1024*1024 for e in entries) or sum(e.file_size for e in entries)>MAX_PROJECT:raise EpubError('プロジェクトの展開サイズが大きすぎます。')
            if archive.getinfo('editing.json').file_size>64*1024*1024 or archive.getinfo('project.json').file_size>4*1024*1024 or archive.getinfo('manifest.json').file_size>65536:raise EpubError('プロジェクト設定が大きすぎます。')
            files={name:archive.read(name) for name in names};manifest=json.loads(files.pop('manifest.json'))
        if manifest.get('format')!='epub-proofreader' or manifest.get('schema_version')!=SCHEMA:raise EpubError('未対応の.eproof形式です。')
        if manifest.get('files')!={path:hashlib.sha256(value).hexdigest() for path,value in files.items()}:raise EpubError('プロジェクトのファイルハッシュが一致しません。')
        original=Book(files['original.epub'],repair_import=True);value=replay(original,json.loads(files['editing.json']))
        if Book(value['working']).files!=Book(files['working.epub']).files:raise EpubError('作業用EPUBと履歴の再現結果が一致しません。')
        value['working']=files['working.epub']
        meta=validate_metadata(json.loads(files['project.json']),editing.working_model(value),files.get('source.pdf'))
        if 'ai.json' in files:
            if len(files['ai.json'])>64*1024*1024:raise EpubError('AI校正バックアップが大きすぎます。')
            value['_ai_backup']=json.loads(files['ai.json'])
        name=manifest.get('name','book.epub')
        if not isinstance(name,str) or len(name)>256:raise EpubError('書籍名が不正です。')
        return original,value,meta,files.get('source.pdf'),name
    except EpubError:raise
    except (ValueError,KeyError,TypeError,IndexError,zipfile.BadZipFile,RuntimeError,UnicodeError,OverflowError) as exc:raise EpubError('プロジェクト・履歴の形式または整合性が不正です。') from exc
