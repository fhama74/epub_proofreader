import {createRequestId} from './requestId';
import {useEffect,useRef,useState} from 'react';
import {api} from './dialogUtils';
import {uploadDate} from './LibraryDialog';
import type {Book,Publication} from './types';
export default function PublishPanel({book,ready,run,onUpdate,onBusy,onClose}:{book:Book;ready:boolean;run:<T>(action:()=>Promise<T>)=>Promise<T>;onUpdate:(book:Book)=>void;onBusy:(busy:boolean)=>void;onClose:()=>void}){
  const request=useRef({revision:book.edit_state.revision,expected_version:book.catalog?.published_version || 0,request_id:createRequestId()});const [published,setPublished]=useState<Publication|null>(null);const [releases,setReleases]=useState<Publication[]>([]);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  useEffect(()=>{void api<{publications:Publication[]}>(`/api/books/${book.id}/publications`).then(data=>setReleases(data.publications)).catch(e=>setError(String(e)));},[book.id]);
  async function publish(){setBusy(true);onBusy(true);setError('');try{const data=await run(async()=>{const result=await api<{publication:Publication;book:Book}>(`/api/books/${book.id}/publish`,'POST',request.current);onUpdate(result.book);return result;});setPublished(data.publication);setReleases(previous=>[data.publication,...previous.filter(p=>p.version!==data.publication.version)]);}catch(e){setError(String(e));}finally{setBusy(false);onBusy(false);}}
  return <div className="publish-panel">{error && <p className="dialog-error" role="alert">{error}</p>}
    {published?<div className="published-result"><strong>v{published.version}を発行・保存しました。</strong><p>この版はプロジェクト内に保持されます。再ダウンロードで版番号は増えません。</p><a className="download-button" href={`/api/books/${book.id}/publications/${published.version}/epub`}>v{published.version}のEPUBをダウンロード</a></div>:<><p>次の発行版：<strong>v{request.current.expected_version+1}</strong></p><p className="editor-help">発行すると版を確定して保存し、EPUB内に版番号を記録します。発行後も同じプロジェクトで修正を続けられます。</p></>}
    <div className="dialog-actions"><button disabled={busy} onClick={onClose}>閉じる</button>{!published && <button className="primary" disabled={busy || !ready} onClick={()=>void publish()}>{busy?'検証して版を保存中…':`v${request.current.expected_version+1}を発行して保存`}</button>}</div>
    {releases.length>0 && <details className="publication-list"><summary>保存済み発行版（{releases.length}）</summary>{releases.map(p=><a key={p.version} href={`/api/books/${book.id}/publications/${p.version}/epub`}>v{p.version} · {uploadDate(p.published_at)} · ダウンロード</a>)}</details>}
  </div>;
}
