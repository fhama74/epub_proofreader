import { useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import type {Mapping,PdfSettings} from './types';
import usePdfFollow from './usePdfFollow';
import {pinchZoom,pdfOutputRatio} from './pdfGesture';
import type {PdfFollowTarget} from './pdfAlignment';
import worker from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
GlobalWorkerOptions.workerSrc = worker;
export default function PdfPane({file,onError,settings,onSettings,selecting=false,onRectangle,mappings=[],alignment,vertical=false}:{vertical?:boolean;file:File|null;onError:(s:string)=>void;settings:PdfSettings;onSettings:(value:Partial<PdfSettings>)=>void;selecting?:boolean;onRectangle?:(page:number,rect:[number,number,number,number])=>void;mappings?:Mapping[];alignment?:PdfFollowTarget;readerNavigation?:boolean}) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const {page,zoom,mode}=settings;
  const follow=usePdfFollow(doc,alignment,(settings.followText??true) && !selecting,page=>{if(latest.current.settings.page!==page)latest.current.onSettings({page,scrollLeft:0,scrollTop:0});});
  const setPage=(page:number)=>onSettings({page,scrollLeft:0,scrollTop:0});
  const setMode=(mode:PdfSettings['mode'])=>onSettings({mode,scrollLeft:0,scrollTop:0});
  const [width, setWidth] = useState(500);
  const [height, setHeight] = useState(600);
  const [rendering, setRendering] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const wrap=useRef<HTMLDivElement>(null);const renderedScale=useRef(1);
  const touches=useRef(new Map<number,{x:number;y:number}>());
  const pinch=useRef<{distance:number;scale:number;zoom:number;fx:number;fy:number;cx:number;cy:number}|null>(null);
  const pendingFocus=useRef<{page:number;fx:number;fy:number;cx:number;cy:number}|null>(null);
  const drag = useRef<{x: number; y: number; left: number; top: number} | null>(null);
  const latest=useRef({settings,onSettings});latest.current={settings,onSettings};
  const selection=useRef<[number,number]|null>(null);const [rectangle,setRectangle]=useState<[number,number,number,number]|null>(null);
  const scrollTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  useEffect(()=>()=>clearTimeout(scrollTimer.current),[]);
  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof getDocument> | undefined;
    clearTimeout(scrollTimer.current);setDoc(null);setRectangle(null);
    if (file) void file.arrayBuffer().then(data => {
      if (cancelled) return;
      task = getDocument({
        data,
        wasmUrl: '/pdfjs/wasm/',
        cMapUrl: '/pdfjs/cmaps/',
        cMapPacked: true,
        standardFontDataUrl: '/pdfjs/standard_fonts/',
      });
      return task.promise.then(pdf => { if (!cancelled) {setDoc(pdf);if(latest.current.settings.page>pdf.numPages)latest.current.onSettings({page:pdf.numPages});} });
    }).catch(e => { if (!cancelled) onError(`PDFを読み込めません: ${String(e)}`); });
    return () => { cancelled = true; if (task) void task.destroy(); };
  }, [file, onError]);
  useEffect(() => {
    const observer = new ResizeObserver(entries => { setWidth(entries[0].contentRect.width); setHeight(entries[0].contentRect.height); });
    if (viewport.current) observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!doc || !canvas.current || width<=0 || height<=0) return;
    let cancelled = false;
    let task: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | undefined;
    setRendering(true);
    void doc.getPage(Math.max(1,Math.min(doc.numPages,page))).then(pdfPage => {
      if (cancelled || !canvas.current) return;
      const natural = pdfPage.getViewport({scale: 1});
      const scale = mode === 'width' ? Math.max(0.1, (width - 40) / natural.width) : mode === 'page' ? Math.max(0.1, Math.min((width - 40) / natural.width, (height - 40) / natural.height)) : zoom;
      const view = pdfPage.getViewport({scale});
      renderedScale.current=scale;
      const ratio = pdfOutputRatio(view.width,view.height,window.devicePixelRatio);
      const c = canvas.current;
      c.width = Math.floor(view.width * ratio); c.height = Math.floor(view.height * ratio);
      c.style.width = `${view.width}px`; c.style.height = `${view.height}px`;
      const context = c.getContext('2d')!;
      task = pdfPage.render({canvasContext: context, canvas: c, viewport: view, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0]});
      return task.promise;
    }).then(() => { if (!cancelled) {setRendering(false);if(viewport.current){const v=viewport.current,f=pendingFocus.current,c=canvas.current;v.scrollLeft=latest.current.settings.scrollLeft;v.scrollTop=latest.current.settings.scrollTop;if(f && f.page===page && c){const box=c.getBoundingClientRect(),bounds=v.getBoundingClientRect();v.scrollLeft+=box.left-bounds.left+box.width*f.fx-f.cx;v.scrollTop+=box.top-bounds.top+box.height*f.fy-f.cy;pendingFocus.current=null;latest.current.onSettings({scrollLeft:v.scrollLeft,scrollTop:v.scrollTop});}}} }).catch(e => { if (!cancelled) {setRendering(false); onError(`PDF表示エラー: ${String(e)}`);} });
    return () => { cancelled = true; task?.cancel(); };
  }, [doc, page, zoom, mode, width, height, onError]);
  useEffect(()=>{touches.current.clear();pinch.current=null;drag.current=null;pendingFocus.current=null;if(wrap.current)wrap.current.style.transform='';},[doc,page]);
  function beginPointer(e:React.PointerEvent<HTMLDivElement>){
    if(!doc || selecting || e.button!==0)return;
    const v=e.currentTarget;v.setPointerCapture(e.pointerId);
    if(e.pointerType==='touch'){
      touches.current.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(touches.current.size>=2 && canvas.current){
        const [a,b]=Array.from(touches.current.values()),box=canvas.current.getBoundingClientRect(),bounds=v.getBoundingClientRect();
        const x=(a.x+b.x)/2,y=(a.y+b.y)/2;
        pinch.current={distance:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)),scale:renderedScale.current,zoom:renderedScale.current,fx:(x-box.left)/box.width,fy:(y-box.top)/box.height,cx:x-bounds.left,cy:y-bounds.top};drag.current=null;clearTimeout(scrollTimer.current);return;
      }
    }
    drag.current={x:e.clientX,y:e.clientY,left:v.scrollLeft,top:v.scrollTop};
  }
  function movePointer(e:React.PointerEvent<HTMLDivElement>){
    if(touches.current.has(e.pointerId))touches.current.set(e.pointerId,{x:e.clientX,y:e.clientY});
    const p=pinch.current;
    if(p && touches.current.size>=2 && wrap.current){
      const [a,b]=Array.from(touches.current.values());p.zoom=pinchZoom(p.scale,Math.hypot(a.x-b.x,a.y-b.y),p.distance);
      wrap.current.style.transformOrigin=`${p.fx*100}% ${p.fy*100}%`;wrap.current.style.transform=`scale(${p.zoom/p.scale})`;return;
    }
    if(drag.current){const d=drag.current;e.currentTarget.scrollLeft=d.left-e.clientX+d.x;e.currentTarget.scrollTop=d.top-e.clientY+d.y;}
  }
  function endPointer(e:React.PointerEvent<HTMLDivElement>){
    touches.current.delete(e.pointerId);drag.current=null;
    const p=pinch.current;
    if(p){pinch.current=null;if(wrap.current)wrap.current.style.transform='';
      if(e.type!=='pointercancel'){pendingFocus.current={page,fx:p.fx,fy:p.fy,cx:p.cx,cy:p.cy};onSettings({mode:'custom',zoom:p.zoom});}
    }
    if(touches.current.size===1){const a=Array.from(touches.current.values())[0];drag.current={x:a.x,y:a.y,left:e.currentTarget.scrollLeft,top:e.currentTarget.scrollTop};}
  }
  const changeZoom=(zoom:number)=>onSettings({mode:'custom',zoom,scrollLeft:0,scrollTop:0});
  const point=(event:React.PointerEvent)=>{const box=canvas.current!.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),Math.max(0,Math.min(1,(event.clientY-box.top)/box.height))] as [number,number];};
  return <>
    <div className="pane-heading"><span>01 / 原本</span><span className="badge">PDF</span></div>
    <div className="toolbar pdf-toolbar">
      <input aria-label="PDFページ番号" type="number" min={1} max={doc?.numPages || 1} value={page} onChange={e => setPage(Math.max(1, Math.min(doc?.numPages || 1, Number(e.target.value) || 1)))}/><small>/ {doc?.numPages || '—'}</small>
      <select aria-label="PDF表示倍率" value={mode === 'custom' ? String(zoom) : mode} onChange={e => ['width','page'].includes(e.target.value) ? setMode(e.target.value as PdfSettings['mode']) : changeZoom(Number(e.target.value))}>
        <option value="width">横幅に合わせる</option><option value="page">ページ全体</option>
        {mode==='custom' && ![.5,.75,1,1.25,1.5,2,3].includes(zoom) && <option value={zoom}>{Math.round(zoom*100)}%</option>}
        {[0.5, 0.75, 1, 1.25, 1.5, 2, 3].map(n => <option key={n} value={n}>{n * 100}%</option>)}
      </select>
    </div>
    {file && <div className={`pdf-follow ${follow.approximate?'approximate':''}`}><label><input type="checkbox" aria-label="本文にPDFを追従" checked={settings.followText??true} onChange={e=>onSettings({followText:e.target.checked})}/>本文に追従</label><span role="status" title={follow.errors?`文字を取得できなかったページ：${follow.errors}ページ`:undefined}>{doc?follow.status:'PDFを読み込み中…'}</span></div>}
    {doc && <div className={`pdf-side-navigation ${vertical?'vertical-sides':''}`} aria-label="PDFのページ送り"><button className="reader-side-page previous-side" aria-label="PDF前ページ" disabled={page<=1} onClick={()=>setPage(page-1)}>{vertical?'▶':'◀'}</button><button className="reader-side-page next-side" aria-label="PDF次ページ" disabled={page>=doc.numPages} onClick={()=>setPage(page+1)}>{vertical?'◀':'▶'}</button></div>}
    <div className={`pdf-viewport ${selecting?'selecting':''}`} ref={viewport} onScroll={e=>{if(!doc || rendering || pinch.current)return;const {scrollLeft,scrollTop}=e.currentTarget;clearTimeout(scrollTimer.current);scrollTimer.current=setTimeout(()=>latest.current.onSettings({scrollLeft,scrollTop}),180);}} onPointerDown={beginPointer} onPointerMove={movePointer} onPointerUp={endPointer} onPointerCancel={endPointer}>
      {file ? <><div ref={wrap} className="pdf-canvas-wrap" onPointerDown={e=>{if(!selecting || e.button!==0)return;e.stopPropagation();e.currentTarget.setPointerCapture(e.pointerId);selection.current=point(e);setRectangle(null);}} onPointerMove={e=>{if(!selection.current)return;const [x,y]=point(e),[a,b]=selection.current;setRectangle([Math.min(a,x),Math.min(b,y),Math.max(a,x),Math.max(b,y)]);}} onPointerUp={e=>{if(!selection.current)return;const [x,y]=point(e),[a,b]=selection.current;selection.current=null;setRectangle(null);const r:[number,number,number,number]=[Math.min(a,x),Math.min(b,y),Math.max(a,x),Math.max(b,y)];if(r[2]-r[0]>.005 && r[3]-r[1]>.005)onRectangle?.(page,r);}} onPointerCancel={()=>{selection.current=null;setRectangle(null);}}><canvas ref={canvas} aria-label="PDF原本ページ"/>{[...mappings.filter(m=>m.page===page && m.rectangle).map(m=>m.rectangle!),...(rectangle?[rectangle]:[])].map((r,i)=><span key={i} className="pdf-region" style={{left:`${r[0]*100}%`,top:`${r[1]*100}%`,width:`${(r[2]-r[0])*100}%`,height:`${(r[3]-r[1])*100}%`}}/>)}</div>{rendering && <span className="rendering" role="status">ページ描画中…</span>}</> : <div className="empty"><span className="empty-symbol">▧</span><h2>原本をそばに。</h2><p>PDFをここへドロップするか、<br/>03／校正の「プロジェクト情報」から追加してください。</p><small>スキャン画像PDFにも対応</small></div>}
    </div>
    <div className="pane-foot">{file?.name || 'PDF未読み込み'}<span>{selecting?'ドラッグで対応範囲を選択':'ドラッグで移動・2本指で拡大縮小'}</span></div>
  </>;
}
