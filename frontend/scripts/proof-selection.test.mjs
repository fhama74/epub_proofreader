import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/proofSelection.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {resolveProofUnit,nextProofLocation}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
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
const chapter=(id,units,headings=[])=>({id,proof_units:units,paragraphs:[...new Set(units.map(u=>u.paragraph_id))].map(id=>({id})),headings});
test('completion follows text order, includes confirmed paragraphs and crosses empty chapters',()=>{
 const book={chapters:[chapter('a',[paragraph('first'),paragraph('confirmed')]),chapter('empty',[]),chapter('b',[paragraph('last')])]};
 assert.equal(nextProofLocation(book,{paragraphId:'first'}).unit.paragraph_id,'confirmed');
 assert.equal(nextProofLocation(book,{paragraphId:'confirmed'}).chapterId,'b');
 assert.equal(nextProofLocation(book,{paragraphId:'last'}),null);
 assert.equal(nextProofLocation(book,{paragraphId:'missing'}),null);
});
test('whole-paragraph completion skips all its newly created sentence units',()=>{
 const book={chapters:[chapter('a',[sentence('edited',0),sentence('edited',1),paragraph('next')])]};
 assert.equal(nextProofLocation(book,{paragraphId:'edited'}).unit.paragraph_id,'next');
 assert.equal(nextProofLocation(book,{paragraphId:'edited',sentenceIndex:0}).unit.sentence_index,1);
 assert.equal(nextProofLocation(book,{paragraphId:'edited',sentenceIndex:1}).unit.paragraph_id,'next');
});
test('shortened or removed sentences continue after the paragraph and headings lead into their body',()=>{
 const units=[{...paragraph('edited'),paragraph_index:0},{...paragraph('next'),paragraph_index:1}];
 const book={chapters:[chapter('a',units,[{id:'title',next_paragraph_index:0}])]};
 assert.equal(nextProofLocation(book,{paragraphId:'edited',sentenceIndex:8}).unit.paragraph_id,'next');
 assert.equal(nextProofLocation(book,{paragraphId:'title'}).unit.paragraph_id,'edited');
});
