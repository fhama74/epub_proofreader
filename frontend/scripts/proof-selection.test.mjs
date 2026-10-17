import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/proofSelection.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {resolveProofUnit}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const paragraph=id=>({paragraph_id:id,kind:'paragraph',sentence_index:null});
const sentence=(id,n)=>({paragraph_id:id,kind:'sentence',sentence_index:n});
test('crossing 300 characters keeps the edited paragraph rather than restarting the chapter',()=>{
 const units=[paragraph('first'),sentence('edited',0),sentence('edited',1)];assert.equal(resolveProofUnit(units,'edited',null),units[1]);
});
test('shortening a long paragraph returns to the same paragraph',()=>{
 const units=[paragraph('first'),paragraph('edited')];assert.equal(resolveProofUnit(units,'edited',5),units[1]);
});
test('existing sentences keep their index while a removed index falls back within its paragraph',()=>{
 const units=[paragraph('first'),sentence('edited',0),sentence('edited',1)];assert.equal(resolveProofUnit(units,'edited',1),units[2]);assert.equal(resolveProofUnit(units,'edited',10),units[1]);
});
test('missing selections and empty chapters have safe fallbacks',()=>{
 const units=[paragraph('first')];assert.equal(resolveProofUnit(units,'removed',0),units[0]);assert.equal(resolveProofUnit([],undefined),undefined);
});
