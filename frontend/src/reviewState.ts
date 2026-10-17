import type {Candidate} from './aiTypes';
import type {Paragraph} from './types';
/** A single outstanding finding wins over incomplete and completed sentences. */
export function reviewStatus(paragraph:Paragraph,flags:Candidate[],target:'body'|'ruby'='body'){
 const state=paragraph.review_state?.[target];
 const red=flags.some(c=>c.paragraph_id===paragraph.id && c.target===(target==='body'?'text':'ruby') && !c.stale && ['pending','held','undone'].includes(c.status) && (target==='ruby' || Array.from(c.original).length>=1 && Array.from(c.original).length<=2));
 const green=state?.confirmed??(target==='body' && paragraph.status==='human_checked');
 return {color:red?'red':green?'green':'yellow',label:red?'AI指摘あり':green?'確定済み':'未確定'};
}
