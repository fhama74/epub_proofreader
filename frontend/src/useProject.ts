import {useCallback,useRef,useState} from 'react';
import {api} from './dialogUtils';
import type {Project} from './types';
export type ProjectPatch=Partial<Pick<Project,'statuses'|'mappings'|'view'>> & {drafts?:Record<string,Project['drafts'][string]|null>};
export const defaultView={fontSize:20,left:36,right:28,hidePdf:false,hideInfo:false,epubScroll:null,pdf:{followText:true,page:1,zoom:1,mode:'page' as const,scrollLeft:0,scrollTop:0}};
export default function useProject(onError:(s:string)=>void){
  const [project,setProject]=useState<Project|null>(null);const [saveState,setSaveState]=useState('保存済み');
  const current=useRef<{id:string;project:Project}|null>(null);const chain=useRef<Promise<unknown>>(Promise.resolve());
  const initialize=useCallback((id:string,p:Project)=>{current.current={id,project:p};chain.current=Promise.resolve();setProject(p);setSaveState('保存済み');},[]);
  const refresh=useCallback(async()=>{const state=current.current;if(!state)return;const p=await api<Project>(`/api/books/${state.id}/project`);if(current.current?.id===state.id)initialize(state.id,p);},[initialize]);
  const persist=useCallback((patch:ProjectPatch)=>{
    const id=current.current?.id;if(!id)return Promise.reject(new Error('プロジェクトが読み込まれていません。'));
    setSaveState('保存中…');
    const operation=chain.current.catch(()=>{}).then(async()=>{
      if(current.current?.id!==id)throw new Error('別の書籍へ移動しました。');
      try{const p=await api<Project>(`/api/books/${id}/project`,'PATCH',{version:current.current.project.version,...patch});if(current.current?.id===id){current.current={id,project:p};setProject(p);setSaveState('保存済み');}return p;}
      catch(error){setSaveState('保存失敗 — 再読み込みが必要');onError(String(error));throw error;}
    });chain.current=operation;return operation;
  },[onError]);
  const run=useCallback(<T,>(action:()=>Promise<T>):Promise<T>=>{const result=chain.current.then(action);chain.current=result;return result;},[]);
  const flush=useCallback(async()=>{await chain.current;},[]);
  const accept=useCallback((p:Project)=>{if(!current.current)return;current.current={id:current.current.id,project:p};setProject(p);},[]);
  return {project,persist,initialize,refresh,flush,run,accept,saveState};
}
