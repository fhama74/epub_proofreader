import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const compiled=ts.transpileModule(await readFile(new URL('../src/reviewState.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {reviewStatus}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const paragraph={id:'p',review_state:{body:{total:2,done:1,confirmed:false,units:[true,false]},ruby:{total:1,done:0,confirmed:false,units:[false]}}};
const flag={paragraph_id:'p',target:'text',status:'pending',stale:false,original:'汽'};
test('any outstanding sentence finding is red; otherwise an unfinished sentence is yellow',()=>{
 assert.equal(reviewStatus(paragraph,[flag]).color,'red');
 assert.equal(reviewStatus(paragraph,[]).color,'yellow');
 const done={...paragraph,review_state:{...paragraph.review_state,body:{total:2,done:2,confirmed:true,units:[true,true]}}};
 assert.equal(reviewStatus(done,[]).color,'green');
 assert.equal(reviewStatus(done,[flag]).color,'red');
});
test('confirmed, stale, rejected and old long body findings cannot mark a paragraph red',()=>{
 for(const other of [{...flag,status:'reviewed'},{...flag,status:'approved'},{...flag,status:'rejected'},{...flag,stale:true},{...flag,original:'段落全体'},{...flag,original:''}])assert.equal(reviewStatus(paragraph,[other]).color,'yellow');
});
test('ruby and body review indicators are independent',()=>{
 const ruby={...flag,target:'ruby',original:'長い親文字'};
 assert.equal(reviewStatus(paragraph,[ruby]).color,'yellow');
 assert.equal(reviewStatus(paragraph,[ruby],'ruby').color,'red');
 assert.equal(reviewStatus(paragraph,[flag],'ruby').color,'yellow');
});
