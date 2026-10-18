import type {Book,Paragraph,Project,ProofScore} from './types';
import type {Candidate,AIState} from './aiTypes';
export interface ReviewReceipt {proof_score?:ProofScore;book_id:string;revision:number;paragraph_id:string;review_state:NonNullable<Paragraph['review_state']>;status:Paragraph['status'];reviewed_ids:string[];project:Project}
export function reviewedCandidates(results:Candidate[],ids:Iterable<string>){
 const reviewed=new Set(ids);return results.map(c=>reviewed.has(c.id) && ['pending','held','undone'].includes(c.status)?{...c,status:'reviewed'}:c);
}
export function reviewedState(state:AIState,ids:Iterable<string>):AIState{
 const results=reviewedCandidates(state.results,ids);
 return {...state,results,jobs:state.jobs.map(j=>({...j,unreviewed:results.filter(c=>c.job_id===j.id && ['pending','undone'].includes(c.status)).length}))};
}
export function applyReviewReceipt(book:Book,receipt:ReviewReceipt):Book{
 if(book.id!==receipt.book_id || book.edit_state.revision!==receipt.revision)throw new Error('本文が変更されています。保存済み状態を再読み込みしてください。');
 const patch=(p:Paragraph)=>p.id===receipt.paragraph_id?{...p,review_state:receipt.review_state,status:receipt.status}:p;
 return {...book,proof_score:receipt.proof_score ?? book.proof_score,project:receipt.project,chapters:book.chapters.map(c=>c.paragraphs.some(p=>p.id===receipt.paragraph_id)||c.headings.some(h=>h.id===receipt.paragraph_id)?{...c,paragraphs:c.paragraphs.map(patch),headings:c.headings.map(h=>({...h,...patch(h)}))}:c)};
}
