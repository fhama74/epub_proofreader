import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
async function load(name){
 let compiled=ts.transpileModule(await readFile(new URL('../src/'+name,import.meta.url),'utf8'),{fileName:name,compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 compiled=compiled.replaceAll('"react/jsx-runtime"',JSON.stringify(import.meta.resolve('react/jsx-runtime')));
 return import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
}
const {chapterLabel}=await load('chapterLabel.ts');
const {default:ProofScore}=await load('ProofScore.tsx');
const {mergeUnitPatch}=await load('unitPatch.ts');
const {applyReviewReceipt}=await load('reviewReceipt.ts');
test('h1 through h6 get native-select-safe full-width indentation',()=>{
 for(let level=1;level<=6;level++)assert.equal(chapterLabel({title:'章名',heading_level:level}),'\u3000'.repeat(level-1)+'章名');
 assert.equal(chapterLabel({title:'未指定'}),'未指定');
});
test('progress renders the server score and distinct AI and human counts',()=>{
 const value={book_id:'b',version:1,total:20,reviewed:10,ai_completed:true,ai_points:50,review_points:25,score:75};
 const html=renderToStaticMarkup(React.createElement(ProofScore,{value}));
 assert.match(html,/75 \/ 100/);assert.match(html,/確認 10\/20/);assert.match(html,/書籍全体の検査完了/);
 assert.equal(renderToStaticMarkup(React.createElement(ProofScore,{})),'');
});
test('compact updates and confirmation receipts immediately replace cached progress',()=>{
 const old={score:0},next={score:6.2};const p={id:'p',unit_mode:'paragraph',text:'本文',sentences:[]};
 const book={id:'b',edit_state:{revision:1},proof_score:old,chapters:[{id:'c',paragraphs:[p],headings:[],proof_units:[]}]};
 const changed=mergeUnitPatch(book,{kind:'unit_patch',book_id:'b',paragraph:p,edit_state:{revision:2},proof_score:next});
 assert.equal(changed.proof_score,next);
 const reviewed=applyReviewReceipt(book,{book_id:'b',revision:1,paragraph_id:'p',status:'human_checked',review_state:{},proof_score:next});
 assert.equal(reviewed.proof_score,next);assert.equal(book.proof_score,old);
});
