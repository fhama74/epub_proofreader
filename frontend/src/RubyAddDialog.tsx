import {useEffect,useState} from 'react';
import {api,dialogKeys,useDialogFocus} from './dialogUtils';
import type {Book,Paragraph} from './types';
export type RubySelection={paragraphId:string;start?:number;end?:number};
export default function RubyAddDialog({book,target,run,onUpdate,onClose}:{book:Book;target:RubySelection;run:<T>(f:()=>Promise<T>)=>Promise<T>;onUpdate:(b:Book)=>void;onClose:()=>void}){
 const ref=useDialogFocus();const [details,setDetails]=useState<(Omit<Paragraph,'rubies'> & {editor_text:string;rubies:(Paragraph['rubies'][number]&{start:number;end:number})[]})|null>(null);
 const [start,setStart]=useState(target.start??0),[end,setEnd]=useState(target.end??((target.start??0)+1)),[reading,setReading]=useState('');
 const [page,setPage]=useState(Math.floor((target.start??0)/120)),[anchor,setAnchor]=useState<number|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{let active=true;void api<typeof details>(`/api/books/${book.id}/paragraphs/${target.paragraphId}`).then(d=>{if(active)setDetails(d);}).catch(e=>active&&setError(String(e)));return()=>{active=false;};},[book.id,target.paragraphId]);
 const chars=Array.from(details?.editor_text||'');const base=chars.slice(start,end).join('');
 const overlaps=details?.rubies.some(r=>r.start<end&&r.end>start);
 function choose(i:number){if(anchor===null){setStart(i);setEnd(i+1);setAnchor(i);}else{setStart(Math.min(anchor,i));setEnd(Math.max(anchor,i)+1);setAnchor(null);}}
 async function add(){if(!details)return;setBusy(true);setError('');try{await run(async()=>onUpdate(await api<Book>(`/api/books/${book.id}/paragraphs/${target.paragraphId}/ruby-structure`,'POST',{revision:details.revision,expected_token:details.token,action:'add',start,end,reading})));onClose();}catch(e){setError(String(e));}finally{setBusy(false);}}
 return <div className="modal-shade"><section ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label="ルビを追加" className="editor-dialog ruby-add-dialog" onKeyDown={e=>dialogKeys(e,()=>{if(!busy)onClose();})}><div className="dialog-heading"><h2>ルビを追加</h2><button disabled={busy} aria-label="ルビ追加を閉じる" onClick={onClose}>×</button></div>
  <p>親文字の最初と最後の文字をタップして範囲を選択できます。</p>{error&&<p role="alert" className="dialog-error">{error}</p>}
  {details?<><div className="ruby-character-picker">{chars.slice(page*120,(page+1)*120).map((c,i)=><button type="button" key={i} disabled={busy} aria-label={`親文字の位置 ${page*120+i+1} ${c}`} aria-pressed={start<=page*120+i&&page*120+i<end} onClick={()=>choose(page*120+i)}>{c===' '?'␣':c}</button>)}</div><div className="ruby-picker-pages"><button disabled={busy||page<=0} onClick={()=>setPage(p=>p-1)}>前の文字</button><small>{page*120+1}〜{Math.min(chars.length,(page+1)*120)} / {chars.length}文字</small><button disabled={busy||(page+1)*120>=chars.length} onClick={()=>setPage(p=>p+1)}>後の文字</button></div>
  <div className="ruby-form"><label>開始文字<input type="number" aria-label="親文字の開始" min={1} max={chars.length} value={start+1} disabled={busy} onChange={e=>setStart(Math.max(0,Number(e.target.value)-1))}/></label><label>終了文字<input type="number" aria-label="親文字の終了" min={1} max={chars.length} value={end} disabled={busy} onChange={e=>setEnd(Number(e.target.value))}/></label></div>
  <label className="edit-label">親文字<input aria-label="追加する親文字" value={base} readOnly/></label><label className="edit-label">読み<input autoComplete="off" aria-label="追加する読み" value={reading} disabled={busy} onChange={e=>setReading(e.target.value)} maxLength={2000}/></label><div className="ruby-add-preview" aria-label="ルビのプレビュー"><ruby>{base}<rt>{reading||'よみ'}</rt></ruby></div>{overlaps&&<p className="dialog-error">既存のルビと重なっています。範囲を選び直してください。</p>}<small>追加・削除はUndo／Redoの対象外です。この操作より前の編集にはUndoで戻れません。</small></>:<p>読み込み中…</p>}
  <div className="dialog-actions"><button disabled={busy} onClick={onClose}>キャンセル</button><button className="primary" disabled={busy||!details||!base||!reading.trim()||start>=end||end>chars.length||!!overlaps} onClick={()=>void add()}>{busy?'追加中…':'追加'}</button></div>
 </section></div>;
}
