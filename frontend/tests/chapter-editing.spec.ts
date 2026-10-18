import {test,expect} from '@playwright/test';
import {newProject,menuAction} from './helpers';

test('insert after a heading, split a chapter and undo the chapter creation',async({page})=>{
 await newProject(page);
 await page.frameLocator('iframe').getByText('第一章　午後の庭',{exact:true}).click();
 await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('第一章　午後の庭');
 await page.getByText('段落・原本との対応',{exact:true}).click();
 const insert=page.getByRole('button',{name:'欠けた本文を段落として追加',exact:true});await expect(insert).toBeEnabled();await insert.click();
 const dialog=page.getByRole('dialog',{name:'段落の挿入・結合',exact:true});
 await dialog.getByLabel('挿入する本文',{exact:true}).fill('追加した段落。');
 await dialog.getByRole('button',{name:'段落を挿入して再計算',exact:true}).click();
 await expect(dialog).toHaveCount(0);await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('追加した段落。');
 await page.getByRole('button',{name:'この位置から新しい章にする',exact:true}).click();
 const chapter=page.getByRole('dialog',{name:'新しい章を作成',exact:true});await chapter.getByLabel('新しい章名',{exact:true}).fill('追加した章');
 await chapter.getByRole('button',{name:'章を作成',exact:true}).click();await expect(chapter).toHaveCount(0);
 await expect(page.getByLabel('章の選択',{exact:true})).toHaveValue('1');
 await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('追加した段落。');
 await expect(page.getByLabel('章の選択',{exact:true}).locator('option')).toHaveCount(3);
 await menuAction(page,'Undo');await expect(page.getByLabel('章の選択',{exact:true}).locator('option')).toHaveCount(2);
});

test('a non-JSON error during the chapter refresh after update stays actionable',async({page})=>{
 await newProject(page);await page.getByLabel('次の段落・文',{exact:true}).click();
 const body=page.getByLabel('本文を編集',{exact:true});await expect(body).toHaveValue('今日は良い天汽だった。庭の向こうで、小さな鳥が鳴いている。');
 await page.route('**/chapters/chapter0001',route=>route.fulfill({status:502,contentType:'text/html',body:'<html>private proxy failure</html>'}));
 await body.fill('今日は良い天気だった。庭の向こうで、小さな鳥が鳴いている。');await page.getByRole('button',{name:'更新',exact:true}).click();
 await expect(page.getByRole('alert').filter({hasText:'HTTP 502'})).toBeVisible();
 await expect(page.getByText('private proxy failure',{exact:false})).toHaveCount(0);
});
