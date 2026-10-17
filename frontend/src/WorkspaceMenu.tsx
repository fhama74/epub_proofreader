import {useEffect,useRef} from 'react';
import type {Book} from './types';
type Props={book:Book|null;loading:boolean;saving:boolean;locked:boolean;onLibrary:()=>void;onNew:()=>void;onUndo:()=>void;onRedo:()=>void;onReplace:()=>void;onHistory:()=>void;onBackup:()=>void;onPublish:()=>void};
export default function WorkspaceMenu(p:Props){
 const ref=useRef<HTMLDetailsElement>(null);
 useEffect(()=>{const outside=(e:PointerEvent)=>{if(ref.current && !ref.current.contains(e.target as Node))ref.current.open=false;};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);},[]);
 function choose(action:()=>void){if(ref.current)ref.current.open=false;action();}
 return <details ref={ref} className="workspace-menu" onKeyDown={e=>{if(e.key==='Escape' && ref.current){ref.current.open=false;ref.current.querySelector('summary')?.focus();}}}><summary aria-label="操作メニュー">操作 ▾</summary><nav aria-label="プロジェクトと校正の操作">
  <button disabled={p.loading || p.locked} onClick={()=>choose(p.onLibrary)}>プロジェクト一覧</button><button className="primary" disabled={p.loading || p.locked} onClick={()=>choose(p.onNew)}>新規プロジェクト</button>
  <button disabled={!p.book?.edit_state.can_undo || p.saving || p.locked} onClick={()=>choose(p.onUndo)}>Undo</button><button disabled={!p.book?.edit_state.can_redo || p.saving || p.locked} onClick={()=>choose(p.onRedo)}>Redo</button>
  <button disabled={!p.book || p.saving || p.locked} onClick={()=>choose(p.onReplace)}>検索・置換</button><button disabled={!p.book || p.saving || p.locked} onClick={()=>choose(p.onHistory)}>履歴</button>
  <button disabled={!p.book || p.saving || p.loading || p.locked} onClick={()=>choose(p.onBackup)} title="原本・編集履歴・未保存入力を.eproofファイルへ保存します">作業データを書き出す</button><button className="primary" disabled={!p.book || p.saving || p.locked} onClick={()=>choose(p.onPublish)}>EPUB発行</button>
 </nav></details>;
}
