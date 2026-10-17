import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const compiled=ts.transpileModule(readFileSync(new URL('../src/aiTextMarks.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replaceAll('export function','function');
test('AI text marks include ruby bases, exclude readings, and clear without changing text',async({page})=>{
 await page.setContent(`<style>body{color:rgb(36,52,45)}.ai-unreviewed-text{color:rgb(180,49,49)}</style><p>その<ruby>唄<rt>ころ</rt></ruby>の僕。</p><script>${compiled};markAIText(document.querySelector('p'),[{start:0,end:6,original:'その唄の僕。'}]);</script>`);
 await expect(page.locator('ruby span')).toHaveCSS('color','rgb(180, 49, 49)');
 await expect(page.locator('rt')).toHaveCSS('color','rgb(36, 52, 45)');
 await page.addScriptTag({content:'clearAITextMarks(document);'});
 await expect(page.locator('[data-ai-text-mark]')).toHaveCount(0);
 await expect(page.locator('p')).toHaveText('その唄ころの僕。');
});
test('mark only verified, merged Unicode ranges and preserve ruby markup',async({page})=>{
 await page.setContent(`<p>😀天汽と<ruby>天汽<rt>てんき</rt></ruby>。</p><script>${compiled};markAIText(document.querySelector('p'),[{start:1,end:3,original:'天汽'},{start:2,end:3,original:'汽'},{start:5,end:6,original:'汽'},{start:0,end:1,original:'不一致'}]);</script>`);
 await expect(page.locator('[data-ai-text-mark]')).toHaveText(['天汽','汽']);
 await expect(page.locator('ruby')).toHaveCount(1);
 await expect(page.locator('rt')).toHaveText('てんき');
});
