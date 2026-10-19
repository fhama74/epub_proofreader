import {test,expect} from '@playwright/test';
import {newProject,menuAction} from './helpers';

for(const kind of ['章','段落'])for(const position of ['前','後']){
 test(`insert ${kind} ${position} of the displayed sentence as one saved operation`,async({page})=>{
  await newProject(page,'navigation.epub');
  await page.getByLabel('次の段落・文',{exact:true}).click();await page.getByLabel('次の段落・文',{exact:true}).click();
  await expect(page.locator('.proof-position')).toContainText('文 2 / 40');
  await expect(page.getByRole('region',{name:'章・段落処理',exact:true}).getByRole('button')).toHaveCount(8);
  await expect(page.locator('.inline-update').getByRole('button',{name:'カーソル位置で段落を二つに分ける',exact:true})).toBeVisible();
  await page.getByRole('button',{name:`${position}に${kind}を追加`,exact:true}).click();
  const endpoint=kind==='章'?'/chapters/split':'/structure';
  const saved=page.waitForResponse(r=>r.url().endsWith(endpoint) && r.request().method()==='POST');
  if(kind==='章'){
   await page.getByLabel('新しい章名',{exact:true}).fill('一');await page.getByLabel('章のレベル',{exact:true}).selectOption('2');
   await page.getByRole('button',{name:'章を作成',exact:true}).click();
  }else{
   await page.getByLabel('挿入する本文',{exact:true}).fill('追加した本文。');
   await page.getByRole('button',{name:'段落を挿入して再計算',exact:true}).click();
  }
  const response=await saved;expect(response.status()).toBe(200);
  expect(response.request().postDataJSON()).toMatchObject({sentence_index:1,position:position==='前'?'before':'after'});
  const book=await response.json();expect(book.edit_state.edit_count).toBe(1);
  if(kind==='章'){expect(book.chapters).toHaveLength(3);expect(book.chapters[1].heading_level).toBe(2);}
  else{expect(book.chapters[0].paragraph_count).toBe(5);await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('追加した本文。');}
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload();await expect(page.getByLabel('章の選択',{exact:true}).locator('option')).toHaveCount(kind==='章'?3:2);
  if(kind==='段落')await expect(page.locator('.proof-position')).toContainText('/ 5');
 });
}

test('forward merge from a sentence consumes both whole paragraphs',async({page})=>{
 await newProject(page,'navigation.epub');await page.getByLabel('次の段落・文',{exact:true}).click();await page.getByLabel('次の段落・文',{exact:true}).click();
 await page.getByRole('button',{name:'後ろの段落に統合',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'段落の挿入・結合',exact:true});await expect(dialog).toContainText('段落全体を統合');
 const saved=page.waitForResponse(r=>r.url().endsWith('/structure') && r.request().method()==='POST');
 await dialog.getByRole('button',{name:'段落を統合して再計算',exact:true}).click();
 const response=await saved;expect(response.request().postDataJSON().sentence_index).toBeUndefined();
 const book=await response.json();expect(book.chapters[0].paragraph_count).toBe(2);
 expect(book.chapters[0].paragraphs[1].text).toContain('庭の景色');
});
