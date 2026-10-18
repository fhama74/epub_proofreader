import type {Book} from './types';
export interface Engine {batch_paragraphs?:number;id:string;name:string;provider:'ollama'|'gemini'|'anthropic'|'openai';url:string;model:string;is_default:boolean;has_api_key:boolean;input_price:number|null;output_price:number|null;chunk_chars:number;max_output_tokens:number;visibility:'private'|'shared'}
export interface Candidate {match_count?:number;suggested_replacement?:string|null;book_id:string;id:string;job_id:string;paragraph_id:string;chapter_id:string;engine_id:string;engine_name:string;model_name:string;target:'text'|'ruby';start:number;end:number;original:string;replacement:string|null;reason:string;category:string;confidence:number;status:string;stale:boolean;base_after?:string|null;ruby_index?:number;query_type?:'body'|'ruby';proposal_note?:string|null;reading_after?:string|null;ruby_before?:{base:string;reading:string}}
export interface Job {diagnostic_count?:number;consecutive_failures?:number;stop_reason?:string|null;id:string;status:string;scope:string;created_at:string;finished_at:string|null;total:number;done:number;failed:number;candidates:number;unreviewed:number;input_tokens:number;output_tokens:number;cost:number|null;error:string|null;config:Engine;errors:{paragraph_id:string;error:string}[]}
export interface AIState {proof_score?:import("./types").ProofScore;cleared_count?:number;jobs:Job[];results:Candidate[]}
export const statusNames:Record<string,string>={archived:'バックアップから復元（記録のみ）',reviewed:'確認済み',pending:'未確認',approved:'承認',rejected:'却下',held:'保留',undone:'Undo済み',superseded:'履歴変更済み',queued:'待機',running:'実行中',pause_requested:'段落終了後に停止',paused:'一時停止',interrupted:'再開待ち',budget_paused:'料金上限で停止',cancelled:'中止',completed:'完了',completed_with_errors:'一部失敗'};
export const categories:Record<string,string>={kanji:'漢字',kana:'仮名',missing:'脱字',extra:'余分な文字',punctuation:'句読点',page_contamination:'ページ番号混入',header_contamination:'柱の混入',ruby:'ルビ',unnatural:'不自然な文字列'};
export function navigationCandidates(results:Candidate[],filter:string){return results.filter(r=>r.target==='text' && ['pending','undone',...(filter==='held'||filter==='all'?['held']:[])].includes(r.status));}
export function neighboringCandidate(results:Candidate[],selected:string|null,delta:number,ordered:Candidate[]=results,paragraphId?:string){
 const at=results.findIndex(c=>c.id===selected);if(at>=0)return results[at+delta] || null;
 const anchor=ordered.findIndex(c=>c.id===selected);
 if(anchor>=0){const allowed=new Set(results.map(c=>c.id));for(let i=anchor+delta;i>=0 && i<ordered.length;i+=delta){if(allowed.has(ordered[i].id))return ordered[i];}return null;}
 const paragraph=ordered.findIndex(c=>c.paragraph_id===paragraphId);
 if(paragraph>=0){const allowed=new Set(results.map(c=>c.id));const start=delta>0?paragraph:ordered.reduce((last,c,i)=>c.paragraph_id===paragraphId?i:last,paragraph);for(let i=start;i>=0 && i<ordered.length;i+=delta){if(allowed.has(ordered[i].id))return ordered[i];}return null;}
 return results[delta>0?0:results.length-1] || null;
}

/** Continue after the completed finding using fresh, server-owned positions. */
export function nextProofCandidate(book:Book,results:Candidate[],source:{paragraphId:string;candidateId?:string;sentenceIndex?:number}):Candidate|null{
 const positions=new Map<string,number>();let base=0;
 for(const ch of book.chapters){ch.paragraphs.forEach((p,i)=>positions.set(p.id,base+i));for(const h of ch.headings || [])positions.set(h.id,base+h.next_paragraph_index-.5);base+=ch.paragraphs.length+1;}
 const ordered=results.filter(c=>c.book_id===book.id && positions.has(c.paragraph_id)).sort((a,b)=>positions.get(a.paragraph_id)!-positions.get(b.paragraph_id)! || a.start-b.start || a.id.localeCompare(b.id));
 const allowed=new Set(navigationCandidates(ordered,'held').filter(c=>!c.stale).map(c=>c.id));
 const anchor=ordered.findIndex(c=>c.id===source.candidateId);
 if(anchor>=0){for(const c of ordered.slice(anchor+1))if(allowed.has(c.id))return c;return null;}
 const position=positions.get(source.paragraphId);if(position===undefined)return null;
 const p=book.chapters.flatMap(ch=>ch.paragraphs).find(p=>p.id===source.paragraphId);
 const end=source.sentenceIndex===undefined?Infinity:p?.sentences[source.sentenceIndex]?.end??Infinity;
 return ordered.find(c=>allowed.has(c.id) && (positions.get(c.paragraph_id)!>position || c.paragraph_id===source.paragraphId && c.start>=end)) || null;
}
