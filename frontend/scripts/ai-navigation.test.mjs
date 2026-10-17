import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/aiTypes.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {navigationCandidates:filter,neighboringCandidate:next}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const candidates=[{id:'a',paragraph_id:'p1',status:'approved'},{id:'b',paragraph_id:'p1',status:'pending'},{id:'c',paragraph_id:'p1',status:'pending'},{id:'d',paragraph_id:'p2',status:'held'},{id:'e',paragraph_id:'p3',status:'rejected'}].map(c=>({...c,target:'text'}));
test('pending navigation visits individual candidates in the same paragraph',()=>{const list=filter(candidates,'pending');assert.deepEqual(list.map(c=>c.id),['b','c']);assert.equal(next(list,null,1).id,'b');assert.equal(next(list,'b',1).id,'c');assert.equal(next(list,'c',-1).id,'b');});
test('pending plus held and all preserve previous decisions',()=>{assert.deepEqual(filter(candidates,'held').map(c=>c.id),['b','c','d']);assert.deepEqual(filter(candidates,'all').map(c=>c.id),['b','c','d']);});
test('empty lists and either boundary have no target',()=>{assert.equal(next([],null,1),null);const list=filter(candidates,'pending');assert.equal(next(list,'b',-1),null);assert.equal(next(list,'c',1),null);assert.equal(next(list,null,-1).id,'c');});

test('body navigation excludes ruby candidates even in all-results mode',()=>{assert.deepEqual(filter([...candidates,{id:'ruby',paragraph_id:'p1',target:'ruby',status:'pending'}],'all').map(c=>c.id),['b','c','d']);});

test('confirming the middle result keeps navigation relative to its old position',()=>{const all=[{id:'a',target:'text',status:'pending'},{id:'b',target:'text',status:'reviewed'},{id:'c',target:'text',status:'pending'}];const list=filter(all,'all');assert.equal(next(list,'b',1,all).id,'c');assert.equal(next(list,'b',-1,all).id,'a');});
test('approved, reviewed, rejected and superseded findings never enter proof navigation',()=>{for(const status of ['approved','reviewed','rejected','superseded'])assert.equal(filter([{id:'x',target:'text',status}],'all').length,0);});

const {nextProofCandidate:afterProof}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const proofBook={id:'book',chapters:[{id:'ch1',headings:[{id:'heading',next_paragraph_index:0}],paragraphs:[{id:'p1',sentences:[{end:20},{end:40}]},{id:'p2',sentences:[]}]},{id:'ch2',paragraphs:[{id:'p3',sentences:[]}]}]};
const finding=(id,pid,start,status='pending',extra={})=>({id,book_id:'book',paragraph_id:pid,start,target:'text',status,...extra});
test('completion uses fresh finding order and skips confirmed, ruby and stale candidates',()=>{
 const rows=[finding('next','p1',15),finding('done','p1',2,'approved'),finding('old','p1',10,'pending',{stale:true}),finding('ruby','p1',12,'pending',{target:'ruby'}),finding('later','p2',0)];
 assert.equal(afterProof(proofBook,rows,{paragraphId:'p1',candidateId:'done'}).id,'next');
});
test('manual paragraph and sentence confirmation advance from the confirmed scope',()=>{
 const rows=[finding('earlier','p1',2),finding('sentence2','p1',25),finding('nextParagraph','p2',0)];
 assert.equal(afterProof(proofBook,rows,{paragraphId:'p1',sentenceIndex:0}).id,'sentence2');
 assert.equal(afterProof(proofBook,rows,{paragraphId:'p1'}).id,'nextParagraph');
 assert.equal(afterProof(proofBook,rows,{paragraphId:'heading'}).id,'earlier');
});
test('completion crosses chapters and stays put at the end instead of wrapping',()=>{
 const rows=[finding('done','p2',0,'reviewed'),finding('last','p3',0)];
 assert.equal(afterProof(proofBook,rows,{paragraphId:'p2',candidateId:'done'}).id,'last');
 assert.equal(afterProof(proofBook,rows,{paragraphId:'p3',candidateId:'last'}),null);
 assert.equal(afterProof(proofBook,[finding('foreign','p2',0,'pending',{book_id:'other'})],{paragraphId:'p1'}),null);
});
