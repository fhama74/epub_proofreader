import {test,expect} from '@playwright/test';
import {newProject} from './helpers';

test('desktop header combines brand, project identity and view controls in one row',async({page})=>{
 await newProject(page);
 const header=page.locator('header.workspace-header');
 await expect(header.getByRole('heading',{name:'EPUB Proofreader',exact:true})).toBeVisible();
 await expect(header.locator('.project-summary')).toContainText('book.epub');
 await expect(header.locator('.project-date')).toBeVisible();
 await expect(header.locator('.project-version')).toHaveText('未発行');
 await expect(page.locator('.bookbar')).toHaveCount(0);
 expect(await header.evaluate(el=>el.getBoundingClientRect().height)).toBeLessThanOrEqual(50);
});

for(const [file,vertical] of [['book.epub',true],['horizontal.epub',false]] as const){
 test(`${vertical?'vertical':'horizontal'} proof navigation follows reading direction`,async({page})=>{
  await newProject(page,file);
  const nav=page.getByRole('navigation',{name:'校正箇所の移動',exact:true});
  const labels=await nav.getByRole('button').evaluateAll(elements=>elements.map(el=>el.getAttribute('aria-label')));
  expect(labels).toEqual(vertical?['次のAI検知','次の段落・文','前の段落・文','前のAI検知']:['前のAI検知','前の段落・文','次の段落・文','次のAI検知']);
  await nav.getByRole('button',{name:'次の段落・文',exact:true}).click();
  await expect(page.getByLabel('現在の本文',{exact:true})).toContainText(vertical?'天汽':'これは第1文です');
  await nav.getByRole('button',{name:'前の段落・文',exact:true}).click();
  await expect(page.getByLabel('現在の本文',{exact:true})).toHaveText('吾輩は猫である。名前はまだない。');
  const actions=page.getByRole('region',{name:'章・段落処理',exact:true});
  for(const name of ['前に章を追加','後に章を追加','前に段落を追加','後に段落を追加'])await expect(actions.getByRole('button',{name,exact:true})).toBeVisible();
 });
}
