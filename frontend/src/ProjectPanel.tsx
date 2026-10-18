import {useState} from 'react';
import type {Mapping,Paragraph,Project,ProofStatus} from './types';
import type {ProjectPatch} from './useProject';
export const statusLabels:Record<ProofStatus,string>={unchecked:'未確認',ai_checked:'AI確認済み',human_checked:'人間確認済み',review:'要再確認'};
export default function ProjectPanel({project,paragraph,pdfPage,selecting,onSelecting,persist,onOpenMapping,onError,onStatusChange}:{onStatusChange?:()=>Promise<void>;project:Project;paragraph?:Paragraph;pdfPage:number;selecting:boolean;onSelecting:(v:boolean)=>void;persist:(patch:ProjectPatch)=>Promise<Project>;onOpenMapping:(mapping:Mapping)=>void;onError:(s:string)=>void}){
  const [busy,setBusy]=useState(false);const mappings=paragraph?project.mappings[paragraph.id] || []:[];
  async function status(value:ProofStatus){if(!paragraph)return;setBusy(true);try{await persist({statuses:{[paragraph.id]:value}});await onStatusChange?.();}catch(e){onError(String(e));}finally{setBusy(false);}}
  async function addPage(){if(!paragraph || !project.pdf)return;const item={page:pdfPage,rectangle:null,pdf_sha256:project.pdf.sha256};try{await persist({mappings:{[paragraph.id]:[...mappings.filter(m=>JSON.stringify(m)!==JSON.stringify(item)),item]}});}catch(e){onError(String(e));}}
  async function remove(index:number){if(!paragraph)return;try{await persist({mappings:{[paragraph.id]:mappings.filter((_,i)=>i!==index)}});}catch(e){onError(String(e));}}
  return <div className="project-panel">
    <label className="proof-status-label">この段落の確認状態<select aria-label="段落の確認状態" value={paragraph?project.statuses[paragraph.id] || 'unchecked':'unchecked'} disabled={!paragraph || busy} onChange={e=>void status(e.target.value as ProofStatus)}>{Object.entries(statusLabels).filter(([value])=>value!=='ai_checked' || !!paragraph && project.statuses[paragraph.id]==='ai_checked').map(([value,label])=><option key={value} value={value} disabled={value==='ai_checked'}>{label}</option>)}</select></label>
    <details className="mapping-panel"><summary>原本PDFとの対応 {mappings.length?`(${mappings.length})`:''}</summary><p className="editor-help">現在の段落を複数ページ・範囲に対応付けます。</p><div className="mapping-actions"><button disabled={!paragraph || !project.pdf} onClick={()=>void addPage()}>現在のPDFページを登録</button><button disabled={!paragraph || !project.pdf} aria-pressed={selecting} onClick={()=>onSelecting(!selecting)}>{selecting?'範囲選択を終了':'PDFの範囲を選択'}</button></div>{selecting && <p className="editor-help">01／原本の画像上をドラッグしてください。</p>}
    {mappings.map((m,i)=><div className="mapping-item" key={i}><button disabled={m.pdf_sha256!==project.pdf?.sha256} onClick={()=>onOpenMapping(m)}>PDF {m.page}ページ{m.rectangle?'・範囲あり':''}{m.pdf_sha256!==project.pdf?.sha256?'（別のPDF）':''}</button><button aria-label={`PDF対応 ${i+1}を解除`} onClick={()=>void remove(i)}>×</button></div>)}</details>
  </div>;
}
