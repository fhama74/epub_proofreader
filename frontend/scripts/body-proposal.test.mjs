import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const compiled=ts.transpileModule(await readFile(new URL('../src/bodyProposal.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {bodyProposal}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const finding={target:'text',start:11,end:12,original:'汽',replacement:'気',match_count:1,status:'pending',stale:false};
test('one occurrence prefills a draft with Unicode/sentence offsets',()=>assert.equal(bodyProposal('天汽。',10,finding),'天気。'));
test('multiple matches never prefill even if a malformed candidate has a replacement',()=>assert.equal(bodyProposal('天汽と天汽。',10,{...finding,match_count:2}),null));
test('detection without proposal, stale and decided results leave the editor unchanged',()=>{
 for(const c of [{...finding,replacement:null},{...finding,stale:true},{...finding,status:'reviewed'},{...finding,start:0,end:1}])assert.equal(bodyProposal('天汽。',10,c),null);
});
test('deletion drafts affect just one verified occurrence',()=>assert.equal(bodyProposal('天汽。',10,{...finding,replacement:''}),'天。'));
