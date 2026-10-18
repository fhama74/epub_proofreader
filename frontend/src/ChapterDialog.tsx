import {useState} from 'react';
import {api,dialogKeys,useDialogFocus} from './dialogUtils';
import type {Book,Paragraph} from './types';
export default function ChapterDialog({book,paragraph,onUpdate,onClose,run,position='before',sentenceIndex}:{book:Book;paragraph:Paragraph;position?:'before'|'after';sentenceIndex?:number;onUpdate:(b:Book)=>void;onClose:()=>void;run:<T>(action:()=>Promise<T>)=>Promise<T>}){
 const [title,setTitle]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');const ref=useDialogFocus();
 const current=book.chapters.find(c=>[...c.paragraphs,...c.headings].some(p=>p.id===paragraph.id));
 const [level,setLevel]=useState(current?.heading_level || 1);
 const close=()=>{if(!busy && (!title || window.confirm('入力中の章名を破棄しますか？')))onClose();};
 async function create(){if(!title.trim())return;setBusy(true);setError('');try{
  await run(async()=>{
   const d=await api<{token:string;chapter_token:string;revision:number}>(`/api/books/${book.id}/paragraphs/${paragraph.id}`);
   if(d.revision!==book.edit_state.revision)throw new Error('本文が変更されています。章を再読み込みしてから作成してください。');
   onUpdate(await api<Book>(`/api/books/${book.id}/chapters/split`,'POST',{revision:d.revision,expected_token:d.token,expected_chapter_token:d.chapter_token,paragraph_id:paragraph.id,title:title.trim(),level,position,sentence_index:sentenceIndex,reason:'選択した文の前後から新しい章を作成'}));
  });onClose();
 }catch(e){setError(String(e));}finally{setBusy(false);}}
 return <div className="modal-shade"><section ref={ref} tabIndex={-1} className="editor-dialog" role="dialog" aria-modal="true" aria-label="新しい章を作成" onKeyDown={e=>dialogKeys(e,close)}>
  <div className="dialog-heading"><h2>現在の文の{position==='before'?'前':'後'}に章を追加</h2><button disabled={busy} onClick={close}>閉じる</button></div>
  <p>表示中の{sentenceIndex===undefined?'段落':'文'}の{position==='before'?'直前':'直後'}から、この章の末尾までを新しい章へ移します。段落の途中であれば、その位置で段落も分けます。章名を見出しと目次に追加します。</p>
  <label className="edit-label">新しい章名<input aria-label="新しい章名" value={title} maxLength={200} disabled={busy} onChange={e=>setTitle(e.target.value)}/></label>
  <label className="edit-label">章のレベル<select aria-label="章のレベル" value={level} disabled={busy} onChange={e=>setLevel(Number(e.target.value))}>{[1,2,3,4,5,6].map(n=><option key={n} value={n}>{`h${n} · 第${n}レベル${n===1?'（最上位）':''}`}</option>)}</select></label>
  <p className="editor-help">例：「第一部」はh1、その中の「一・二・三」はh2。目次も選んだレベルに合わせて階層化します。先行する上位の項目がなければ、目次の最上位に置きます。本文内に別途作られた目次ページは更新しません。</p>
  <p className="dialog-meta">追加位置の基準となる{sentenceIndex===undefined?'段落':'文'}</p><pre>{(sentenceIndex===undefined?paragraph.text:paragraph.sentences[sentenceIndex]?.text) || '（空の段落）'}</pre>
  <p className="editor-help">本文・ルビ・PDFとの対応を保持します。変更した段落の校閲状態は再確認が必要です。見出しは同じXHTML内に追加し、ファイルは増やしません。未更新の入力は先に更新してください。</p>
  {error && <p role="alert" className="dialog-error">{error}</p>}
  <div className="dialog-actions"><button disabled={busy} onClick={close}>キャンセル</button><button className="primary" disabled={busy || !title.trim()} onClick={()=>void create()}>{busy?'章と目次を更新中…':'章を作成'}</button></div>
 </section></div>;
}
