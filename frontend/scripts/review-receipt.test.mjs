import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const compiled=ts.transpileModule(await readFile(new URL('../src/reviewReceipt.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {applyReviewReceipt,reviewedCandidates,reviewedState}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
test('confirmation patches one paragraph without modifying text, revision or proof units',()=>{
 const p={id:'p',text:'原文',rubies:[],status:'unchecked'};const units=[{paragraph_id:'p'}];
 const chapter={id:'c',paragraphs:[p],headings:[],proof_units:units};const other={id:'other',paragraphs:[],headings:[]};const edit_state={revision:3};const book={id:'b',chapters:[chapter,other],edit_state};
 const receipt={book_id:'b',revision:3,paragraph_id:'p',status:'human_checked',project:{version:2},review_state:{body:{confirmed:true}}};
 const next=applyReviewReceipt(book,receipt);
 assert.equal(next.chapters[0].paragraphs[0].text,'原文');assert.equal(next.chapters[0].paragraphs[0].status,'human_checked');assert.equal(p.status,'unchecked');
 assert.equal(next.edit_state,edit_state);assert.equal(next.chapters[0].proof_units,units);assert.equal(next.chapters[1],other);
 assert.throws(()=>applyReviewReceipt(book,{...receipt,revision:4}),/本文が変更/);
 assert.throws(()=>applyReviewReceipt(book,{...receipt,book_id:'other'}),/本文が変更/);
});
test('reviewed IDs clear highlights and navigation without applying any replacement',()=>{
 const flags=[{id:'a',job_id:'j',status:'pending',replacement:'訂正'},{id:'b',job_id:'j',status:'pending'},{id:'c',job_id:'j',status:'approved'}];
 const state=reviewedState({results:flags,jobs:[{id:'j',unreviewed:2}]},['a','c']);
 assert.deepEqual(state.results.map(c=>c.status),['reviewed','pending','approved']);assert.equal(state.jobs[0].unreviewed,1);
 assert.equal(state.results[0].replacement,'訂正');assert.equal(flags[0].status,'pending');
 assert.deepEqual(reviewedCandidates(state.results,['a']),state.results);
});
