import { useEffect, useState } from 'react';
import { api, dialogKeys, useDialogFocus } from './dialogUtils';
import type { Book } from './types';
import PublishPanel from './PublishPanel';
export type DialogKind = 'history' | 'replace' | 'export';
interface HistoryEvent {id: string; timestamp: string; action: string; paragraph_ids: string[]; before: unknown; after: unknown; reason: string; state: string}
interface Validation {revision: number; internal: {status: string; changed_xhtml: string[]}; epubcheck: {status: string; message?: string; output?: string; report?: {messages?: {severity: string; message: string; ID?: string}[]}}}
const pretty=(value: unknown) => typeof value==='string' ? value : JSON.stringify(value,null,2);
export default function ProofingDialog({kind,book,paragraphId,onUpdate,onClose,run}: {run:<T>(action:()=>Promise<T>)=>Promise<T>;kind: DialogKind;book: Book;paragraphId?: string;onUpdate: (b: Book) => void;onClose: () => void}) {
  const dialogRef=useDialogFocus();
  const [target,setTarget]=useState('');const [replacement,setReplacement]=useState('');
  const [scope,setScope]=useState('paragraph');const [reason,setReason]=useState('検索・置換による校正');
  const [busy,setBusy]=useState(false);const [downloading,setDownloading]=useState(false);const [error,setError]=useState('');
  const [events,setEvents]=useState<HistoryEvent[]>([]);const [validation,setValidation]=useState<Validation | null>(null);
  useEffect(()=>{
    let active=true;
    if (kind==='history') void api<{events:HistoryEvent[]}>(`/api/books/${book.id}/history`).then(r=>{if(active)setEvents(r.events);}).catch(e=>{if(active)setError(String(e));});
    if (kind==='export') {
      setBusy(true);
      void api<Validation>(`/api/books/${book.id}/validate`,'POST',{revision:book.edit_state.revision}).then(r=>{if(active)setValidation(r);}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setBusy(false);});
    }
    return ()=>{active=false;};
  },[kind,book.id,book.edit_state.revision]);
  async function replace() {
    setBusy(true);setError('');
    try {const result=await run(async()=>{const result=await api<Book>(`/api/books/${book.id}/replace`,'POST',{revision:book.edit_state.revision,target,replacement,reason,paragraph_id:scope==='paragraph' ? paragraphId:undefined});onUpdate(result);return result;});if(result.edit_state.revision===book.edit_state.revision){setError('置換できる本文の一致箇所がありません。ルビの親文字・読みは一括置換の対象外です。');}else{onClose();}}catch(e){setError(String(e));}finally{setBusy(false);}
  }
  async function downloadHistory() {
    try {const result=await api(`/api/books/${book.id}/history`);const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`${book.metadata.title?.[0] || 'book'}_history.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){setError(String(e));}
  }
  return <div className="modal-shade"><section className="editor-dialog" ref={dialogRef} tabIndex={-1} onKeyDown={e=>dialogKeys(e,()=>{if(!busy && !downloading)onClose();})} role="dialog" aria-modal="true" aria-label={{history:'校正履歴',replace:'検索・置換',export:'EPUB発行'}[kind]}>
    <div className="dialog-heading"><h2>{{history:'校正履歴',replace:'検索・置換',export:'版番号付きEPUBを発行'}[kind]}</h2><button aria-label="ダイアログを閉じる" disabled={busy || downloading} onClick={onClose}>×</button></div>
    {error && <p role="alert" className="dialog-error">{error}</p>}
    {kind==='replace' && <><label className="edit-label">対象<select aria-label="置換対象" value={scope} onChange={e=>setScope(e.target.value)}><option value="paragraph" disabled={!paragraphId}>選択中の段落</option><option value="book">書籍全体</option></select></label><label className="edit-label">検索する文字列<input aria-label="検索する文字列" value={target} onChange={e=>setTarget(e.target.value)} maxLength={1000}/></label><label className="edit-label">置換後の文字列<input aria-label="置換後の文字列" value={replacement} onChange={e=>setReplacement(e.target.value)} maxLength={1000}/></label><label className="edit-label">修正理由<input aria-label="修正理由" value={reason} onChange={e=>setReason(e.target.value)} maxLength={1000}/></label><p className="editor-help">ルビや保護された要素に重なる箇所は対象外です。書籍全体の置換も1回のUndoで戻せます。</p><div className="dialog-actions"><button onClick={onClose} disabled={busy || downloading}>キャンセル</button><button className="primary" disabled={busy || !target || target===replacement} onClick={()=>void replace()}>{busy?'置換中…':'置換を適用'}</button></div></>}
    {kind==='history' && <><p className="dialog-meta">{events.length}件 · Undo／Redoを含む操作を記録しています。</p><div className="history-list">{[...events].reverse().slice(0,100).map(event=><details key={event.id}><summary>{new Date(event.timestamp).toLocaleString('ja-JP')} · {{combined:'本文・ルビ',text:'本文',ruby:'ルビ',replace:'置換',undo:'元に戻す',redo:'やり直す',sentence:'本文（一文）',chapter_split:'章作成',insert:'段落挿入',split:'段落分割',merge:'段落結合'}[event.action] || event.action} · {event.paragraph_ids.join(', ')}</summary><p>{event.reason}</p><div className="edit-diff"><div><strong>変更前</strong><pre>{pretty(event.before)}</pre></div><div><strong>変更後</strong><pre>{pretty(event.after)}</pre></div></div></details>)}{!events.length && <p>まだ修正履歴はありません。</p>}</div><div className="dialog-actions"><button onClick={()=>void downloadHistory()}>履歴JSONを出力</button><button onClick={onClose}>閉じる</button></div></>}
    {kind==='export' && <>{busy && <p role="status">EPUBの構造とEPUBCheckを検証中…</p>}{validation && <div className="validation-result"><p>内部構造検証：<strong>成功</strong></p><p>変更したXHTML：{validation.internal.changed_xhtml.length}ファイル</p><p>EPUBCheck：<strong>{{passed:'成功',failed:'エラーあり',unavailable:'未実行（未設定・利用不可）',timeout:'タイムアウト',error:'実行エラー'}[validation.epubcheck.status] || validation.epubcheck.status}</strong></p>{validation.epubcheck.message && <p>{validation.epubcheck.message}</p>}{validation.epubcheck.status==='failed' && <p className="dialog-error">EPUBCheckのエラーを修正してから発行してください。</p>}{validation.epubcheck.output && <details><summary>EPUBCheckの詳細</summary><pre>{validation.epubcheck.output}</pre></details>}<p className="editor-help">発行時は本文・CSS・画像・目次を保持し、OPFに校正版番号と発行識別情報を記録します。</p></div>}<PublishPanel book={book} ready={!!validation && ['passed','unavailable'].includes(validation.epubcheck.status)} run={run} onUpdate={onUpdate} onBusy={setDownloading} onClose={onClose}/></>}
  </section></div>;
}
