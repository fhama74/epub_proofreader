import {useEffect,useRef,useState} from 'react';
import {api,dialogKeys,useDialogFocus} from './dialogUtils';
import type {Book,Draft,Paragraph,Project} from './types';
import type {Candidate} from './aiTypes';
import type {ProjectPatch} from './useProject';
export {api} from './dialogUtils';
export type EditorTarget={paragraphId:string;sentenceIndex?:number;rubyIndex?:number};
interface Details extends Paragraph {editor_text:string;rubies:(Paragraph['rubies'][number]&{index:number;start:number;end:number})[]}
export default function EditorDialog({book,target,project,persist,flush,run,onUpdate,onClose,onlyRuby=false,candidate=null}:{book:Book;target:EditorTarget;project:Project;persist:(patch:ProjectPatch)=>Promise<Project>;flush:()=>Promise<void>;run:<T>(action:()=>Promise<T>)=>Promise<T>;onUpdate:(b:Book)=>void;onClose:()=>void;onlyRuby?:boolean;candidate?:Candidate|null}){
  const {paragraphId,sentenceIndex}=target;const ref=useDialogFocus();const textarea=useRef<HTMLTextAreaElement>(null);const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  const [details,setDetails]=useState<Details|null>(null);const [before,setBefore]=useState('');const [text,setText]=useState('');const [rubies,setRubies]=useState<Draft['rubies']>({});const [reason,setReason]=useState('原本との照合');
  const [cursor,setCursor]=useState(0);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [draftState,setDraftState]=useState('');const [staleDraft,setStaleDraft]=useState<Draft|null>(null);
  const draftKey=onlyRuby?`ruby:${paragraphId}:${target.rubyIndex??'all'}:${sentenceIndex??'all'}`:`${paragraphId}:${sentenceIndex===undefined?'all':sentenceIndex}`;const localKey=`eproof-draft:${book.id}:${draftKey}`;
  const current=useRef({text,rubies,reason});current.current={text,rubies,reason};
  useEffect(()=>{let active=true;void api<Details>(`/api/books/${book.id}/paragraphs/${paragraphId}`).then(d=>{
    if(!active)return;const value=sentenceIndex===undefined?d.editor_text:d.sentences[sentenceIndex]?.text;if(value===undefined)throw new Error('文の構成が変わっています。選択し直してください。');
    setBefore(value);setText(value);setDetails(d);
    let saved=project.drafts[draftKey];try{const local=localStorage.getItem(localKey);if(local)saved=JSON.parse(local);}catch{setDraftState('ブラウザの未保存入力を読み込めません。');}
    if(!saved && onlyRuby && candidate && !candidate.stale && ['pending','held'].includes(candidate.status) && candidate.replacement!==null){const r=d.rubies.find(r=>r.index===candidate.ruby_index);if(r && r.base===candidate.original && candidate.ruby_before?.reading===r.readings.join('')){setRubies({[r.index]:{base:candidate.base_after || r.base,reading:candidate.reading_after || r.readings.join('')}});setReason(candidate.reason);}}
    if(saved){if(saved.revision===d.revision && saved.before===value){setText(saved.text);setRubies(saved.rubies);setReason(saved.reason);setDraftState('保護していた未保存入力を復元しました。');}else{setStaleDraft(saved);setDraftState('元の本文が更新されています。古い入力を確認してください。');}}
  }).catch(e=>{if(active)setError(String(e));});return()=>{active=false;clearTimeout(timer.current);};},[book.id,paragraphId,sentenceIndex]);
  const visible=details?.rubies.filter(r=>(!onlyRuby || target.rubyIndex===undefined || r.index===target.rubyIndex) && (sentenceIndex===undefined || (r.start>=details.sentences[sentenceIndex].start && r.end<=details.sentences[sentenceIndex].end))) || [];
  const dirty=text!==before || visible.some(r=>rubies[r.index] && (rubies[r.index].base!==r.base || rubies[r.index].reading!==r.readings[0]));
  useEffect(()=>{
    if(!details || busy || staleDraft)return;
    clearTimeout(timer.current);
    if(!dirty)return;
    const draft:Draft={revision:details.revision,text,rubies,reason,paragraphId,sentenceIndex,before};
    try{localStorage.setItem(localKey,JSON.stringify(draft));setDraftState('未保存入力をブラウザに保護済み');}catch{setDraftState('入力の保護に失敗しました。閉じる前に内容を控えてください。');}
    timer.current=setTimeout(()=>{void persist({drafts:{[draftKey]:draft}}).then(()=>setDraftState('未保存入力を自動保存済み')).catch(e=>setError(String(e)));},600);
    return()=>clearTimeout(timer.current);
  },[text,rubies,reason,dirty,details,busy,staleDraft,persist]);
  async function protectAndClose(){if(busy)return;clearTimeout(timer.current);if(dirty && details && !staleDraft){try{await persist({drafts:{[draftKey]:{revision:details.revision,...current.current,paragraphId,sentenceIndex,before}}});}catch{return;}}else if(!staleDraft){try{await clearDraft();}catch{return;}}onClose();}
  async function clearDraft(){clearTimeout(timer.current);await persist({drafts:{[draftKey]:null}});localStorage.removeItem(localKey);}
  async function discard(){setBusy(true);try{await clearDraft();onClose();}catch(e){setError(String(e));}finally{setBusy(false);}}
  async function save(){if(!details || staleDraft)return;clearTimeout(timer.current);setBusy(true);setError('');try{
    await flush();const updates=visible.filter(r=>r.editable && rubies[r.index] && (rubies[r.index].base!==r.base || rubies[r.index].reading!==r.readings[0])).map(r=>({index:r.index,...rubies[r.index]}));
    await run(async()=>{if(onlyRuby && candidate && candidate.replacement!==null && !candidate.stale && ['pending','held'].includes(candidate.status) && text===before && updates.length===1 && updates[0].index===candidate.ruby_index && updates[0].base===candidate.base_after && updates[0].reading===candidate.reading_after){const result=await api<{book:Book}>(`/api/books/${book.id}/ai/results/${candidate.id}/decision`,'POST',{action:'approve',revision:details.revision});onUpdate(result.book);return;}const result=await api<Book>(`/api/books/${book.id}/paragraphs/${paragraphId}/edit`,'PATCH',{revision:details.revision,expected_token:details.token,text,reason,sentence_index:sentenceIndex,expected_sentence:sentenceIndex===undefined?undefined:before,rubies:updates});
    onUpdate(result);if(onlyRuby && candidate && ['pending','held'].includes(candidate.status))await api(`/api/books/${book.id}/ai/results/${candidate.id}/decision`,'POST',{action:'confirm',revision:result.edit_state.revision});});await clearDraft();onClose();
  }catch(e){setError(String(e));}finally{setBusy(false);}}
  async function confirm(){if(!details || !candidate)return;setBusy(true);setError('');try{await run(()=>api(`/api/books/${book.id}/ai/results/${candidate.id}/decision`,'POST',{action:'confirm',revision:details.revision}));const exactAI=!!candidate && candidate.replacement!==null && text===before && visible.every(r=>!rubies[r.index] || (r.index===candidate.ruby_index && rubies[r.index].base===candidate.base_after && rubies[r.index].reading===candidate.reading_after));if(dirty && !exactAI){await persist({drafts:{[draftKey]:{revision:details.revision,...current.current,paragraphId,sentenceIndex,before}}});}else await clearDraft();onClose();}catch(e){setError(String(e));}finally{setBusy(false);}}
  const offset=(sentenceIndex===undefined?0:details?.sentences[sentenceIndex]?.start || 0)+cursor;
  async function split(){if(!details)return;setBusy(true);setError('');try{await flush();await run(async()=>{onUpdate(await api<Book>(`/api/books/${book.id}/structure`,'POST',{revision:details.revision,expected_token:details.token,expected_chapter_token:details.chapter_token,action:'split',paragraph_id:paragraphId,offset,reason:'カーソル位置で段落を分割'}));});await clearDraft();onClose();}catch(e){setError(String(e));}finally{setBusy(false);}}
  function rubyValue(index:number,field:'base'|'reading',value:string){const r=details!.rubies[index];setRubies(previous=>({...previous,[index]:{...(previous[index] || {base:r.base,reading:r.readings[0]}),[field]:value}}));}
  return <div className="modal-shade"><section ref={ref} tabIndex={-1} onKeyDown={e=>dialogKeys(e,()=>void protectAndClose())} className={`editor-dialog ${onlyRuby?'ruby-only':'unified-editor'}`} role="dialog" aria-modal="true" aria-label={onlyRuby?'ルビ編集':'編集'}>
    <div className="dialog-heading"><h2>{onlyRuby?'ルビを編集':sentenceIndex===undefined?'段落を編集':'一文を編集'}</h2><button aria-label="編集を閉じる" disabled={busy} onClick={()=>void protectAndClose()}>×</button></div>
    <p className="dialog-meta">{onlyRuby?'現在の親文字と読みを確認して更新します。訂正内容は赤字で表示します。':'本文と、該当するルビをまとめて修正します。'}</p>{error && <p role="alert" className="dialog-error">{error}</p>}
    {!details?<p>読み込み中…</p>:<>
      {staleDraft && <div className="dialog-error"><p>以前の未保存入力です。現在の本文へ自動適用しません。</p><pre>{staleDraft.text}</pre>{Object.values(staleDraft.rubies).map((r,i)=><p key={i}>{r.base}〈{r.reading}〉</p>)}<button onClick={()=>{setStaleDraft(null);void clearDraft().catch(e=>setError(String(e)));}}>古い入力を破棄して現在の本文を編集</button></div>}
      {!onlyRuby && <label className="edit-label">本文<textarea ref={textarea} aria-label="本文" value={text} onChange={e=>setText(e.target.value)} onSelect={()=>setCursor(Array.from(text.slice(0,textarea.current?.selectionStart || 0)).length)} maxLength={20000} spellCheck={false} disabled={busy || !!staleDraft}/></label>}
      {visible.length>0 && <div className="paired-rubies"><h3>{onlyRuby?'親文字と読み':'この本文のルビ'}</h3><p className="editor-help">{onlyRuby?'親文字と読みを修正できます。複雑なルビは構造を保護します。':'親文字は下の欄で修正します。本文欄では元の親文字を残してください。複雑なルビは構造を保護します。'}</p>{visible.map((r,i)=>{
        const v=rubies[r.index] || {base:r.base,reading:r.readings.join('・')};return <section className="paired-ruby" key={r.index} data-ruby-index={r.index}><strong>{i+1}. {r.base}〈{r.readings.join('・')}〉{!r.editable?'（保護）':''}</strong><div className="ruby-form"><label>親文字<input aria-label={`親文字 ${i+1}`} value={v.base} className={v.base!==r.base?'changed-text':''} maxLength={1000} disabled={busy || !r.editable || !!staleDraft} onChange={e=>rubyValue(r.index,'base',e.target.value)}/></label><label>読み（ルビ）<input aria-label={`読み ${i+1}`} value={v.reading} className={v.reading!==r.readings.join('・')?'changed-text':''} maxLength={2000} disabled={busy || !r.editable || !!staleDraft} onChange={e=>rubyValue(r.index,'reading',e.target.value)}/></label></div>{!r.editable && <p className="editor-help">複雑なルビはこの版では編集できません。</p>}</section>;
      })}</div>}
      {!onlyRuby && sentenceIndex!==undefined && <details className="context"><summary>段落全体を確認</summary><p>{details.editor_text}</p></details>}
      {!onlyRuby && text!==before && <div className="edit-diff"><div><strong>変更前の本文</strong><p>{before}</p></div><div><strong>変更後の本文</strong><p>{text}</p></div></div>}
      {!onlyRuby && <label className="edit-label">修正理由<input aria-label="修正理由" value={reason} disabled={busy || !!staleDraft} onChange={e=>setReason(e.target.value)}/></label>}
      {!onlyRuby && details.structure_editable && <div className="split-controls"><button disabled={busy || dirty || !!staleDraft || offset<=0 || offset>=Array.from(details.editor_text).length} onClick={()=>void split()}>カーソル位置で段落を分割</button><small>{dirty?'分割前に変更を保存してください。':`カーソル：${offset} / ${Array.from(details.editor_text).length}`}</small></div>}
      <p className="draft-state" role="status">{draftState || '入力は確定した本文と分けて自動保存します。'}</p>
      <div className="dialog-actions">{!onlyRuby && <><button disabled={busy} onClick={()=>void discard()}>入力を破棄</button><button disabled={busy} onClick={()=>void protectAndClose()}>閉じる（入力を保持）</button></>}{onlyRuby && candidate && ['pending','held'].includes(candidate.status) && <button disabled={busy} onClick={()=>void confirm()}>確認済みにする</button>}<button className="primary" disabled={busy || !dirty || !!staleDraft} onClick={()=>void save()}>{busy?'更新中…':onlyRuby?'更新':'変更を保存'}</button></div>
    </>}
  </section></div>;
}
