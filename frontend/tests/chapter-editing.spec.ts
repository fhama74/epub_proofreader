import {test,expect} from '@playwright/test';
import {newProject,menuAction} from './helpers';

test('insert after a heading, split a chapter and persist the chapter creation',async({page})=>{
 await newProject(page);
 await page.frameLocator('iframe').getByText('第一章　午後の庭',{exact:true}).click();
 await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('第一章　午後の庭');

 const insert=page.getByRole('button',{name:'後に段落を追加',exact:true});await expect(insert).toBeEnabled();await insert.click();
 const dialog=page.getByRole('dialog',{name:'段落の挿入・結合',exact:true});
 await dialog.getByLabel('挿入する本文',{exact:true}).fill('追加した段落。');
 await dialog.getByRole('button',{name:'段落を挿入して再計算',exact:true}).click();
 await expect(dialog).toHaveCount(0);await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('追加した段落。');
 await page.getByRole('button',{name:'前に章を追加',exact:true}).click();
 const chapter=page.getByRole('dialog',{name:'新しい章を作成',exact:true});await chapter.getByLabel('新しい章名',{exact:true}).fill('追加した章');
 await expect(chapter.getByLabel('章のレベル',{exact:true}).locator('option')).toHaveCount(6);
 await chapter.getByLabel('章のレベル',{exact:true}).selectOption('2');
 const saved=page.waitForResponse(r=>r.url().endsWith('/chapters/split') && r.request().method()==='POST');
 await chapter.getByRole('button',{name:'章を作成',exact:true}).click();await expect(chapter).toHaveCount(0);
 expect((await (await saved).json()).chapters[1].heading_level).toBe(2);
 await expect(page.getByLabel('章の選択',{exact:true})).toHaveValue('1');
 await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('追加した章');
 await expect(page.getByLabel('章の選択',{exact:true}).locator('option')).toHaveCount(3);
 await page.reload();await expect(page.getByLabel('章の選択',{exact:true}).locator('option')).toHaveCount(3);
});

test('a non-JSON error during compact update stays actionable and preserves the draft',async({page})=>{
 await newProject(page);await page.getByLabel('次の段落・文',{exact:true}).click();
 const body=page.getByLabel('本文を編集',{exact:true});await expect(body).toHaveValue('今日は良い天汽だった。庭の向こうで、小さな鳥が鳴いている。');
 await page.route('**/paragraphs/*',route=>route.request().method()==='PATCH'?route.fulfill({status:502,contentType:'text/html',body:'<html>private proxy failure</html>'}):route.continue());
 await body.fill('今日は良い天気だった。庭の向こうで、小さな鳥が鳴いている。');await page.getByRole('button',{name:'更新',exact:true}).click();
 await expect(page.getByRole('alert').filter({hasText:'HTTP 502'})).toBeVisible();
 await expect(page.getByText('private proxy failure',{exact:false})).toHaveCount(0);
 await expect(body).toHaveValue('今日は良い天気だった。庭の向こうで、小さな鳥が鳴いている。');
});
