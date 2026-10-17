import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/requestId.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {createRequestId}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
test('HTTP Safari can create request IDs with getRandomValues and no randomUUID',()=>{
 let sequence=0;const crypto={getRandomValues(bytes){bytes.fill(++sequence);return bytes;}};
 const a=createRequestId(crypto),b=createRequestId(crypto);assert.match(a,uuid);assert.match(b,uuid);assert.notEqual(a,b);
});
test('native method keeps its receiver and minimal browsers still work',()=>{
 const crypto={randomUUID(){assert.equal(this,crypto);return 'native-id';}};assert.equal(createRequestId(crypto),'native-id');
 const values=new Set(Array.from({length:100},()=>createRequestId({})));assert.equal(values.size,100);for(const id of values)assert.match(id,uuid);
});
