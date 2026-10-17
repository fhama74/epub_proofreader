/** Mark exact base-text ranges, including native ruby bases, on every browser. */
export function clearAITextMarks(doc:Document){
 doc.querySelectorAll('span[data-ai-text-mark]').forEach(el=>{const parent=el.parentNode;el.replaceWith(...Array.from(el.childNodes));parent?.normalize();});
}
export function markAIText(paragraph:Element,candidates:{start:number;end:number;original:string}[]){
 const doc=paragraph.ownerDocument;
 const walker=doc.createTreeWalker(paragraph,4,{acceptNode:n=>n.parentElement?.closest('rt,rp,rtc')?2:1});
 const slots:{node:Text;chars:string[];start:number}[]=[];const text:string[]=[];let node;
 while((node=walker.nextNode())){const chars=Array.from(node.textContent || '');slots.push({node:node as Text,chars,start:text.length});text.push(...chars);}
 const intervals=candidates.filter(c=>Array.from(c.original).length>=1 && Array.from(c.original).length<=2 && c.start>=0 && c.end>=c.start && c.end<=text.length && text.slice(c.start,c.end).join('')===c.original).map(c=>({start:c.start===c.end?Math.max(0,c.start-1):c.start,end:c.start===c.end?Math.min(text.length,Math.max(0,c.start-1)+1):c.end})).sort((a,b)=>a.start-b.start);
 const merged:{start:number;end:number}[]=[];
 for(const range of intervals){const last=merged.at(-1);if(last && range.start<=last.end)last.end=Math.max(last.end,range.end);else merged.push({...range});}
 for(const slot of slots){
  // Split from right to left so earlier offsets stay valid (DOM uses UTF-16).
  for(const range of [...merged].reverse()){
   const a=Math.max(0,range.start-slot.start),b=Math.min(slot.chars.length,range.end-slot.start);if(b<=a)continue;
   const end=slot.chars.slice(0,b).join('').length,start=slot.chars.slice(0,a).join('').length;
   if(end<slot.node.length)slot.node.splitText(end);
   const part=start?slot.node.splitText(start):slot.node;
   const span=doc.createElement('span');span.setAttribute('data-ai-text-mark','');span.className='ai-unreviewed-text';part.replaceWith(span);span.append(part);
  }
 }
}
