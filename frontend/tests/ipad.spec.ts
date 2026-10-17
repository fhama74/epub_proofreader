import {test,expect} from '@playwright/test';
import {newProject} from './helpers';
test.use({viewport:{width:820,height:1180},hasTouch:true});
test('tablet reader, PDF position, editing drafts and rotation',async({page})=>{
 await newProject(page,'book.epub','original.pdf');
 await expect(page.locator('.app')).toHaveClass(/reader-mode/);
 await expect(page.locator('.epub-pane')).toBeVisible();await expect(page.locator('.pdf-pane')).toBeHidden();await expect(page.locator('.info-pane')).toBeHidden();
 await page.getByRole('button',{name:'PDF',exact:true}).click();await page.getByLabel('PDF次ページ',{exact:true}).click();
 await expect(page.getByLabel('PDFページ番号',{exact:true})).toHaveValue('2');
 await page.getByRole('button',{name:'本文',exact:true}).click();
 await expect(page.frameLocator('iframe').locator('#epub-content')).toBeVisible();
 await expect.poll(()=>page.locator('iframe').evaluate(el=>el.getBoundingClientRect().height)).toBeGreaterThan(200);
 await page.getByRole('button',{name:'編集',exact:true}).click();
 await expect(page.locator('.info-pane')).toBeVisible();await expect(page.locator('.epub-pane')).toBeHidden();
 const body=page.getByLabel('本文を編集',{exact:true});const draft='吾輩は猫である。名前はまだない。入力途中。';await body.fill(draft);
 await page.getByRole('button',{name:'PDF',exact:true}).click();await expect(page.getByLabel('PDFページ番号',{exact:true})).toHaveValue('2');
 await page.getByRole('button',{name:'編集',exact:true}).click();await expect(body).toHaveValue(draft);
 await page.reload();await page.getByRole('button',{name:'編集',exact:true}).click();await expect(body).toHaveValue(draft);
 await page.setViewportSize({width:1180,height:820});await expect(body).toBeVisible();await expect(page.locator('.app')).toHaveClass(/reader-mode/);
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.getByRole('button',{name:'読書に戻る',exact:true}).click();await expect(page.locator('.epub-pane')).toBeVisible();
});
test('body taps choose the proofreading unit and navigation starts at the tapped position',async({page})=>{
 await newProject(page);
 const frame=page.frameLocator('iframe');
 await frame.locator('[data-paragraph="chapter0001-p00003"]').click();
 await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('静かな午後、書物を開いて一文字ずつ確かめた。');
 await page.getByLabel('前の段落・文',{exact:true}).click();await expect(page.getByLabel('現在の本文',{exact:true})).toContainText('天汽');
 await page.getByLabel('次の段落・文',{exact:true}).click();await expect(page.getByLabel('現在の本文',{exact:true})).toContainText('書物');
 await page.getByRole('button',{name:'読書に戻る',exact:true}).click();
 await page.getByRole('button',{name:'通常表示',exact:true}).click();
 await frame.locator('[data-paragraph="chapter0001-p00001"]').click();
 await expect(page.getByLabel('現在の本文',{exact:true})).toContainText('吾輩');
 await page.getByLabel('次の段落・文',{exact:true}).click();await expect(page.getByLabel('現在の本文',{exact:true})).toContainText('天汽');
});

test('ruby list can expand and shrink the base range without stale drafts after updating',async({page})=>{
 await newProject(page);
 await page.frameLocator('iframe').locator('[data-paragraph="chapter0001-p00001"]').click();
 await page.getByRole('button',{name:'ルビの訂正',exact:true}).click();
 const popup=page.getByRole('dialog',{name:'ルビの訂正',exact:true});
 const base=popup.getByLabel('親文字 chapter0001-p00001 0',{exact:true});
 const reading=popup.getByLabel('読み chapter0001-p00001 0',{exact:true});
 await popup.getByRole('button',{name:'右へ広げる',exact:true}).click();await expect(base).toHaveValue('吾輩は');
 await reading.fill('わがはいは');await popup.getByRole('button',{name:'更新',exact:true}).click();
 await expect(base).toBeEnabled();await expect(popup).not.toContainText('原文が変わっています');
 await popup.getByRole('button',{name:'右を戻す',exact:true}).click();await reading.fill('わがはい');
 await popup.getByRole('button',{name:'更新',exact:true}).click();await expect(base).toHaveValue('吾輩');await expect(base).toBeEnabled();
 await page.getByRole('button',{name:'ルビ一覧を閉じる',exact:true}).click();
 await expect(page.getByLabel('現在の本文',{exact:true})).toHaveText('吾輩は猫である。名前はまだない。');
});

test('reader page arrows sit on the sides and page turns keep the editor closed',async({page})=>{
 await newProject(page,'navigation.epub','original.pdf');
 const next=page.getByLabel('本文次の表示ページ',{exact:true}),previous=page.getByLabel('本文前の表示ページ',{exact:true});
 const a=await next.boundingBox(),b=await previous.boundingBox();
 expect(a!.width).toBeGreaterThanOrEqual(44);expect(a!.height).toBeGreaterThanOrEqual(80);expect(a!.x).toBeLessThan(b!.x);
 await expect(next).toHaveText('◀');await expect(previous).toHaveText('▶');
 await next.click();await expect(page.getByRole('button',{name:'編集',exact:true})).toBeVisible();await expect(page.locator('.info-pane')).toBeHidden();
 await expect(page.getByLabel('本文表示ページ',{exact:true})).toContainText('表示 2 /');
 await page.getByRole('button',{name:'PDF',exact:true}).click();
 await expect(page.locator('.pdf-follow')).toContainText('利用できる文字レイヤーがありません');
 const pdfPrevious=await page.getByLabel('PDF前ページ',{exact:true}).boundingBox(),pdfNext=await page.getByLabel('PDF次ページ',{exact:true}).boundingBox();
 expect(pdfNext!.x).toBeLessThan(pdfPrevious!.x);expect(pdfNext!.height).toBeGreaterThanOrEqual(80);
});

test('body page navigation crosses chapters and an update returns to reading',async({page})=>{
 await newProject(page,'book.epub');
 const position=page.getByLabel('本文表示ページ',{exact:true});
 const next=page.getByLabel('本文次の表示ページ',{exact:true});
 for(let n=0;n<20;n++){
  const text=await position.innerText();const numbers=text.match(/\d+/g)!.map(Number);
  if(numbers[0]===numbers[1])break;
  await next.click();
 }
 await next.click();await expect(page.getByLabel('章の選択',{exact:true})).toHaveValue('1');await expect(position).toContainText('表示 1 /');
 await page.getByLabel('本文前の表示ページ',{exact:true}).click();await expect(page.getByLabel('章の選択',{exact:true})).toHaveValue('0');
 await expect.poll(async()=>{const values=(await position.innerText()).match(/\d+/g)!.map(Number);return values[0]===values[1];}).toBe(true);
 await page.getByRole('button',{name:'編集',exact:true}).click();const editor=page.getByLabel('本文を編集',{exact:true});await expect(editor).toBeEnabled();await editor.fill((await editor.inputValue())+'追記。');await page.getByRole('button',{name:'更新',exact:true}).click();
 await expect(page.locator('.info-pane')).toBeHidden();await expect(page.locator('.epub-pane')).toBeVisible();
});
