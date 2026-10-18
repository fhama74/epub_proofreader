import type {Book,Paragraph,Project,ProofUnit,ProofScore} from './types';
export interface UnitPatch {kind:'unit_patch';proof_score?:ProofScore;book_id:string;paragraph:Paragraph;project:Project;edit_state:Book['edit_state']}
export function mergeUnitPatch(current:Book|null,response:Book|UnitPatch):Book{
 if(!('kind' in response) || response.kind!=='unit_patch')return response as Book;
 if(!current || current.id!==response.book_id)throw new Error('更新先のプロジェクトが変わりました。再読み込みしてください。');
 const paragraph=response.paragraph;
 const chapters=current.chapters.map(c=>{
  if(!c.paragraphs.some(p=>p.id===paragraph.id))return c;
  const paragraphs=c.paragraphs.map(p=>p.id===paragraph.id?paragraph:p);
  const proof_units=paragraphs.flatMap<ProofUnit>((p,i)=>p.unit_mode==='sentence'?p.sentences.map(s=>({paragraph_id:p.id,paragraph_index:i,kind:'sentence',sentence_index:s.index,text:s.text})):[{paragraph_id:p.id,paragraph_index:i,kind:'paragraph',sentence_index:null,text:p.text}]);
  return {...c,paragraphs,proof_units,sentence_count:paragraphs.reduce((n,p)=>n+p.sentences.length,0),long_paragraph_count:paragraphs.filter(p=>p.unit_mode==='sentence').length};
 });
 return {...current,chapters,project:response.project,edit_state:response.edit_state,proof_score:response.proof_score ?? current.proof_score};
}
