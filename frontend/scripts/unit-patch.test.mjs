import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const compiled=ts.transpileModule(await readFile(new URL('../src/unitPatch.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {mergeUnitPatch}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
test('compact save refreshes only the selected paragraph and recalculates sentence navigation',()=>{
 const first={id:'p',text:'短い段落。',unit_mode:'paragraph',sentences:[{index:0,text:'短い段落。'}]},other={id:'q',text:'次の段落。',unit_mode:'paragraph',sentences:[]};
 const second={id:'other',paragraphs:[]};const book={id:'b',chapters:[{id:'c',paragraphs:[first,other],proof_units:[]},second]};
 const paragraph={...first,text:'長い文。次の文。',unit_mode:'sentence',sentences:[{index:0,text:'長い文。'},{index:1,text:'次の文。'}]};
 const updated=mergeUnitPatch(book,{kind:'unit_patch',book_id:'b',paragraph,edit_state:{revision:2},project:{version:3}});
 assert.equal(updated.chapters[0].paragraphs[0],paragraph);assert.equal(updated.chapters[0].paragraphs[1],other);assert.equal(updated.chapters[1],second);
 assert.deepEqual(updated.chapters[0].proof_units.map(u=>[u.paragraph_id,u.sentence_index]),[['p',0],['p',1],['q',null]]);
 assert.equal(updated.chapters[0].long_paragraph_count,1);assert.equal(book.chapters[0].paragraphs[0],first);
 assert.equal(updated.edit_state.revision,2);
});
test('a compact response cannot update another project',()=>{
 const patch={kind:'unit_patch',book_id:'b'};
 assert.throws(()=>mergeUnitPatch(null,patch),/プロジェクト/);
 assert.throws(()=>mergeUnitPatch({id:'other'},patch),/プロジェクト/);
 const full={id:'b',chapters:[]};assert.equal(mergeUnitPatch(null,full),full);
});
