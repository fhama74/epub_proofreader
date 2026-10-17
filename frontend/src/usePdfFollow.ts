import {useEffect,useRef,useState} from 'react';
import type {PDFDocumentProxy} from 'pdfjs-dist';
import {buildPdfTextIndex,findPdfLocation,pdfPageVariants,type PdfTextPage,type PdfTextIndex,type PdfFollowTarget,type PdfLocation} from './pdfAlignment';
const cache=new Map<string,PdfTextIndex>();
const labels:Record<PdfLocation['method'],string>={text:'本文から追従',original:'修正前の本文から追従',similar:'類似する本文から追従（推定）',neighbor:'前後の文から追従（推定）',chapter:'章内の近くの位置（推定）',registered:'登録済みの対応ページ'};
export default function usePdfFollow(doc:PDFDocumentProxy|null,target:PdfFollowTarget|undefined,enabled:boolean,onFollow:(page:number)=>void){
 const [index,setIndex]=useState<PdfTextIndex|null>(null);const [progress,setProgress]=useState({done:0,total:0,errors:0});const [failure,setFailure]=useState(false);const [location,setLocation]=useState<PdfLocation|null>(null);
 const current=useRef({target,onFollow});current.current={target,onFollow};
 const hash=target?.pdfHash;
 useEffect(()=>{
  let cancelled=false;setIndex(null);setLocation(null);setFailure(false);setProgress({done:0,total:doc?.numPages || 0,errors:0});
  if(!doc || !hash)return;
  const saved=cache.get(hash);if(saved){setIndex(saved);setProgress({done:doc.numPages,total:doc.numPages,errors:0});return;}
  void (async()=>{
   const pages:PdfTextPage[]=[];let errors=0;
   for(let n=1;n<=doc.numPages;n++){
    if(cancelled)return;
    try{const page=await doc.getPage(n);if(cancelled)return;const content=await page.getTextContent();if(cancelled)return;pages.push({page:n,variants:pdfPageVariants(content.items.filter(i=>'str' in i))});page.cleanup();}
    catch{if(cancelled)return;errors++;pages.push({page:n,variants:[]});}
    if(n%8===0 || n===doc.numPages){setProgress({done:n,total:doc.numPages,errors});await new Promise<void>(resolve=>setTimeout(resolve,0));}
   }
   if(cancelled)return;const value=buildPdfTextIndex(pages);if(errors===0)cache.set(hash,value);if(cache.size>2)cache.delete(cache.keys().next().value!);setIndex(value);if(errors===doc.numPages)setFailure(true);
  })().catch(()=>{if(!cancelled)setFailure(true);});
  return()=>{cancelled=true;};
 },[doc,hash]);
 const mappingKey=JSON.stringify(target?.mappings || {});
 useEffect(()=>{
  if(!enabled || !index || !current.current.target){setLocation(null);return;}
  const next=findPdfLocation(index,current.current.target);setLocation(next);if(next)current.current.onFollow(next.page);
 },[index,enabled,target?.book.id,target?.book.edit_state.revision,target?.chapter.id,target?.paragraph.id,target?.unit.sentence_index,mappingKey]);
 let status='PDF未読み込み';
 if(doc && !enabled)status='手動でページを移動';
 else if(doc && !target)status='本文を選ぶとPDFが追従します';
 else if(doc && failure)status='文字を読み取れませんでした（手動で移動）';
 else if(doc && !index)status=`PDFの文字を準備中 ${progress.done} / ${progress.total}ページ`;
 else if(index && !index.usable)status='利用できる文字レイヤーがありません（手動で移動）';
 else if(index && location)status=`${labels[location.method]} · ${location.page}ページ`;
 else if(index)status='対応位置を特定できません（手動で移動できます）';
 return {status,loading:!!doc && !index && !failure,approximate:location && ['similar','neighbor','chapter'].includes(location.method),errors:progress.errors};
}
