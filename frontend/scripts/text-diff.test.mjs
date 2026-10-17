import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/textDiff.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {textDiff}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const changed=parts=>parts.filter(p=>p.changed).map(p=>p.text).join('');
test('Japanese correction colors only the substituted characters on both sides',()=>{
 const d=textDiff('今日は良い天汽だった。','今日は良い天気だった。');assert.equal(changed(d.before),'汽');assert.equal(changed(d.after),'気');
});
test('insertions, deletions, emoji, separated changes and newlines preserve exact text',()=>{
 for(const [a,b] of [['本文。','本文を追加。'],['追加した本文。','本文。'],['𠮷野😀。猫。','吉野😺。犬。'],['一。\n二。','一。\n新しい二。'],['','追加'],['削除',''],['同じ','同じ']]){
  const d=textDiff(a,b);assert.equal(d.before.map(p=>p.text).join(''),a);assert.equal(d.after.map(p=>p.text).join(''),b);
  assert.equal(d.before.filter(p=>!p.changed).map(p=>p.text).join(''),d.after.filter(p=>!p.changed).map(p=>p.text).join(''));
 }
 const d=textDiff('猫。長い文。犬。','鳥。長い文。馬。');assert.equal(changed(d.before),'猫犬');assert.equal(changed(d.after),'鳥馬');
});
test('long text with distant changes keeps the unchanged middle uncolored',()=>{
 const middle='本文を確認。'.repeat(2500);const d=textDiff('猫'+middle+'犬','鳥'+middle+'馬');assert.equal(changed(d.before),'猫犬');assert.equal(changed(d.after),'鳥馬');
});
test('bounded diff remains lossless when an entire large paragraph is replaced',()=>{
 const a='あ'.repeat(20000),b='い'.repeat(20000),d=textDiff(a,b);assert.equal(d.before.map(p=>p.text).join(''),a);assert.equal(d.after.map(p=>p.text).join(''),b);
});
test('deletion-only edit marks the removed original text and no edited text',()=>{
 const d=textDiff('今日は良い天汽だった。庭の向こうで、小さな鳥が鳴いている。','今日は良い天汽だった。小さな鳥が鳴いている。');
 assert.equal(changed(d.before),'庭の向こうで、');assert.equal(changed(d.after),'');
});
