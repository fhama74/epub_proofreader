import {test,expect} from '@playwright/test';
import {newProject} from './helpers';

test('review badge changes on confirmation/reset; touch ruby addition and removal preserve body',async({page})=>{
 await newProject(page);
 await page.getByLabel('次の段落・文',{exact:true}).click();
 const body=page.getByLabel('本文を編集',{exact:true});
 await expect(body).toHaveValue('今日は良い天汽だった。庭の向こうで、小さな鳥が鳴いている。');
 const text=await body.inputValue();
 await expect(page.getByLabel('段落の校閲状態：未確定',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'確認済みにする',exact:true}).click();
 await expect(page.getByLabel('段落の校閲状態：確定済み',{exact:true})).toBeVisible();
 await page.getByText('校閲状態をリセット',{exact:true}).click();
 await page.getByRole('button',{name:'未確定に戻す',exact:true}).click();
 await expect(page.getByLabel('段落の校閲状態：未確定',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'ルビを追加',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'ルビを追加',exact:true});
 await dialog.getByLabel('親文字の位置 1 今',{exact:true}).click();
 await dialog.getByLabel('親文字の位置 2 日',{exact:true}).click();
 await expect(dialog.getByLabel('追加する親文字',{exact:true})).toHaveValue('今日');
 await dialog.getByLabel('追加する読み',{exact:true}).fill('きょう');
 await dialog.getByRole('button',{name:'追加',exact:true}).click();
 await expect(dialog).toHaveCount(0);await expect(body).toHaveValue(text);
 await page.getByRole('button',{name:'ルビの訂正',exact:true}).click();
 const list=page.getByRole('dialog',{name:'ルビの訂正',exact:true});
 await expect(list.getByLabel('親文字 chapter0001-p00002 0',{exact:true})).toHaveValue('今日');
 await list.getByRole('button',{name:'ルビを削除',exact:true}).click();
 await expect(list.getByLabel('親文字 chapter0001-p00002 0',{exact:true})).toHaveCount(0);
 await page.getByLabel('ルビ一覧を閉じる',{exact:true}).click();await expect(body).toHaveValue(text);
});

test('two browsers save different paragraphs and preserve a conflicting input',async({page,browser,baseURL})=>{
 await newProject(page);const id=(await page.evaluate(()=>localStorage.getItem('lastBook')))!;
 const other=await browser.newContext({baseURL,viewport:{width:1440,height:960}});
 try{
  await other.addInitScript(id=>localStorage.setItem('lastBook',id),id);
  const second=await other.newPage();await second.goto('/');
  await expect(second.getByLabel('本文を編集',{exact:true})).toBeEnabled();
  await page.getByLabel('次の段落・文',{exact:true}).click();
  await second.getByLabel('次の段落・文',{exact:true}).click();
  await second.getByLabel('次の段落・文',{exact:true}).click();
  const firstText=page.getByLabel('本文を編集',{exact:true}),secondText=second.getByLabel('本文を編集',{exact:true});
  const a=await firstText.inputValue(),b=await secondText.inputValue();
  await firstText.fill(a+'甲。');await secondText.fill(b+'乙。');
  await page.getByRole('button',{name:'更新',exact:true}).click();
  await second.getByRole('button',{name:'更新',exact:true}).click();
  await expect(second.getByLabel('現在の本文',{exact:true})).toHaveText(b+'乙。');
  // A still holds the old third paragraph. B saves another change first.
  await page.getByLabel('次の段落・文',{exact:true}).click();
  await expect(firstText).toHaveValue(b+'乙。');
  await firstText.fill(b+'未保存。');await secondText.fill(b+'乙。追加。');
  await second.getByRole('button',{name:'更新',exact:true}).click();
  await expect(second.getByLabel('現在の本文',{exact:true})).toHaveText(b+'乙。追加。');
  await page.getByRole('button',{name:'更新',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'この段落は別のブラウザーで変更'})).toBeVisible();
  await expect(firstText).toHaveValue(b+'未保存。');
 }finally{await other.close();}
});
