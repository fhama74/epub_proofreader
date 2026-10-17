import type {Chapter,Paragraph} from './types';
import type {EditorTarget} from './EditorDialog';
export interface RubyPosition {pid:string;index:number}
export function rubyRows(chapter?:Chapter){
 if(!chapter)return [];
 const ordered=[...chapter.paragraphs.map((paragraph,i)=>({paragraph,order:i*2+1})),...chapter.headings.map(paragraph=>({paragraph,order:paragraph.next_paragraph_index*2}))].sort((a,b)=>a.order-b.order);
 return ordered.flatMap(({paragraph})=>paragraph.rubies.map((ruby,index)=>({pid:paragraph.id,index,ruby,paragraph})));
}
export function nearestRuby(chapter:Chapter|undefined,target:EditorTarget,saved?:RubyPosition|null,details?:{sentences:Paragraph['sentences'];rubies:{start:number;end:number}[]}){
 const rows=rubyRows(chapter);if(!chapter || !rows.length)return null;
 const same=rows.filter(r=>r.pid===target.paragraphId);
 if(same.length){
  if(target.rubyIndex!==undefined)return same.find(r=>r.index===target.rubyIndex) || same[0];
  const sentence=target.sentenceIndex!==undefined?details?.sentences[target.sentenceIndex]:undefined;
  if(sentence && details)return same.reduce((best,r)=>{const distance=(index:number)=>{const ruby=details.rubies[index];return ruby?Math.max(sentence.start-ruby.end,ruby.start-sentence.end,0):Infinity;};return distance(r.index)<distance(best.index)?r:best;},same[0]);
  return same.find(r=>r.pid===saved?.pid && r.index===saved.index) || same[0];
 }
 const positions=new Map([...chapter.paragraphs.map((p,i)=>[p.id,i*2+1] as const),...chapter.headings.map(p=>[p.id,p.next_paragraph_index*2] as const)]);
 const at=positions.get(target.paragraphId);if(at===undefined)return rows.find(r=>r.pid===saved?.pid && r.index===saved.index) || rows[0];
 return rows.reduce((best,r)=>Math.abs(positions.get(r.pid)!-at)<Math.abs(positions.get(best.pid)!-at)?r:best,rows[0]);
}
