import type {Book,Chapter,Paragraph,ProofUnit,Mapping} from './types';
export interface PdfTextItem {str:string;transform:number[];height?:number;dir?:string}
export interface PdfTextPage {page:number;variants:string[]}
export interface PdfTextIndex {pages:PdfTextPage[];postings:Map<string,number[]>;usable:boolean}
export interface PdfFollowTarget {book:Book;chapter:Chapter;paragraph:Paragraph;unit:ProofUnit;pdfHash:string;mappings:Record<string,Mapping[]>}
export interface PdfLocation {page:number;method:'text'|'original'|'similar'|'neighbor'|'chapter'|'registered';confidence:number}
export function normalizePdfText(value:string){return value.normalize('NFKC').replace(/[^\p{L}\p{N}]/gu,'');}
function grams(value:string){const chars=Array.from(value),out=new Set<string>();for(let i=0;i<chars.length-2;i++)out.add(chars.slice(i,i+3).join(''));return out;}
/** OCR PDFs often emit every Japanese glyph as an ltr item. Compare both
 * reading orders, plus the original stream; omit smaller furigana in variants. */
export function pdfPageVariants(items:PdfTextItem[]):string[]{
 const text=items.filter(i=>i.str.trim() && i.transform.length>=6);
 const size=(i:PdfTextItem)=>Math.hypot(i.transform[2],i.transform[3]) || Math.hypot(i.transform[0],i.transform[1]) || 1;
 const sizes=text.flatMap(i=>Array(Math.min(24,Array.from(i.str).length)).fill(size(i))).sort((a,b)=>a-b);
 const median=sizes[Math.floor(sizes.length/2)] || 1,body=text.filter(i=>size(i)>=median*.68);
 function ordered(vertical:boolean){
  const groups:{position:number;items:PdfTextItem[]}[]=[];
  for(const item of [...body].sort((a,b)=>vertical?b.transform[4]-a.transform[4]:b.transform[5]-a.transform[5])){
   const position=item.transform[vertical?4:5];let group=groups.find(g=>Math.abs(g.position-position)<median*.48);
   if(!group){group={position,items:[]};groups.push(group);}group.items.push(item);
  }
  return groups.map(g=>g.items.sort((a,b)=>vertical?b.transform[5]-a.transform[5]:a.transform[4]-b.transform[4]).map(i=>i.str).join('')).join('');
 }
 return [...new Set([text.map(i=>i.str).join(''),body.map(i=>i.str).join(''),ordered(true),ordered(false)].map(normalizePdfText))].filter(Boolean);
}
export function buildPdfTextIndex(pages:PdfTextPage[]):PdfTextIndex{
 const normalized=pages.map(p=>({page:p.page,variants:[...new Set(p.variants.map(normalizePdfText))].filter(Boolean)}));
 const postings=new Map<string,number[]>();let usable=false;
 normalized.forEach((p,i)=>{
  if(p.variants.some(v=>(v.match(/\p{L}/gu)?.length || 0)>=24))usable=true;
  for(const gram of new Set(p.variants.flatMap(v=>[...grams(v)]))){const list=postings.get(gram) || [];list.push(i);postings.set(gram,list);}
 });return {pages:normalized,postings,usable};
}
interface SearchContext {hint?:number;min?:number;max?:number}
interface Hit {page:number;confidence:number}
function queries(text:string){
 const value=normalizePdfText(text);if(value.length<8)return [];
 const out:{text:string;confidence:number}[]=[];
 if(value.length<=240)out.push({text:value,confidence:1});
 else out.push({text:value.slice(0,160),confidence:.97});
 if(value.length>=32)for(const start of new Set([0,Math.floor(value.length/3),Math.floor(value.length*2/3),Math.max(0,value.length-32)])){
  const text=value.slice(start,start+32);if(text.length>=20)out.push({text,confidence:.9});
 }
 return out;
}
function search(index:PdfTextIndex,texts:string[],context:SearchContext={},fuzzy=true):Hit|null{
 const allowed=(page:number)=>(context.min===undefined || page>=context.min) && (context.max===undefined || page<=context.max);
 const candidates=new Map<number,number>();
 for(const text of [...new Set(texts.filter(Boolean))])for(const query of queries(text)){
  const pages=new Set<number>();
  index.pages.forEach((p,i)=>{
   if(!allowed(p.page))return;
   if(p.variants.some(v=>v.includes(query.text)))pages.add(p.page);
   // A sentence may cross a physical page boundary. Keep its starting page.
   const next=index.pages[i+1];if(next && next.page===p.page+1)for(const v of p.variants)for(const w of next.variants){
    const joined=v.slice(-240)+w.slice(0,240),at=joined.indexOf(query.text),boundary=Math.min(240,v.length);
    if(at>=0 && at<boundary && at+query.text.length>boundary)pages.add(p.page);
   }
  });
  let chosen:number|undefined;
  if(pages.size===1)chosen=[...pages][0];
  else if(context.hint!==undefined){const near=[...pages].filter(p=>Math.abs(p-context.hint!)<=1);if(near.length===1)chosen=near[0];}
  if(chosen!==undefined)candidates.set(chosen,Math.max(candidates.get(chosen) || 0,query.confidence));
 }
 const exact=[...candidates].sort((a,b)=>b[1]-a[1] || Math.abs(a[0]-(context.hint??a[0]))-Math.abs(b[0]-(context.hint??b[0])));
 if(exact.length && (exact.length===1 || exact[0][1]>exact[1][1] || context.hint!==undefined && Math.abs(exact[0][0]-context.hint)<Math.abs(exact[1][0]-context.hint)))return {page:exact[0][0],confidence:exact[0][1]};
 if(!fuzzy)return null;
 const scores=new Map<number,number>();
 for(const text of texts){const value=normalizePdfText(text).slice(0,220),needles=grams(value);if(needles.size<14)continue;
  const counts=new Map<number,number>();for(const gram of needles)for(const i of index.postings.get(gram) || [])if(allowed(index.pages[i].page))counts.set(i,(counts.get(i) || 0)+1);
  for(const [i,count] of counts){const score=count/needles.size;if(score>=.74)scores.set(index.pages[i].page,Math.max(scores.get(index.pages[i].page) || 0,score));}
 }
 const ranked=[...scores].sort((a,b)=>b[1]-a[1]);
 if(ranked.length && (!ranked[1] || ranked[0][1]-ranked[1][1]>=.08))return {page:ranked[0][0],confidence:ranked[0][1]*.86};
 return null;
}
interface Anchor {paragraph:number;page:number}
const anchorCache=new WeakMap<PdfTextIndex,Map<string,Anchor[]>>();
function chapterAnchors(index:PdfTextIndex,target:PdfFollowTarget):Anchor[]{
 const {chapter,book,mappings,pdfHash}=target;
 const key=JSON.stringify([book.id,book.edit_state.revision,chapter.id,pdfHash,mappings]);
 let cache=anchorCache.get(index);if(!cache){cache=new Map();anchorCache.set(index,cache);}const cached=cache.get(key);if(cached)return cached;
 const anchors:Anchor[]=[];const step=Math.max(1,Math.ceil(chapter.paragraphs.length/24));
 for(let i=0;i<chapter.paragraphs.length;i++){
  const p=chapter.paragraphs[i],manual=mappings[p.id]?.find(m=>m.pdf_sha256===pdfHash && m.page<=index.pages.length);
  if(manual){anchors.push({paragraph:i,page:manual.page});continue;}
  if(i%step!==0 && i!==chapter.paragraphs.length-1)continue;
  const hit=search(index,[p.text,p.original_text],{},false);if(hit)anchors.push({paragraph:i,page:hit.page});
 }
 // Keep an ordered chain: isolated hits from repeated headers must not pull
 // an entire chapter into a different part of the source book.
 const chain:Anchor[][]=[];
 for(let i=0;i<anchors.length;i++){let previous:Anchor[]=[];for(let j=0;j<i;j++)if(anchors[j].page<=anchors[i].page && chain[j].length>previous.length)previous=chain[j];chain.push([...previous,anchors[i]]);}
 const ordered=chain.reduce((best,current)=>current.length>best.length?current:best,[] as Anchor[]);
 cache.set(key,ordered);if(cache.size>16)cache.delete(cache.keys().next().value!);return ordered;
}
export function findPdfLocation(index:PdfTextIndex,target:PdfFollowTarget):PdfLocation|null{
 if(!index.usable)return null;
 const {chapter,paragraph,unit,mappings,pdfHash}=target;
 const pIndex=chapter.paragraphs.findIndex(p=>p.id===paragraph.id);
 const manual=(mappings[paragraph.id] || []).filter(m=>m.pdf_sha256===pdfHash && m.page>=1 && m.page<=index.pages.length);
 if(manual.length){const i=unit.kind==='sentence'?Math.min(manual.length-1,Math.floor((unit.sentence_index || 0)/Math.max(1,paragraph.sentences.length)*manual.length)):0;return {page:manual[i].page,method:'registered',confidence:1};}
 const anchors=chapterAnchors(index,target),near=anchors.reduce<Anchor|undefined>((best,a)=>!best || Math.abs(a.paragraph-pIndex)<Math.abs(best.paragraph-pIndex)?a:best,undefined);
 const first=anchors[0],last=anchors.at(-1);
 const context:SearchContext=anchors.length>=2?{hint:near?.page,min:Math.max(1,first.page-2),max:last!.page+2}:{};
 const current=search(index,[unit.text],context);if(current)return {...current,method:current.confidence>=.9?'text':'similar'};
 // Paragraph IDs preserve their import-time text even after sentence edits.
 const original=unit.kind==='sentence'?null:search(index,[paragraph.original_text],context);if(original)return {...original,method:'original'};
 if(pIndex>=0){
  const neighborhood:Hit[]=[];
  // Use the start of surrounding sentences, rather than requiring the edited
  // sentence itself to still appear in the PDF.
  if(unit.kind==='sentence')for(const offset of [-1,1,-2,2]){const s=paragraph.sentences[(unit.sentence_index || 0)+offset];if(s){const hit=search(index,[s.text.slice(0,80)],context);if(hit)neighborhood.push(hit);}}
  for(const offset of [-1,1,-2,2]){const p=chapter.paragraphs[pIndex+offset];if(p){const hit=search(index,[offset<0?p.text.slice(-100):p.text.slice(0,100),offset<0?p.original_text?.slice(-100):p.original_text?.slice(0,100)].filter(Boolean) as string[],context);if(hit)neighborhood.push(hit);}}
  if(neighborhood.length){const page=neighborhood[0].page;if(neighborhood.length===1 || neighborhood.some((h,i)=>i>0 && Math.abs(h.page-page)<=2))return {page,method:'neighbor',confidence:.7};}
  if(unit.kind==='sentence'){const old=search(index,[paragraph.original_text],context);if(old)return {...old,method:'original'};const whole=search(index,[paragraph.text],context);if(whole)return {...whole,method:'similar'};}
  if(near && anchors.length>=2)return {page:near.page,method:'chapter',confidence:.5};
 }
 const heading=search(index,[chapter.title,...(chapter.headings || []).map(h=>h.text)],{},false);
 return heading?{page:heading.page,method:'chapter',confidence:.45}:null;
}
