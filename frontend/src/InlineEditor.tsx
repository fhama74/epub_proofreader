import {bodyProposal} from './bodyProposal';
import ReviewBadge from './ReviewBadge';
import type {RubySelection} from './RubyAddDialog';
import {useEffect,useMemo,useRef,useState} from 'react';
import {api} from './dialogUtils';
import DiffEditor,{DiffText} from './DiffEditor';
import {textDiff} from './textDiff';
import type {Book,Draft,Paragraph,Project} from './types';
import type {Candidate} from './aiTypes';
import type {ProjectPatch} from './useProject';
interface Details extends Paragraph {token:string;chapter_token:string;editor_text:string}
export interface ProofCompletion {bookId:string;paragraphId:string;candidateId?:string;sentenceIndex?:number}
export default function InlineEditor({heading=false,book,paragraphId,sentenceIndex,candidate,project,persist,run,onUpdate,onRuby,onDone,onAddRuby,aiFlags=[]}:{onAddRuby:(target:RubySelection)=>void;aiFlags?:Candidate[];onDone?:(source:ProofCompletion)=>Promise<void>|void;heading?:boolean;book:Book;paragraphId:string;sentenceIndex?:number;candidate:Candidate|null;project:Project;persist:(p:ProjectPatch)=>Promise<Project>;run:<T>(f:()=>Promise<T>)=>Promise<T>;onUpdate:(b:Book)=>void;onRuby:()=>void}){
  const [details,setDetails]=useState<Details|null>(null);const [before,setBefore]=useState('');const [text,setText]=useState('');const [proposal,setProposal]=useState<string|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [note,setNote]=useState('');
  const [resetScope,setResetScope]=useState('paragraph'),[resetTarget,setResetTarget]=useState('body');
    const [cursor,setCursor]=useState(0);const textarea=useRef<HTMLTextAreaElement>(null);
  const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);const ref=useRef({text,before,details,busy});ref.current={text,before,details,busy};
  const key=`body:${paragraphId}:${sentenceIndex??'all'}`;const local=`eproof-draft:${book.id}:${key}`;const activeKey=useRef(key);activeKey.current=key;
  const selected=candidate?.book_id===book.id && candidate.paragraph_id===paragraphId && candidate.target==='text'?candidate:null;
  useEffect(()=>{let active=true;setDetails(null);setError('');setNote('');setProposal(null);
    void api<Details>(`/api/books/${book.id}/paragraphs/${paragraphId}`).then(d=>{
      if(!active)return;const unit=sentenceIndex===undefined?null:d.sentences[sentenceIndex];const value=unit?.text??d.editor_text;setDetails(d);setBefore(value);setText(value);
      let saved=project.drafts[key];try{const raw=localStorage.getItem(local);if(raw)saved=JSON.parse(raw);}catch{}
      if(saved && saved.before===value && (!saved.paragraphToken || saved.paragraphToken===d.token)){setText(saved.text);setNote('入力途中の内容を復元しました。');return;}
      if(saved){setNote('以前の入力は原文が変わったため自動適用していません。プロジェクト情報の未保存入力から確認できます。');}
      if(selected && (selected.match_count??1)>1)setNote('同じ文の一致箇所をすべて赤字で表示しています。原本を見て修正する箇所を選んでください。'+(selected.suggested_replacement!==null && selected.suggested_replacement!==undefined?` 訂正案：${selected.suggested_replacement||'削除'}`:''));
      const next=bodyProposal(value,unit?.start??0,selected);
      if(next!==null){setText(next);setProposal(next);setNote('AI推奨の訂正内容です。原本と照合して更新してください。');}

    }).catch(e=>active && setError(String(e)));return()=>{active=false;clearTimeout(timer.current);};
  },[book.id,book.edit_state.revision,paragraphId,sentenceIndex,selected?.id]);
  function protect(value=text){const d=ref.current.details;if(!d || value===ref.current.before || ref.current.busy)return Promise.resolve();const draft:Draft={paragraphToken:d.token,revision:d.revision,text:value,rubies:{},reason:'原本との照合',paragraphId,sentenceIndex,before:ref.current.before};try{localStorage.setItem(local,JSON.stringify(draft));}catch{}return persist({drafts:{[key]:draft}}).then(()=>{}).catch(e=>setError(String(e)));}
  function change(value:string){setText(value);const d=ref.current.details;if(d){try{localStorage.setItem(local,JSON.stringify({paragraphToken:d.token,revision:d.revision,text:value,rubies:{},reason:'原本との照合',paragraphId,sentenceIndex,before}));}catch{}}clearTimeout(timer.current);timer.current=setTimeout(()=>void protect(value),600);}
  async function update(){if(!details)return;clearTimeout(timer.current);setBusy(true);setError('');try{
    await run(async()=>{
      if(selected && proposal!==null && text===proposal && !selected.stale){const r=await api<{book:Book}>(`/api/books/${book.id}/ai/results/${selected.id}/decision`,'POST',{action:'approve',revision:details.revision});onUpdate(r.book);}
      else {
        let revision=details.revision;
        if(text!==before){const r=await api<Book>(`/api/books/${book.id}/paragraphs/${paragraphId}`,'PATCH',{revision,expected_token:details.token,text,reason:'原本との照合',sentence_index:sentenceIndex,expected_sentence:sentenceIndex===undefined?undefined:before});revision=r.edit_state.revision;onUpdate(r);}
        if(selected && ['pending','held'].includes(selected.status))await api(`/api/books/${book.id}/ai/results/${selected.id}/decision`,'POST',{action:'confirm',revision});
      }
    });await persist({drafts:{[key]:null}});localStorage.removeItem(local);if(activeKey.current===key)setBefore(text);setProposal(null);setNote('更新して確認済みにしました。');await onDone?.({bookId:book.id,paragraphId,candidateId:selected?.id,sentenceIndex});
  }catch(e){setError(String(e));}finally{setBusy(false);}}
  async function split(){if(!details)return;setBusy(true);setError('');try{const offset=(sentenceIndex===undefined?0:details.sentences[sentenceIndex].start)+cursor;await run(async()=>onUpdate(await api<Book>(`/api/books/${book.id}/structure`,'POST',{revision:details.revision,expected_token:details.token,expected_chapter_token:details.chapter_token,action:'split',paragraph_id:paragraphId,offset,reason:'段落を分割'})));await persist({drafts:{[key]:null}});localStorage.removeItem(local);}catch(e){setError(String(e));}finally{setBusy(false);}}
  async function confirm(){if(!details)return;clearTimeout(timer.current);setBusy(true);setError('');try{
    const reset=proposal!==null && text===proposal;
    const draft=text!==before && !reset?{revision:details.revision,text,rubies:{},reason:'原本との照合',paragraphId,sentenceIndex,before}:null;
    await run(async()=>onUpdate(await api<Book>(`/api/books/${book.id}/paragraphs/${paragraphId}/review`,'POST',{target:'body',index:sentenceIndex,expected_token:details.token})));
    await persist({drafts:{[key]:draft}});
    if(!draft){localStorage.removeItem(local);if(reset){setText(before);setProposal(null);}}
    setNote('原文を変更せず確認済みにしました。');await onDone?.({bookId:book.id,paragraphId,candidateId:selected?.id,sentenceIndex});
  }catch(e){setError(String(e));}finally{setBusy(false);}}

  useEffect(()=>{textarea.current?.closest('.info-scroll')?.scrollTo({top:0});},[book.id,paragraphId,sentenceIndex,selected?.id]);
  const paragraph=book.chapters.flatMap(c=>[...c.paragraphs,...c.headings]).find(p=>p.id===paragraphId);
  async function reset(){setBusy(true);setError('');try{await run(async()=>onUpdate(await api<Book>(`/api/books/${book.id}/review/reset`,'POST',{scope:resetScope,target:resetTarget,paragraph_id:paragraphId,chapter_id:book.chapters.find(c=>[...c.paragraphs,...c.headings].some(p=>p.id===paragraphId))?.id})));}catch(e){setError(String(e));}finally{setBusy(false);}}
  function addRuby(){if(!details)return;const offset=sentenceIndex===undefined?0:details.sentences[sentenceIndex].start;const a=Array.from(text.slice(0,textarea.current?.selectionStart||0)).length,b=Array.from(text.slice(0,textarea.current?.selectionEnd||0)).length;onAddRuby({paragraphId,start:offset+a,end:offset+(b>a?b:Math.min(Array.from(text).length,a+1))});}
  const diff=useMemo(()=>textDiff(before,text),[before,text]);
  return <section className="inline-editor info-section"><div className="inline-heading"><h3>{heading?'見出し':sentenceIndex===undefined?'段落':'文'}を校正</h3><ReviewBadge paragraph={paragraph} flags={aiFlags}/></div>{selected && <p className="ai-reason">{selected.reason}{(selected.match_count??1)>1?`（同じ文に${selected.match_count}箇所・手動確認）`:selected.replacement===null?'（修正案なし・要確認）':''}</p>}
    <div className="inline-columns"><div><label>現在の内容</label><pre aria-label="現在の本文">{before?<DiffText parts={diff.before}/>:details?'（空の段落）':'読み込み中…'}</pre></div><label>編集内容<DiffEditor parts={diff.after} inputRef={textarea} onSelect={()=>{const a=Array.from(text.slice(0,textarea.current?.selectionStart||0)).length;setCursor(a);}} aria-label="本文を編集" value={text} maxLength={20000} disabled={busy || !details} spellCheck={false} onChange={e=>change(e.target.value)} onBlur={()=>{clearTimeout(timer.current);void protect();}}/></label></div>
    {error && <p className="dialog-error" role="alert">{error}</p>}<div className="inline-update"><small role="status">{note || '入力途中の内容は保護されます。本文の確定は「更新」。'}</small><button disabled={busy || !details} onClick={()=>void confirm()}>確認済みにする</button><button className="primary" disabled={busy || !details || text===before} onClick={()=>void update()}>{busy?'更新中…':'更新'}</button></div>
  <div className="body-edit-actions"><button disabled={busy||!details||text!==before||!text} onClick={addRuby}>ルビを追加</button><small>{text!==before?'本文を更新してからルビを追加してください。':'文字を選択してから追加できます。'}</small></div>
  {details?.structure_editable && <details className="inline-structure"><summary>既存の段落を二つに分ける</summary><small>本文は追加せず、選んだ位置で段落を分けます。編集欄で分割位置をクリックしてください。</small><button disabled={busy || text!==before || cursor<=0 || cursor>=Array.from(text).length} onClick={()=>void split()}>カーソル位置で段落を分割</button></details>}
  <details className="inline-structure"><summary>校閲状態をリセット</summary><select aria-label="校閲リセットの範囲" value={resetScope} onChange={e=>setResetScope(e.target.value)}><option value="paragraph">この段落</option><option value="chapter">この章</option><option value="book">書籍全体</option></select><select aria-label="リセットする校閲状態" value={resetTarget} onChange={e=>setResetTarget(e.target.value)}><option value="body">本文</option><option value="ruby">ルビ</option><option value="both">本文とルビ</option></select><button disabled={busy} onClick={()=>void reset()}>未確定に戻す</button><small>本文・編集履歴・AI検出結果は削除しません。</small></details>
  </section>;
}
