import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/pdfGesture.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {pinchZoom,pdfOutputRatio}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('pinch changes the actual fit scale in both directions and respects persistence bounds',()=>{
 assert.equal(pinchZoom(.6,200,100),1.2);assert.equal(pinchZoom(1.2,50,100),.6);assert.equal(pinchZoom(4,200,100),5);assert.equal(pinchZoom(.2,1,100),.1);assert.ok(Number.isFinite(pinchZoom(1,10,0)));
});
test('retina canvas buffers stay below Safari limits without changing CSS zoom',()=>{
 for(const [w,h,d] of [[500,800,2],[3000,5000,3],[12000,2000,2]]){const r=pdfOutputRatio(w,h,d);assert.ok(w*r<=8192);assert.ok(h*r<=8192);assert.ok(w*h*r*r<=16000000.01);assert.ok(r<=d);}assert.equal(pdfOutputRatio(500,800,2),2);
});
