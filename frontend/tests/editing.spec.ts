import {test,expect} from '@playwright/test';
import {newProject,menuAction,openActions} from './helpers';
test('edit, undo, redo, ruby and validated EPUB download',async({page})=>{
  await newProject(page);
  await expect(page.locator('iframe')).toBeVisible();
  await page.getByRole('button',{name:'次の段落・文'}).click();
  await page.getByLabel('本文を編集',{exact:true}).fill('今日は良い天気だった。庭の向こうで、小さな鳥が鳴いている。');
  await page.getByRole('button',{name:'更新',exact:true}).click();
  const frame=page.frameLocator('iframe');
  await expect(frame.locator('p.selected')).toContainText('天気');
  await menuAction(page,'Undo');
  await expect(frame.locator('p.selected')).toContainText('天汽');
  await menuAction(page,'Redo');
  await expect(frame.locator('p.selected')).toContainText('天気');
  await frame.locator('ruby').first().click();
  await page.getByRole('button',{name:'ルビの訂正',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'ルビの訂正'})).toBeVisible();
  await page.getByLabel(/^親文字 /).first().fill('我輩');
  await page.getByRole('dialog',{name:'ルビの訂正'}).getByRole('button',{name:'更新',exact:true}).click();
  await expect(page.getByLabel(/^親文字 /).first()).toBeEnabled();
  await page.getByRole('button',{name:'ルビ一覧を閉じる',exact:true}).click();
  await expect(frame.locator('ruby').first()).toContainText('我輩');
  await expect(frame.locator('ruby').first().locator('rp')).toHaveCount(2);
  await menuAction(page,'履歴');
  await expect(page.getByRole('dialog',{name:'校正履歴'})).toContainText('4件');
  await page.getByRole('button',{name:'閉じる',exact:true}).click();
  await menuAction(page,'EPUB発行');
  await expect(page.getByRole('dialog',{name:'EPUB発行'})).toContainText('内部構造検証：成功',{timeout:20000});
  await page.getByRole('button',{name:'v1を発行して保存',exact:true}).click();
  const promise=page.waitForEvent('download');
  await page.getByRole('link',{name:'v1のEPUBをダウンロード',exact:true}).click();
  expect((await promise).suggestedFilename()).toBe('book_v001.epub');
});
test('complex ruby is protected and search/replace preserves it',async({page})=>{
  await newProject(page);
  await page.getByLabel('章の選択').selectOption('1');
  await page.frameLocator('iframe').locator('ruby').first().click();
  await page.getByRole('button',{name:'ルビの訂正',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'ルビの訂正'})).toBeVisible();
  await expect(page.getByLabel(/^親文字 /).first()).toBeDisabled();
  await page.getByRole('button',{name:'ルビ一覧を閉じる',exact:true}).click();
  await menuAction(page,'検索・置換');
  await page.getByLabel('置換対象').selectOption('book');
  await page.getByLabel('検索する文字列').fill('天汽');
  await page.getByLabel('置換後の文字列').fill('天気');
  await page.getByRole('button',{name:'置換を適用',exact:true}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByLabel('章の選択').selectOption('0');
  await expect(page.frameLocator('iframe').locator('body')).toContainText('天気');
});

test('sentence navigation and reversible paragraph split, merge and insertion',async({page})=>{
  await page.goto('/');
  await page.locator('input[accept=".epub,.pdf,.eproof"]').setInputFiles((await import('node:path')).resolve('../samples/navigation.epub'));
  await expect(page.locator('.proof-position')).toContainText('段落 1 / 3');
  await page.getByLabel('次の段落・文',{exact:true}).click();
  await expect(page.locator('.proof-position')).toContainText('文 1 / 40');
  await page.getByLabel('次の段落・文',{exact:true}).click();
  await expect(page.locator('.proof-position')).toContainText('文 2 / 40');
  await expect(page.getByLabel('本文を編集',{exact:true})).toBeVisible();
  await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('庭の景色を眺めながら本文の校正と段落の移動を確かめます。');
  await page.getByLabel('本文を編集',{exact:true}).press('Home');
  await page.getByText('既存の段落を二つに分ける',{exact:true}).click();
  await page.getByRole('button',{name:'カーソル位置で段落を分割',exact:true}).click();
  await expect(page.locator('.proof-position')).toContainText('/ 4');
  await page.getByText('段落・原本との対応',{exact:true}).click();
  await page.getByRole('button',{name:'前の段落に結合',exact:true}).click();
  await page.getByRole('button',{name:'前の段落に結合して再計算',exact:true}).click();
  await expect(page.locator('.proof-position')).toContainText('/ 3');
  await page.getByRole('button',{name:'欠けた本文を段落として追加',exact:true}).click();
  await page.getByLabel('挿入する本文',{exact:true}).fill('補完した本文。');
  await page.getByRole('button',{name:'段落を挿入して再計算',exact:true}).click();
  await expect(page.locator('.proof-position')).toContainText('/ 4');
  await menuAction(page,'Undo');
  await expect(page.locator('.proof-position')).toContainText('/ 3');
  await menuAction(page,'Redo');
  await expect(page.locator('.proof-position')).toContainText('/ 4');
});


test('proof controls live in pane 03 and selected sentences stay in view',async({page})=>{
  await page.goto('/');
  await page.locator('input[accept=".epub,.pdf,.eproof"]').setInputFiles((await import('node:path')).resolve('../samples/navigation.epub'));
  await expect(page.locator('.epub-pane').getByRole('button',{name:'ルビの訂正',exact:true})).toHaveCount(0);
  await expect(page.locator('.epub-pane .unit-controls')).toHaveCount(0);
  await expect(page.locator('.info-pane').getByLabel('次の段落・文',{exact:true})).toHaveCount(1);
  await page.getByText('段落・原本との対応',{exact:true}).click();
  await expect(page.locator('.info-pane').getByRole('button',{name:'欠けた本文を段落として追加',exact:true})).toBeVisible();
  for(const direction of [1,1,1,1,1,1,1,1,1,1,1,1,-1,-1,-1]){
    await page.getByLabel(direction>0?'次の段落・文':'前の段落・文',{exact:true}).click();
    await expect.poll(()=>page.frameLocator('iframe').locator('html').evaluate(root=>{
      const nodes=Array.from(root.querySelectorAll('.sentence-selected'));
      if(!nodes.length)return false;
      const rects=nodes.flatMap(node=>{const range=node.ownerDocument.createRange();range.selectNodeContents(node);return Array.from(range.getClientRects());}).filter(r=>r.width>0 && r.height>0);
      const left=Math.min(...rects.map(r=>r.left));const right=Math.max(...rects.map(r=>r.right));
      return right-left<=root.clientWidth-48?left>=23 && right<=root.clientWidth-23:rects[0].left>=23 && rects[0].right<=root.clientWidth-23;
    })).toBe(true);
  }
  // Manual page browsing still works independently; next selection restores follow.
  await page.getByLabel('本文前の表示ページ',{exact:true}).click();
  await page.getByLabel('次の段落・文',{exact:true}).click();
  await expect(page.frameLocator('iframe').locator('.sentence-selected')).not.toHaveCount(0);
});
