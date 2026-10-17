import type {ProofUnit} from './types';
/** Keep the paragraph when edits change its sentence mode or sentence count. */
export function resolveProofUnit(units:ProofUnit[],paragraphId?:string,sentenceIndex?:number|null):ProofUnit|undefined{
 return units.find(u=>u.paragraph_id===paragraphId && (u.kind==='paragraph' || u.sentence_index===sentenceIndex))
  || units.find(u=>u.paragraph_id===paragraphId) || units[0];
}
