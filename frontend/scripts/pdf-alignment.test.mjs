import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/pdfAlignment.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
export const alignment=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const {normalizePdfText,pdfPageVariants,buildPdfTextIndex,findPdfLocation}=alignment;
const first='夜明けの山道を進む旅人は遠くに見える街の灯火を見つめていた。';
const second='静かな午後の庭で小さな鳥が歌い花びらが池の水面にゆっくり落ちた。';
const third='工場の機械は規則正しく音を立て職人たちは慎重に部品を組み立てていた。';
const makeIndex=texts=>buildPdfTextIndex(texts.map((text,i)=>({page:i+1,variants:[text]})));
const paragraph=(text,original=text,i=0)=>({id:'p'+i,text,original_text:original,sentences:[{index:0,start:0,end:text.length,text}],rubies:[]});
function target(paragraphs,i=0,overrides={}){const p=paragraphs[i],chapter={id:'c1',title:'一',paragraphs,headings:[]};return {book:{id:'b1',edit_state:{revision:0},chapters:[chapter]},chapter,paragraph:p,unit:{paragraph_id:p.id,paragraph_index:i,kind:'paragraph',sentence_index:null,text:p.text},pdfHash:'pdf1',mappings:{},...overrides};}
test('normalization handles width, spaces, newlines and punctuation without changing letter order',()=>assert.equal(normalizePdfText('ＡＢＣ　１２３\n「庭 の 鳥」。'),'ABC123庭の鳥'));
test('vertical glyph positions and small furigana produce an independent body-only reading order',()=>{
 const chars=Array.from(first);const items=chars.map((str,i)=>({str,transform:[10,0,0,10,100-Math.floor(i/12)*20,500-(i%12)*12]}));
 items.push({str:'たびびと',transform:[3,0,0,3,105,470]});items.reverse();
 const variants=pdfPageVariants(items);assert.ok(variants.includes(normalizePdfText(first)));assert.ok(variants.some(v=>v.includes('たびびと')));
});
test('selected text chooses its source page',()=>{
 const index=makeIndex([first,second,third]),result=findPdfLocation(index,target([paragraph(second)]));assert.equal(result.page,2);assert.equal(result.method,'text');
});
test('a fully rewritten paragraph can follow its immutable original text',()=>{
 const index=makeIndex([first,second,third]),result=findPdfLocation(index,target([paragraph('統計資料の分類方法を全く新しい説明へ書き換えました。',second)]));assert.equal(result.page,2);assert.equal(result.method,'original');
});
test('newly inserted text follows surrounding paragraphs instead of inventing an exact match',()=>{
 const ps=[paragraph(first,first,0),paragraph('統計資料の分類方法を全く新しい説明へ書き換えました。','',1),paragraph(third,third,2)];
 const result=findPdfLocation(makeIndex([first,second,third]),target(ps,1));assert.equal(result.page,1);assert.equal(result.method,'neighbor');
});
test('edited sentences prefer a nearby sentence over the first page of a long original paragraph',()=>{
 const p=paragraph(first+second+third),middle='統計資料の分類方法を全く新しい説明へ書き換えました。';
 p.sentences=[{index:0,text:first},{index:1,text:middle},{index:2,text:third}];p.text=first+middle+third;
 const t=target([p]);t.unit={...t.unit,kind:'sentence',sentence_index:1,text:middle};
 const result=findPdfLocation(makeIndex([first,second,third]),t);assert.equal(result.method,'neighbor');assert.ok([1,3].includes(result.page));
});
test('chapter anchors give an explicitly approximate location when all nearby text has changed',()=>{
 const ps=Array.from({length:15},(_,i)=>paragraph('完全に新規の見出しだけを挿入しました。','',i));ps[0]=paragraph(first,first,0);ps[14]=paragraph(third,third,14);
 const result=findPdfLocation(makeIndex([first,second,third]),target(ps,7));assert.equal(result.method,'chapter');assert.equal(result.page,1);
});
test('a sentence crossing PDF pages follows the page where it starts',()=>{
 const text=second+third;const index=makeIndex([first,second,third]);assert.equal(findPdfLocation(index,target([paragraph(text)])).page,2);
});
test('ambiguous repeated sentences never jump to an arbitrary page',()=>{
 const repeated='これは毎回繰り返される共通の文章です。';const index=makeIndex([first+repeated,third+repeated]);assert.equal(findPdfLocation(index,target([paragraph(repeated)])),null);
});
test('image-only PDFs and page-number-only text do not trigger automatic alignment',()=>{
 for(const values of [['','',''],['1','2','3'],['表紙','目次','図版']]){const index=makeIndex(values);assert.equal(index.usable,false);assert.equal(findPdfLocation(index,target([paragraph(second)])),null);}
});
test('registered mapping wins only for the attached PDF and a valid page',()=>{
 const index=makeIndex([first,second,third]),t=target([paragraph(second)]);t.mappings={p0:[{page:3,pdf_sha256:'pdf1'}]};assert.equal(findPdfLocation(index,t).method,'registered');assert.equal(findPdfLocation(index,t).page,3);
 t.mappings={p0:[{page:3,pdf_sha256:'old-pdf'},{page:100,pdf_sha256:'pdf1'}]};assert.equal(findPdfLocation(index,t).page,2);
});
test('OCR differences can be located without rewriting the EPUB',()=>{
 const edited=second.replace('小さな鳥','小鳥').replace('池の水面','水面');const t=target([paragraph(edited,'')]);const result=findPdfLocation(makeIndex([first,second,third]),t);assert.equal(result.page,2);assert.equal(result.method,'similar');assert.equal(t.paragraph.text,edited);
});
