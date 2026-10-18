import {useState} from 'react';
import {api,dialogKeys,useDialogFocus} from './dialogUtils';
import type {Book,Paragraph} from './types';
export default function ChapterDialog({book,paragraph,onUpdate,onClose,run}:{book:Book;paragraph:Paragraph;onUpdate:(b:Book)=>void;onClose:()=>void;run:<T>(action:()=>Promise<T>)=>Promise<T>}){
 const [title,setTitle]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');const ref=useDialogFocus();
 const close=()=>{if(!busy && (!title || window.confirm('入力中の章名を破棄しますか？')))onClose();};
 async function create(){if(!title.trim())return;setBusy(true);setError('');try{
  await run(async()=>{
   const d=await api<{token:string;chapter_token:string;revision:number}>(`/api/books/${book.id}/paragraphs/${paragraph.id}`);
   if(d.revision!==book.edit_state.revision)throw new Error('本文が変更されています。章を再読み込みしてから作成してください。');
   onUpdate(await api<Book>(`/api/books/${book.id}/chapters/split`,'POST',{revision:d.revision,expected_token:d.token,expected_chapter_token:d.chapter_token,paragraph_id:paragraph.id,title:title.trim(),reason:'選択段落から新しい章を作成'}));
  });onClose();
 }catch(e){setError(String(e));}finally{setBusy(false);}}
 return <div className="modal-shade"><section ref={ref} tabIndex={-1} className="editor-dialog" role="dialog" aria-modal="true" aria-label="新しい章を作成" onKeyDown={e=>dialogKeys(e,close)}>
  <div className="dialog-heading"><h2>この位置から新しい章にする</h2><button disabled={busy} onClick={close}>閉じる</button></div>
  <p>選択した段落から、この章の末尾までを新しい章へ移します。章名を見出しと目次に追加します。</p>
  <label className="edit-label">新しい章名<input aria-label="新しい章名" value={title} maxLength={200} disabled={busy} onChange={e=>setTitle(e.target.value)}/></label>
  <p className="dialog-meta">新しい章の先頭</p><pre>{paragraph.text || '（空の段落）'}</pre>
  <p className="editor-help">本文・ルビ・校閲状態・PDFとの対応を引き継ぎます。保存後はUndoで元に戻せます。未更新の入力は先に更新してください。</p>
  {error && <p role="alert" className="dialog-error">{error}</p>}
  <div className="dialog-actions"><button disabled={busy} onClick={close}>キャンセル</button><button className="primary" disabled={busy || !title.trim()} onClick={()=>void create()}>{busy?'章と目次を更新中…':'章を作成'}</button></div>
 </section></div>;
}
