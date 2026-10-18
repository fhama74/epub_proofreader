import {applyReviewReceipt,reviewedCandidates,type ReviewReceipt} from './reviewReceipt';
import RubyAddDialog,{type RubySelection} from './RubyAddDialog';
import type {ReaderBookmark} from './readerBookmark';
import {projectRightToLeft} from './projectDirection';
import {nextProofLocation,resolveProofUnit} from './proofSelection';
import {useCallback,useEffect,useRef,useState} from 'react';
import WorkspaceMenu from './WorkspaceMenu';
import PdfPane from './PdfPane';
import AIPanel,{type AINavigation} from './AIPanel';
import InlineEditor,{type BlockAction,type ProofCompletion} from './InlineEditor';
import useReaderLayout from './useReaderLayout';
import NewProjectDialog from './NewProjectDialog';
import {type Candidate,type AIState} from './aiTypes';
import EpubPane from './EpubPane';
import {type EditorTarget} from './EditorDialog';
import RubyReviewDialog from './RubyReviewDialog';
import {api} from './dialogUtils';
import {readJSON,requestJSON} from './apiClient';
import ProofingDialog,{type DialogKind} from './ProofingDialogs';
import StructureDialog from './StructureDialog';
import ChapterDialog from './ChapterDialog';
import ProjectPanel,{statusLabels} from './ProjectPanel';
import LibraryDialog,{uploadDate} from './LibraryDialog';
import useProject,{defaultView} from './useProject';
import type {Book,Mapping,Project,WorkspaceView} from './types';
export default function App(){
  const {readerMode,chooseReader,readerHeight}=useReaderLayout();
  const [chapterLanding,setChapterLanding]=useState<'start'|'end'|null>(null);
  const readerReturnPosition=useRef<number|null>(null);const readerPosition=useRef<ReaderBookmark|null>(null);const [readerRestore,setReaderRestore]=useState<ReaderBookmark|null>(null);
  const [readerTab,setReaderTab]=useState<'epub'|'pdf'>('epub');const [readerEditOrigin,setReaderEditOrigin]=useState<'text'|'toolbar'|null>(null);const readerEditing=readerEditOrigin!==null;

  const [book,setBook]=useState<Book|null>(null);const activeBook=useRef<Book|null>(null);
  const [view,setView]=useState<WorkspaceView>(defaultView);const currentView=useRef(view);currentView.current=view;
  const [pdf,setPdf]=useState<File|null>(null);const pendingPdf=useRef<File|null>(null);const [html,setHtml]=useState<string|null>(null);
  const [rubyAdd,setRubyAdd]=useState<RubySelection|null>(null);
  const [editTarget,setEditTarget]=useState<EditorTarget|null>(null);const [dialog,setDialog]=useState<DialogKind|null>(null);const [blockAction,setBlockAction]=useState<BlockAction|null>(null);const [reviewEvent,setReviewEvent]=useState<ReviewReceipt|null>(null);
  const [libraryOpen,setLibraryOpen]=useState(false);
  const [newProject,setNewProject]=useState(false);
  const [selectionToken,setSelectionToken]=useState(0);
  const [aiResults,setAIResults]=useState<Candidate[]>([]);
  const [currentCandidate,setCurrentCandidate]=useState<Candidate|null>(null);
  const [aiNavigation,setAINavigation]=useState<AINavigation>({previousId:null,nextId:null,count:0,index:-1});
  const [aiRequest,setAIRequest]=useState<{id:string;nonce:number;candidate?:Candidate}|null>(null);
  const [aiModal,setAiModal]=useState(false);
  const [aiHighlight,setAiHighlight]=useState<Candidate|null>(null);
  const [saving,setSaving]=useState(false);const [loading,setLoading]=useState(false);const [error,setError]=useState('');const [query,setQuery]=useState('');const [selecting,setSelecting]=useState(false);
  const input=useRef<HTMLInputElement>(null);const historyInput=useRef<HTMLInputElement>(null);const panes=useRef<HTMLDivElement>(null);const readyId=useRef<string|null>(null);
  const reportError=useCallback((message:unknown)=>setError(String(message)),[]);
  const store=useProject(reportError);const {project,persist,initialize,flush,run,accept}=store;
  const {fontSize,left,right,hidePdf,hideInfo}=view;
  const rightToLeft=projectRightToLeft(book);
  const chapterIndex=Math.max(0,book?.chapters.findIndex(c=>c.id===view.chapterId) ?? 0);const chapter=book?.chapters[chapterIndex];const units=chapter?.proof_units || [];
  const heading=chapter?.headings?.find(h=>h.id===view.paragraphId);
  const resolved=resolveProofUnit(units,view.paragraphId,view.sentenceIndex);const index=Math.max(0,resolved?units.indexOf(resolved):0);const unit=heading?{paragraph_id:heading.id,paragraph_index:heading.next_paragraph_index,kind:'paragraph' as const,sentence_index:null,text:heading.text}:resolved;const paragraph=heading || (unit?chapter?.paragraphs[unit.paragraph_index]:undefined);
  const inlineCandidate=currentCandidate && paragraph && currentCandidate.paragraph_id===paragraph.id && currentCandidate.target==='text'?currentCandidate:aiResults.find(c=>c.book_id===book?.id && c.paragraph_id===paragraph?.id && c.target==='text' && !c.stale && ['pending','held'].includes(c.status) && (unit?.kind!=='sentence' || c.start>=(paragraph?.sentences[unit.sentence_index!]?.start??0) && c.end<=(paragraph?.sentences[unit.sentence_index!]?.end??0))) || null;
  const pdfSentence=aiHighlight?.paragraph_id===paragraph?.id?paragraph?.sentences.find(s=>s.start<=aiHighlight!.start && aiHighlight!.start<s.end):undefined;
  const pdfUnit=pdfSentence && unit?{...unit,kind:'sentence' as const,sentence_index:pdfSentence.index,text:pdfSentence.text}:unit;
  const modal=!!blockAction || !!rubyAdd || !!editTarget || !!dialog || libraryOpen || aiModal || newProject;
  const openBook=useCallback(async(value:Book)=>{
    setReaderRestore(null);readerPosition.current=null;setChapterLanding(null);readyId.current=null;setAIResults([]);setReaderTab('epub');setReaderEditOrigin(null);setCurrentCandidate(null);setAiHighlight(null);setAIRequest(null);setAINavigation({previousId:null,nextId:null,count:0,index:-1});setHtml(null);setSelecting(false);setQuery('');
    let meta=await api<Project>(`/api/books/${value.id}/project`);
    if(!meta.pdf && pendingPdf.current){const form=new FormData();form.append('file',pendingPdf.current);meta=await requestJSON<Project>(`/api/books/${value.id}/pdf`,{method:'POST',body:form});pendingPdf.current=null;}
    let attached:File|null=null;if(meta.pdf){const response=await fetch(`/api/books/${value.id}/pdf`);if(!response.ok)throw new Error('保存済みPDFを取得できません。');attached=new File([await response.blob()],meta.pdf.name,{type:'application/pdf'});}
    const restored={...defaultView,...meta.view,pdf:{...defaultView.pdf,...meta.view.pdf}};
    try{
      const local=JSON.parse(localStorage.getItem(`eproof-view:${value.id}`) || 'null');
      // A shared project update must not replace this browser's own position.
      if(local?.fingerprint===value.fingerprint && local.view){
        Object.assign(restored,local.view,{pdf:{...restored.pdf,...local.view.pdf}});
        if(local.revision!==undefined && local.revision!==value.edit_state.revision)restored.epubScroll=null;
      }
    }catch{/* Corrupt or unavailable browser storage falls back to the project view. */}
    const c=value.chapters.find(c=>c.id===restored.chapterId) || value.chapters[0];const u=c?resolveProofUnit(c.proof_units,restored.paragraphId,restored.sentenceIndex):undefined;
    restored.chapterId=c?.id;restored.paragraphId=c?.headings?.some(h=>h.id===restored.paragraphId)?restored.paragraphId:u?.paragraph_id;restored.sentenceIndex=u?.sentence_index;
    setPdf(attached);setView(restored);setBook(value);activeBook.current=value;initialize(value.id,meta);readyId.current=value.id;localStorage.setItem('lastBook',value.id);
  },[initialize]);
  useEffect(()=>{const last=localStorage.getItem('lastBook');if(last)void api<Book>(`/api/books/${last}`).then(openBook).catch(reportError);},[openBook,reportError]);
  useEffect(()=>{
    if(!book || readyId.current!==book.id || loading)return;

    try{localStorage.setItem(`eproof-view:${book.id}`,JSON.stringify({view,fingerprint:book.fingerprint,revision:book.edit_state.revision}));}catch{reportError('ブラウザへの表示位置保存に失敗しました。プロジェクト保存を利用してください。');}
  },[view,book?.id,book?.edit_state.revision,loading,reportError]);
  const setPdfSettings=useCallback((patch:Partial<WorkspaceView['pdf']>)=>setView(v=>{if(Object.entries(patch).every(([key,value])=>v.pdf[key as keyof typeof v.pdf]===value))return v;return {...v,pdf:{...v.pdf,...patch}};}),[]);
  const saveEpubScroll=useCallback((position:number)=>setView(v=>v.epubScroll===position?v:{...v,epubScroll:position}),[]);
  useEffect(()=>{if(!book || !chapter)return;const controller=new AbortController();setHtml(null);void requestJSON<{html:string}>(`/api/books/${book.id}/chapters/${chapter.id}`,{signal:controller.signal}).then(value=>setHtml(value.html)).catch(e=>{if(e.name!=='AbortError')reportError(String(e));});return()=>controller.abort();},[book?.id,chapter?.id,book?.edit_state.revision,reportError]);
  const updateBook=useCallback((value:Book)=>{
    setBook(value);activeBook.current=value;if(value.project)accept(value.project);
    if(value.focus_paragraph_id){const c=value.chapters.find(c=>c.paragraphs.some(p=>p.id===value.focus_paragraph_id));const u=c?.proof_units.find(u=>u.paragraph_id===value.focus_paragraph_id);if(c && u)setView(v=>({...v,chapterId:c.id,paragraphId:u.paragraph_id,sentenceIndex:u.sentence_index,epubScroll:null}));}
    else setView(v=>{const c=value.chapters.find(c=>c.id===v.chapterId) || value.chapters[0];if(c?.headings?.some(h=>h.id===v.paragraphId))return {...v,epubScroll:null};const u=c?resolveProofUnit(c.proof_units,v.paragraphId,v.sentenceIndex):undefined;return {...v,chapterId:c?.id,paragraphId:u?.paragraph_id,sentenceIndex:u?.sentence_index,epubScroll:null};});
  },[accept]);
  const acceptReview=useCallback(async(receipt:ReviewReceipt)=>{
    const current=activeBook.current;if(!current || current.id!==receipt.book_id)return;
    if(current.edit_state.revision!==receipt.revision){updateBook(await api<Book>(`/api/books/${current.id}`));}
    else{const next=applyReviewReceipt(current,receipt);activeBook.current=next;setBook(next);accept(receipt.project);}
    setAIResults(results=>reviewedCandidates(results,receipt.reviewed_ids));setReviewEvent(receipt);
  },[accept,updateBook]);
  const chooseUnit=useCallback((i:number)=>{setReaderRestore(null);setChapterLanding(null);const u=units[i];setSelectionToken(t=>t+1);setAIRequest(null);setCurrentCandidate(null);setAiHighlight(null);if(u)setView(v=>({...v,paragraphId:u.paragraph_id,sentenceIndex:u.sentence_index,epubScroll:null}));},[units]);
  const navigate=useCallback((step:number)=>{
    if(!book || !chapter)return;const next=heading?(step>0?units.findIndex(u=>u.paragraph_index>=heading.next_paragraph_index):units.reduce((last,u,i)=>u.paragraph_index<heading.next_paragraph_index?i:last,-1)):index+step;
    if(next>=0 && next<units.length)chooseUnit(next);
    else {const c=book.chapters[chapterIndex+step];const u=step>0?c?.proof_units[0]:c?.proof_units.at(-1);if(c && u){setSelecting(false);setCurrentCandidate(null);setAiHighlight(null);setView(v=>({...v,chapterId:c.id,paragraphId:u.paragraph_id,sentenceIndex:u.sentence_index,epubScroll:null}));}}
  },[book,chapter,index,units,chooseUnit,chapterIndex,heading]);
  const onKey=useCallback((event:KeyboardEvent)=>{if(modal)return;if(event.altKey && ['ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();(event.target as HTMLElement)?.blur?.();navigate(event.key==='ArrowDown'?1:-1);}},[modal,navigate]);
  useEffect(()=>{window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey);},[onKey]);
  const select=useCallback((paragraphId:string,sentenceIndex?:number)=>{setView(v=>({...v,hideInfo:false}));if(chapter?.headings?.some(h=>h.id===paragraphId)){setSelectionToken(t=>t+1);setAIRequest(null);setCurrentCandidate(null);setAiHighlight(null);setView(v=>({...v,paragraphId,sentenceIndex:null,epubScroll:null}));return;}const i=units.findIndex(u=>u.paragraph_id===paragraphId && (u.kind==='paragraph' || sentenceIndex===undefined || u.sentence_index===sentenceIndex));if(i>=0)chooseUnit(i);},[units,chooseUnit,chapter]);
  const ruby=useCallback((paragraphId:string,rubyIndex:number,sentenceIndex?:number)=>{select(paragraphId,sentenceIndex);if(readerMode)setReaderEditOrigin('text');},[readerMode,select]);
  function turnChapter(step:number){setReaderRestore(null);const c=book?.chapters[chapterIndex+step];if(!c)return;const u=step>0?c.proof_units[0]:c.proof_units.at(-1);setChapterLanding(step>0?'start':'end');setSelecting(false);setCurrentCandidate(null);setAiHighlight(null);setAIRequest(null);setView(v=>({...v,chapterId:c.id,paragraphId:u?.paragraph_id,sentenceIndex:u?.sentence_index,epubScroll:null}));}
  function selectChapter(value:number){setReaderRestore(null);setChapterLanding('start');const c=book?.chapters[value],u=c?.proof_units[0];setSelecting(false);setView(v=>({...v,chapterId:c?.id,paragraphId:u?.paragraph_id,sentenceIndex:u?.sentence_index,epubScroll:null}));setQuery('');}
  function edit(){if(unit)setEditTarget({paragraphId:unit.paragraph_id,sentenceIndex:unit.kind==='sentence'?unit.sentence_index!:undefined});}
  async function attachPdf(file:File){const b=activeBook.current;if(!b){pendingPdf.current=file;setPdf(file);return;}await flush();const form=new FormData();form.append('file',file);const response=await fetch(`/api/books/${b.id}/pdf`,{method:'POST',body:form});const meta=await readJSON<Project>(response);accept(meta);setPdf(file);setView(v=>({...v,pdf:{...defaultView.pdf,...meta.view.pdf}}));}
  async function readFiles(files:File[]){setLoading(true);setError('');try{
    await flush();
    for(const file of [...files].sort((a,b)=>Number(a.name.toLowerCase().endsWith('.pdf'))-Number(b.name.toLowerCase().endsWith('.pdf')))){
      const name=file.name.toLowerCase();
      if(name.endsWith('.pdf')){if(file.size>256*1024*1024 || !(await file.slice(0,1024).text()).includes('%PDF-'))throw new Error('PDF形式またはサイズが不正です（256 MiBまで）。');await attachPdf(file);}
      else if(name.endsWith('.epub') || name.endsWith('.eproof')){const limit=name.endsWith('.epub')?64:512;if(file.size>limit*1024*1024)throw new Error(`${limit} MiB以下のファイルを選択してください。`);const form=new FormData();form.append('file',file);const response=await fetch(name.endsWith('.epub')?'/api/books':'/api/projects/import',{method:'POST',body:form});const value=await readJSON<Book>(response);await openBook(value);}
      else throw new Error('PDF・EPUB・.eproofを選択してください。');
    }
  }catch(e){reportError(String(e));}finally{setLoading(false);if(input.current)input.current.value='';}}
  function resize(event:React.PointerEvent,side:'left'|'right'){
    const target=event.currentTarget as HTMLElement;target.setPointerCapture(event.pointerId);
    const move=(e:PointerEvent)=>{const bounds=panes.current!.getBoundingClientRect();const value=side==='left'?Math.max(20,Math.min(52,100*(e.clientX-bounds.left)/bounds.width)):Math.max(18,Math.min(36,100*(bounds.right-e.clientX)/bounds.width));setView(v=>({...v,[side]:value}));};
    const end=()=>{target.removeEventListener('pointermove',move);target.removeEventListener('pointerup',end);target.removeEventListener('pointercancel',end);};target.addEventListener('pointermove',move);target.addEventListener('pointerup',end);target.addEventListener('pointercancel',end);
  }
  async function undoRedo(kind:'undo'|'redo'){if(!book || saving)return;setSaving(true);setError('');try{await run(async()=>{updateBook(await api<Book>(`/api/books/${book.id}/${kind}`,'POST',{revision:book.edit_state.revision}));});}catch(e){reportError(String(e));}finally{setSaving(false);}}
  useEffect(()=>{const listener=(e:KeyboardEvent)=>{if(modal || !book || saving || !(e.ctrlKey || e.metaKey) || !['z','y'].includes(e.key.toLowerCase()))return;const tag=(e.target as Element)?.tagName?.toLowerCase();if(tag==='input'||tag==='textarea')return;const redo=e.shiftKey || e.key.toLowerCase()==='y';if(redo?book.edit_state.can_redo:book.edit_state.can_undo){e.preventDefault();void undoRedo(redo?'redo':'undo');}};window.addEventListener('keydown',listener);return()=>window.removeEventListener('keydown',listener);},[book,saving,modal]);
  async function saveProject(){if(!book)return;setSaving(true);setError('');try{await persist({view:currentView.current});await flush();const response=await fetch(`/api/books/${book.id}/project/export`);if(!response.ok)await readJSON(response);const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=(book.metadata.title?.[0] || 'project')+'.eproof';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){reportError(String(e));}finally{setSaving(false);}}
  async function importHistory(file:File){if(!book)return;setLoading(true);try{await flush();const form=new FormData();form.append('file',file);const response=await fetch(`/api/books/${book.id}/history/import`,{method:'POST',body:form});const value=await readJSON<Book>(response);await openBook(value);}catch(e){reportError(String(e));}finally{setLoading(false);if(historyInput.current)historyInput.current.value='';}}
  async function rectangle(page:number,rect:[number,number,number,number]){if(!project?.pdf || !paragraph)return;const mapping:Mapping={page,rectangle:rect,pdf_sha256:project.pdf.sha256};try{await persist({mappings:{[paragraph.id]:[...project.mappings[paragraph.id] || [],mapping]}});setSelecting(false);}catch(e){reportError(String(e));}}
  const prevAvailable=!!book && ((heading?heading.next_paragraph_index>0:index>0) || chapterIndex>0);const nextAvailable=!!book && ((heading?heading.next_paragraph_index<chapter!.paragraph_count:index<units.length-1) || chapterIndex<book.chapters.length-1);
  const allParagraphs=book?.chapters.flatMap(c=>c.paragraphs) || [];const checked=allParagraphs.filter(p=>project?.statuses[p.id]==='human_checked').length;const review=allParagraphs.filter(p=>project?.statuses[p.id]==='review').length;
  return <div className={`app ${readerMode?'reader-mode':''} ${readerEditing?'reader-editing':''} reader-tab-${readerTab}`} style={readerMode?{height:readerHeight,'--reader-height':`${readerHeight}px`} as React.CSSProperties:undefined} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();if(modal){reportError('編集画面を閉じてからファイルを読み込んでください。');return;}if(!loading)void readFiles(Array.from(e.dataTransfer.files));}}>
    <header><div className="brand"><span className="logo">校</span><h1>EPUB Proofreader</h1></div><WorkspaceMenu book={book} loading={loading} saving={saving} locked={modal} onLibrary={()=>setLibraryOpen(true)} onNew={()=>setNewProject(true)} onUndo={()=>void undoRedo('undo')} onRedo={()=>void undoRedo('redo')} onReplace={()=>setDialog('replace')} onHistory={()=>setDialog('history')} onBackup={()=>void saveProject()} onPublish={()=>setDialog('export')}/><input hidden type="file" ref={input} accept=".epub,.pdf,.eproof" multiple onChange={e=>void readFiles(Array.from(e.target.files || []))}/><input hidden type="file" ref={historyInput} accept=".json" onChange={e=>{const file=e.target.files?.[0];if(file)void importHistory(file);}}/></header>
    <div className="bookbar"><div className="project-summary"><strong title={book?.catalog?.filename || book?.metadata.title?.[0]}>{book?.catalog?.filename || '新しい校正ワークスペース'}</strong>{book?.catalog && <><span className="project-date" title="プロジェクト作成日時">{uploadDate(book.catalog.uploaded_at).replace(/:\d{2}$/,'')}</span><span className="project-version">{book.catalog.published_version?`v${book.catalog.published_version}`:'未発行'}</span></>}</div>{readerMode?<nav className="reader-toolbar" aria-label="読書と校正"><button aria-pressed={readerTab==='epub' && !readerEditing} disabled={modal} onClick={()=>{setReaderTab('epub');setReaderEditOrigin(null);}}>本文</button><button aria-pressed={readerTab==='pdf' && !readerEditing} disabled={!pdf || modal} title={pdf?'原本PDFに切り替え':'このプロジェクトにはPDFがありません'} onClick={()=>{setReaderTab('pdf');setReaderEditOrigin(null);}}>PDF</button><button className={readerEditing?'primary':''} aria-pressed={readerEditing} disabled={!book || modal} onClick={()=>{setChapterLanding(null);if(!readerEditing){readerReturnPosition.current=currentView.current.epubScroll??null;setReaderRestore(readerPosition.current);}setReaderTab('epub');setReaderEditOrigin(value=>value?null:'toolbar');}}>{readerEditing?'読書に戻る':'編集'}</button><button disabled={modal} onClick={()=>{chooseReader(false);setReaderEditOrigin(null);}}>通常表示</button></nav>:<div className="view-toggles"><button aria-pressed={!hidePdf} onClick={()=>setView(v=>({...v,hidePdf:!v.hidePdf}))}>原本 {hidePdf?'表示':'非表示'}</button><button aria-pressed={!hideInfo} onClick={()=>setView(v=>({...v,hideInfo:!v.hideInfo}))}>校正 {hideInfo?'表示':'非表示'}</button><button disabled={modal} onClick={()=>{chooseReader(true);setReaderTab('epub');setReaderEditOrigin(null);}}>読書表示</button></div>}</div>
    {!!book?.import_repairs?.length && <details className="import-repair-notice"><summary><span role="status">読み込み時に文字参照の破損を{book.import_repairs.length}箇所、自動修復しました（原本は保持）</span></summary><p>XMLエラーの後、一意に復元できた箇所だけを作業用データで修復しています。発行するEPUBには修復を含めます。</p>{book.import_repairs.map((r,i)=><div key={i}><strong>{r.path} · {r.line}行目</strong><code>{r.before}</code><span> → </span><code>{r.after}</code></div>)}</details>}
    {error && <div className="error" role="alert">{error}<button disabled={loading || modal} onClick={()=>{const b=activeBook.current;if(b)void openBook(b).then(()=>setError('')).catch(reportError);}}>保存済み状態を再読み込み</button><button aria-label="エラーを閉じる" onClick={()=>setError('')}>×</button></div>}
    <div className="panes" ref={panes}>
      <section className="pane pdf-pane" style={{display:readerMode?undefined:hidePdf?'none':undefined,flex:`0 0 ${left}%`}}><PdfPane vertical={rightToLeft} alignment={book && chapter && paragraph && pdfUnit && project?.pdf?{book,chapter,paragraph,unit:pdfUnit,pdfHash:project.pdf.sha256,mappings:project.mappings}:undefined} file={pdf} onError={reportError} settings={view.pdf} onSettings={setPdfSettings} selecting={selecting} onRectangle={(p,r)=>void rectangle(p,r)} mappings={(paragraph?project?.mappings[paragraph.id] || []:[]).filter(m=>m.pdf_sha256===project?.pdf?.sha256)}/></section>{!hidePdf && <div role="separator" aria-label="原本ペインの幅" aria-orientation="vertical" tabIndex={0} className="splitter" onPointerDown={e=>resize(e,'left')} onKeyDown={e=>{if(e.key==='ArrowLeft')setView(v=>({...v,left:Math.max(20,v.left-2)}));if(e.key==='ArrowRight')setView(v=>({...v,left:Math.min(52,v.left+2)}));}}/>}
      <section className="pane epub-pane"><div className="pane-heading"><span>02 / 本文</span><span className="badge green">{chapter?.writing_mode?.startsWith('vertical')?'縦書き':'横書き'}プレビュー</span></div><div className="toolbar"><select aria-label="章の選択" disabled={!book} value={chapterIndex} onChange={e=>selectChapter(Number(e.target.value))}>{book?book.chapters.map((c,i)=><option key={c.id} value={i}>{c.title}</option>):<option>章を選択</option>}</select><details className="reader-settings"><summary>表示設定</summary><label className="font-control">文字サイズ<input aria-label="文字サイズ" type="range" min={14} max={32} value={fontSize} onChange={e=>setView(v=>({...v,fontSize:Number(e.target.value),epubScroll:null}))}/><small>{fontSize}</small></label><small>{chapter?.writing_mode?.startsWith('vertical')?'縦書き':'横書き'}（EPUBの指定）</small></details></div>
        {book?html!==null?<EpubPane restoreBookmark={readerRestore} onBookmark={value=>{readerPosition.current=value;}} rightToLeft={rightToLeft} visible={!readerMode || readerTab==='epub' && !readerEditing} initialLanding={chapterLanding} hasPreviousChapter={chapterIndex>0} hasNextChapter={chapterIndex<(book?.chapters.length??0)-1} onChapterTurn={turnChapter} onVisibleUnit={(pid,sentence)=>{const i=units.findIndex(u=>u.paragraph_id===pid && (u.kind==='paragraph' || u.sentence_index===sentence));if(i>=0)chooseUnit(i);}} readerNavigation={readerMode} html={html} chapter={chapter} unit={unit} fontSize={fontSize} pendingCandidates={aiResults.filter(c=>c.book_id===book.id && c.target==='text' && c.chapter_id===chapter?.id && !c.stale && ['pending','held','undone'].includes(c.status))} readingOnly={readerMode && !readerEditing} aiHighlight={readerMode && !readerEditing?null:aiHighlight} onChoose={(pid,sentence)=>{readerReturnPosition.current=currentView.current.epubScroll??null;select(pid,sentence);setReaderRestore(readerPosition.current);if(readerMode){setReaderTab('epub');setReaderEditOrigin('text');}}} onRuby={ruby} onKey={onKey} initialScroll={view.epubScroll} onScroll={saveEpubScroll}/>:<div className="empty epub-empty">章を読み込み中…</div>:<div className="empty epub-empty"><span className="empty-symbol">文</span><h2>文字を、原本と照らす。</h2><p>「操作」→「新規プロジェクト」からEPUBを読み込んでください。<br/>作業内容はツール内に自動保存されます。</p></div>}
        <div className="pane-foot"><span>{book?`章 ${chapterIndex+1} / ${book.chapters.length}`:'EPUB未読み込み'}</span><span>{readerMode && unit?`校正対象：段落 ${unit.paragraph_index+1} / ${chapter?.paragraph_count}${unit.kind==='sentence'?`・文 ${unit.sentence_index!+1}`:''}`:'校正対象に追従'}</span></div>
      </section>
      {(!hideInfo || readerMode) && <><div role="separator" aria-label="情報ペインの幅" aria-orientation="vertical" tabIndex={0} className="splitter" onPointerDown={e=>resize(e,'right')} onKeyDown={e=>{if(e.key==='ArrowLeft')setView(v=>({...v,right:Math.min(36,v.right+2)}));if(e.key==='ArrowRight')setView(v=>({...v,right:Math.max(18,v.right-2)}));}}/><aside className="pane info-pane" aria-label="校正画面" style={{flex:`0 0 ${right}%`}}><div className="pane-heading"><span>03 / 校正</span><button disabled={!book} onClick={()=>paragraph && setEditTarget({paragraphId:paragraph.id})}>ルビの訂正</button></div>
        <div className="combined-navigation"><button disabled={!book || !aiNavigation.previousId} onClick={()=>setAIRequest({id:aiNavigation.previousId!,nonce:Date.now()})}>◀ 前のAI検知</button><button aria-label="前の段落・文" disabled={!prevAvailable} onClick={()=>navigate(-1)}>◀ 前へ</button><button aria-label="次の段落・文" disabled={!nextAvailable} onClick={()=>navigate(1)}>次へ ▶</button><button disabled={!book || !aiNavigation.nextId} onClick={()=>setAIRequest({id:aiNavigation.nextId!,nonce:Date.now()})}>次のAI検知 ▶</button></div>
        <div className="proof-position">{heading?<span aria-label="校正位置">見出し {chapter!.headings.findIndex(h=>h.id===heading.id)+1} / {chapter!.headings.length}</span>:<><span aria-label="校正位置">{unit?index+1:0} / {units.length}</span> · 段落 {unit?unit.paragraph_index+1:0} / {chapter?.paragraph_count || 0}</>}{unit?.kind==='sentence' && paragraph?` · 文 ${unit.sentence_index!+1} / ${paragraph.sentences.length}`:''}</div>
        <div className="info-scroll">
        {book && project && paragraph && unit && <InlineEditor onStructure={setBlockAction} onReviewed={acceptReview} aiFlags={aiResults} onAddRuby={setRubyAdd} key={`${book.id}:${paragraph.id}:${unit.sentence_index??"all"}`} onDone={async(source:ProofCompletion)=>{
          if(activeBook.current?.id!==source.bookId)return;
          const fresh=source.reviewedIds!==undefined?{results:reviewedCandidates(aiResults,source.reviewedIds)}:await api<AIState>(`/api/books/${source.bookId}/ai`);const current=activeBook.current;if(current?.id!==source.bookId)return;setAIResults(fresh.results);
          if(readerMode && readerEditOrigin==='text'){const v=currentView.current;const saved=readerRestore && readerRestore.chapterId===v.chapterId && readerRestore.paragraphId===v.paragraphId?{...readerRestore}:v.chapterId && v.paragraphId?{chapterId:v.chapterId,paragraphId:v.paragraphId,sentenceIndex:v.sentenceIndex??undefined,offset:16,scroll:readerReturnPosition.current??0}:null;setReaderRestore(saved);setView(v=>({...v,epubScroll:readerReturnPosition.current}));setReaderTab('epub');setReaderEditOrigin(null);return;}
          const next=nextProofLocation(current,source);
          setCurrentCandidate(null);setAiHighlight(null);setAIRequest(null);setReaderRestore(null);setChapterLanding(null);setSelectionToken(t=>t+1);
          if(next)setView(v=>({...v,chapterId:next.chapterId,paragraphId:next.unit.paragraph_id,sentenceIndex:next.unit.sentence_index,epubScroll:null,pdf:{...v.pdf,followText:true}}));
        }} heading={!!heading} book={book} paragraphId={paragraph.id} sentenceIndex={unit.kind==='sentence'?unit.sentence_index!:undefined} candidate={inlineCandidate} project={project} persist={persist} run={run} onUpdate={updateBook} onRuby={()=>setEditTarget({paragraphId:paragraph.id,sentenceIndex:unit.kind==='sentence'?unit.sentence_index!:undefined})}/>}
        {book && <details className="ai-settings"><summary>AI検査・結果一覧{aiNavigation.activity && <small className="ai-activity">{aiNavigation.activity}</small>}</summary><AIPanel reviewEvent={reviewEvent} selectionToken={selectionToken} onResults={setAIResults} onNavigation={setAINavigation} onSelected={setCurrentCandidate} navRequest={aiRequest} onEditCandidate={candidate=>{if(candidate.target==='ruby')setEditTarget({paragraphId:candidate.paragraph_id,rubyIndex:candidate.ruby_index});}} onModal={setAiModal} book={book} paragraphId={heading?undefined:paragraph?.id} chapterId={chapter?.id} onUpdate={updateBook} run={run} onJump={candidate=>{if(candidate.book_id!==book.id)return;if(readerMode)setReaderEditOrigin(origin=>origin??'toolbar');setReaderTab('epub');const c=book.chapters.find(c=>c.id===candidate.chapter_id);const p=c?.paragraphs.find(p=>p.id===candidate.paragraph_id);const sentence=p?.sentences.find(s=>s.start<=candidate.start && candidate.start<s.end);if(!c || !p)return;setAiHighlight(candidate);setCurrentCandidate(candidate);setView(v=>{const mapping=project?.mappings[p.id]?.find(m=>m.pdf_sha256===project.pdf?.sha256);return {...v,chapterId:c.id,paragraphId:p.id,sentenceIndex:p.unit_mode==='sentence'?sentence?.index:null,epubScroll:null,hideInfo:false,pdf:mapping?{...v.pdf,page:mapping.page}:v.pdf};});if(candidate.target==='ruby')setEditTarget({paragraphId:p.id,sentenceIndex:p.unit_mode==='sentence'?sentence?.index:undefined,rubyIndex:candidate.ruby_index});}}/></details>}
        <details className="info-section"><summary>校閲状態・原本との対応</summary>{project && <ProjectPanel project={project} paragraph={paragraph} pdfPage={view.pdf.page} selecting={selecting} onSelecting={v=>{setSelecting(v);if(v){setReaderTab('pdf');setReaderEditOrigin(null);setView(s=>({...s,hidePdf:false}));}}} persist={persist} onOpenMapping={m=>{setReaderTab('pdf');setReaderEditOrigin(null);setPdfSettings({page:m.page,scrollLeft:0,scrollTop:0});setView(v=>({...v,hidePdf:false}));}} onError={reportError}/>}</details>

        {book && <details className="info-section"><summary>プロジェクト情報</summary><p>{book.file_count}ファイル / 綴じ方向 {book.direction}</p><a href={`/api/books/${book.id}/original`}>読み込み時の原本をダウンロード</a><p className="editor-help">上部の「操作」→「作業データを書き出す」で別の環境へ移せます。通常の作業は自動保存されます。</p><button onClick={()=>input.current?.click()}>保存データ・追加PDFを読み込む</button><button disabled={modal || loading} onClick={()=>historyInput.current?.click()}>履歴JSONを読み込む</button>{!!book.warnings.length && <details><summary>読み込み時の注意</summary>{book.warnings.map((w,i)=><p key={i}>{w}</p>)}</details>}{project && Object.keys(project.drafts).length>0 && <details><summary>未保存入力</summary>{Object.entries(project.drafts).map(([key,d])=><div key={key}><p>{d.text}</p>{Object.values(d.rubies).map((r,i)=><p key={i}>{r.base}〈{r.reading}〉</p>)}</div>)}</details>}</details>}
      </div></aside></>}
    </div>
    {newProject && <NewProjectDialog onClose={()=>setNewProject(false)} onCreate={readFiles}/>}
    {blockAction?.kind==='chapter' && book && paragraph && <ChapterDialog book={book} paragraph={paragraph} position={blockAction.position} sentenceIndex={unit?.kind==='sentence'?unit.sentence_index!:undefined} run={run} onUpdate={updateBook} onClose={()=>setBlockAction(null)}/>}
    {libraryOpen && <LibraryDialog onClose={()=>setLibraryOpen(false)} onOpen={async id=>{await flush();await openBook(await api<Book>(`/api/books/${id}`));}} onDeleted={id=>{try{Object.keys(localStorage).filter(key=>key===`eproof-view:${id}` || key.startsWith(`eproof-draft:${id}:`)).forEach(key=>localStorage.removeItem(key));}catch{reportError('削除済みプロジェクトのブラウザ内保護データを削除できませんでした。');}if(activeBook.current?.id===id){readyId.current=null;setBook(null);activeBook.current=null;setPdf(null);setHtml(null);localStorage.removeItem('lastBook');localStorage.removeItem(`eproof-view:${id}`);}}}/>}
    {book && project && editTarget && <RubyReviewDialog onReviewed={acceptReview} onAdd={()=>setRubyAdd({paragraphId:editTarget.paragraphId})} book={book} project={project} persist={persist} run={run} onUpdate={updateBook} target={editTarget} candidates={aiResults} onResults={setAIResults} onClose={()=>setEditTarget(null)}/>}
    {book && rubyAdd && <RubyAddDialog book={book} target={rubyAdd} run={run} onUpdate={updateBook} onClose={()=>setRubyAdd(null)}/>}
    {book && dialog && <ProofingDialog run={run} kind={dialog} book={book} paragraphId={paragraph?.id} onUpdate={updateBook} onClose={()=>setDialog(null)}/>}
    {book && blockAction && blockAction.kind!=='chapter' && paragraph && unit && <StructureDialog run={run} action={blockAction.kind==='insert'?'insert':blockAction.position==='before'?'merge':'merge_next'} position={blockAction.position} sentenceIndex={unit.kind==='sentence'?unit.sentence_index!:undefined} book={book} paragraph={paragraph} previous={chapter?.paragraphs[unit.paragraph_index-1]} next={chapter?.paragraphs[unit.paragraph_index+1]} onUpdate={updateBook} onClose={()=>setBlockAction(null)}/>}
    <footer><span className="muted" role="status" title={book?`確認済み ${checked} / ${allParagraphs.length}段落 · 要再確認 ${review}`:undefined}>{book?`${store.saveState} · 編集 ${book.edit_state.edit_count}件 · 確認済み ${checked}/${allParagraphs.length}`:'新規プロジェクトから校正を開始'}</span></footer>
  </div>;
}
