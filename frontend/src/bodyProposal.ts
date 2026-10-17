import type {Candidate} from './aiTypes';
/** Prefill a single verified occurrence; repeated occurrences remain manual. */
export function bodyProposal(text:string,offset:number,candidate:Candidate|null):string|null{
 const c=candidate;
 if(!c || c.target!=='text' || c.stale || (c.match_count??1)!==1 || c.replacement===null || !['pending','held'].includes(c.status))return null;
 const chars=Array.from(text),a=c.start-offset,b=c.end-offset;
 if(a<0 || b>chars.length || a>=b || chars.slice(a,b).join('')!==c.original)return null;
 return chars.slice(0,a).join('')+c.replacement+chars.slice(b).join('');
}
