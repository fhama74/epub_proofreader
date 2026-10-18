import type {Book,ProofUnit} from './types';
/** Keep the paragraph when edits change its sentence mode or sentence count. */
export function resolveProofUnit(units:ProofUnit[],paragraphId?:string,sentenceIndex?:number|null):ProofUnit|undefined{
 return units.find(u=>u.paragraph_id===paragraphId && (u.kind==='paragraph' || u.sentence_index===sentenceIndex))
  || units.find(u=>u.paragraph_id===paragraphId) || units[0];
}

/** Continue after the saved scope, using the updated book's sentence boundaries. */
export function nextProofLocation(book:Book,source:{paragraphId:string;sentenceIndex?:number}):{chapterId:string;unit:ProofUnit}|null{
 const chapterIndex=book.chapters.findIndex(c=>c.paragraphs.some(p=>p.id===source.paragraphId) || c.headings.some(h=>h.id===source.paragraphId));
 if(chapterIndex<0)return null;
 const chapter=book.chapters[chapterIndex],heading=chapter.headings.find(h=>h.id===source.paragraphId);
 let next:ProofUnit|undefined;
 if(heading)next=chapter.proof_units.find(u=>u.paragraph_index>=heading.next_paragraph_index);
 else{
  const last=chapter.proof_units.reduce((at,u,i)=>u.paragraph_id===source.paragraphId?i:at,-1);
  if(last<0)return null;
  if(source.sentenceIndex!==undefined)next=chapter.proof_units.find(u=>u.paragraph_id===source.paragraphId && u.kind==='sentence' && u.sentence_index!>source.sentenceIndex!);
  next??=chapter.proof_units[last+1];
 }
 if(next)return {chapterId:chapter.id,unit:next};
 for(const c of book.chapters.slice(chapterIndex+1))if(c.proof_units.length)return {chapterId:c.id,unit:c.proof_units[0]};
 return null;
}
