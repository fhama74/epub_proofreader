import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const compiled=ts.transpileModule(await readFile(new URL('../src/apiClient.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {api,APIError}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
async function withFetch(fetch,action){const previous=globalThis.fetch;globalThis.fetch=fetch;try{await action();}finally{globalThis.fetch=previous;}}
test('non-JSON server errors produce an HTTP message instead of Safari SyntaxError',async()=>{
 await withFetch(async()=>new Response('private server stack',{status:500}),async()=>{
  await assert.rejects(api('/api/example','POST',{}),e=>e instanceof APIError && e.status===500 && e.message.includes('HTTP 500') && !e.message.includes('private'));
 });
});
test('busy database JSON message is preserved and requests are not retried automatically',async()=>{
 let calls=0;
 await withFetch(async()=>{calls++;return new Response(JSON.stringify({detail:'保存処理が混み合っています。'}),{status:503});},async()=>{
  await assert.rejects(api('/api/example','POST',{}),e=>e instanceof APIError && e.status===503 && e.message==='保存処理が混み合っています。');
 });
 assert.equal(calls,1);
});
test('malformed success and network failures have actionable messages',async()=>{
 await withFetch(async()=>new Response('not JSON'),async()=>{
  await assert.rejects(api('/api/example'),e=>e instanceof APIError && e.message.includes('返答を読み込めません'));
 });
 await withFetch(async()=>{throw new TypeError('private network details');},async()=>{
  await assert.rejects(api('/api/example'),e=>e instanceof APIError && e.status===0 && e.message.includes('接続できません') && !e.message.includes('private'));
 });
});
test('successful JSON and existing conflict status remain unchanged',async()=>{
 await withFetch(async()=>new Response('{"ok":true}'),async()=>assert.deepEqual(await api('/api/example'),{ok:true}));
 await withFetch(async()=>new Response('{"detail":"入力は保持されています"}',{status:409}),async()=>{
  await assert.rejects(api('/api/example'),e=>e instanceof APIError && e.status===409 && e.message==='入力は保持されています');
 });
});
