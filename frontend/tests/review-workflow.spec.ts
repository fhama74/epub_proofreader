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
 await expect(body).toHaveValue('静かな午後、書物を開いて一文字ずつ確かめた。');
 await page.getByLabel('前の段落・文',{exact:true}).click();
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

test('two browsers save different paragraphs and a shared paragraph is protected by a lease',async({page,browser,baseURL})=>{
 await newProject(page);const id=(await page.evaluate(()=>localStorage.getItem('lastBook')))!;
 await page.getByLabel('次の段落・文',{exact:true}).click();
 const firstText=page.getByLabel('本文を編集',{exact:true});await expect(firstText).toHaveValue(/天汽/);
 const other=await browser.newContext({baseURL,viewport:{width:1440,height:960}});
 try{
  await other.addInitScript(id=>localStorage.setItem('lastBook',id),id);
  const second=await other.newPage();await second.goto('/');
  const secondText=second.getByLabel('本文を編集',{exact:true});
  await expect(secondText).toBeEnabled();await expect(secondText).toHaveValue(/吾輩/);
  const a=await firstText.inputValue(),b=await secondText.inputValue();
  await firstText.fill(a+'甲。');await secondText.fill(b+'乙。');
  await page.getByRole('button',{name:'更新',exact:true}).click();
  await expect(firstText).toHaveValue(/書物/);
  await second.getByRole('button',{name:'更新',exact:true}).click();
  await expect(secondText).toHaveValue(a+'甲。');
  await expect(secondText).toBeEnabled();
  const stored=await (await second.request.get('/api/books/'+id)).json();
  expect(stored.chapters[0].paragraphs[0].text).toBe(b+'乙。');
  expect(stored.chapters[0].paragraphs[1].text).toBe(a+'甲。');
  const draft=(await firstText.inputValue())+'未保存。';await firstText.fill(draft);
  await second.getByLabel('次の段落・文',{exact:true}).click();
  await expect(second.getByRole('alert').filter({hasText:'別のブラウザーで編集中'})).toBeVisible();
  await expect(secondText).toBeDisabled();
  await expect(second.getByRole('button',{name:'更新',exact:true})).toBeDisabled();
  await expect(firstText).toHaveValue(draft);
 }finally{await other.close();}
});
