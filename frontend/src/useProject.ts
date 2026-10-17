import {useCallback,useRef,useState} from 'react';
import {api,APIError} from './dialogUtils';
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
      try{
        const base=current.current.project;let p:Project;
        try{p=await api<Project>(`/api/books/${id}/project`,'PATCH',{version:base.version,...patch});}
        catch(error){
          if(!(error instanceof APIError) || error.status!==409)throw error;
          const latest=await api<Project>(`/api/books/${id}/project`);
          const at=(value:Project,key:string)=>((value as unknown as Record<string,Record<string,unknown>>)[key]||{});
          const independent=Object.entries(patch).every(([key,items])=>Object.keys(items||{}).every(ident=>JSON.stringify(at(base,key)[ident])===JSON.stringify(at(latest,key)[ident]) || JSON.stringify(at(latest,key)[ident])===JSON.stringify((items as Record<string,unknown>)[ident])));
          if(!independent)throw new Error('同じ項目が別のブラウザーで変更されています。入力はこのブラウザーに保持しています。');
          if(current.current?.id!==id)throw new Error('別の書籍へ移動しました。');
          p=await api<Project>(`/api/books/${id}/project`,'PATCH',{version:latest.version,...patch});
        }
if(current.current?.id===id){current.current={id,project:p};setProject(p);setSaveState('保存済み');}return p;}
      catch(error){setSaveState('保存失敗 — 再読み込みが必要');onError(String(error));throw error;}
    });chain.current=operation;return operation;
  },[onError]);
  const run=useCallback(<T,>(action:()=>Promise<T>):Promise<T>=>{const result=chain.current.catch(()=>{}).then(action);chain.current=result;return result;},[]);
  const flush=useCallback(async()=>{await chain.current;},[]);
  const accept=useCallback((p:Project)=>{if(!current.current)return;current.current={id:current.current.id,project:p};setProject(p);},[]);
  return {project,persist,initialize,refresh,flush,run,accept,saveState};
}
