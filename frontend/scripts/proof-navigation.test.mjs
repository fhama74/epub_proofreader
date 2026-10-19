import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
let compiled=ts.transpileModule(await readFile(new URL('../src/ProofNavigation.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
compiled=compiled.replaceAll('"react/jsx-runtime"',JSON.stringify(import.meta.resolve('react/jsx-runtime')));
const {default:Navigation}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
for(const rtl of [false,true])test(`${rtl?'vertical':'horizontal'} navigation order, arrows, actions and boundary states agree`,()=>{
 const calls=[];const props={rightToLeft:rtl,previous:false,next:true,previousAI:false,nextAI:true,onPrevious:()=>calls.push('previous'),onNext:()=>calls.push('next'),onPreviousAI:()=>calls.push('previous-ai'),onNextAI:()=>calls.push('next-ai')};
 const tree=Navigation(props),buttons=tree.props.children;
 const expected=rtl?['次のAI検知','次の段落・文','前の段落・文','前のAI検知']:['前のAI検知','前の段落・文','次の段落・文','次のAI検知'];
 assert.deepEqual(buttons.map(b=>b.props['aria-label']),expected);
 for(const b of buttons){
  const back=b.props['aria-label'].startsWith('前');
  assert.equal(b.props.disabled,back);b.props.onClick();
 }
 assert.deepEqual(calls,rtl?['next-ai','next','previous','previous-ai']:['previous-ai','previous','next','next-ai']);
 const html=renderToStaticMarkup(React.createElement(Navigation,props));
 assert.match(html,rtl?/◀ 次へ/:/次へ ▶/);
 assert.match(html,rtl?/前へ ▶/:/◀ 前へ/);
});
