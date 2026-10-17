import { test, expect } from '@playwright/test';
import path from 'node:path';
import {newProject} from './helpers';
const sample = (name: string) => path.resolve('../samples', name);

test('sample PDF rendering, vertical ruby, chapter and paragraph navigation', async ({page}) => {
  const failures: string[] = [];
  page.on('pageerror', error => failures.push(error.message));
  await newProject(page,'book.epub','original.pdf');
  await expect(page.getByText('book.epub', {exact:true})).toBeVisible();
  const epub = page.frameLocator('iframe');
  await expect(epub.locator('ruby').first()).toContainText('わがはい');
  await expect(epub.locator('#epub-content')).toHaveCSS('writing-mode', 'vertical-rl');
  await expect(epub.locator('p.selected')).toHaveAttribute('data-paragraph', 'chapter0001-p00001');
  await expect(epub.locator('img')).toBeVisible();
  await expect.poll(() => epub.locator('img').evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect.poll(() => page.locator('canvas').evaluate((c: HTMLCanvasElement) => {
    if (!c.width || !c.height) return false;
    const rgba = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    let dark = 0; for (let i = 0; i < rgba.length; i += 4) if (rgba[i] < 180 && rgba[i + 1] < 180 && rgba[i + 2] < 180 && rgba[i + 3] > 0) dark++;
    return dark > 100;
  })).toBe(true);
  await page.getByRole('button', {name: '次の段落・文'}).click();
  await expect(epub.locator('p.selected')).toContainText('天汽');
  await page.keyboard.press('Alt+ArrowDown');
  await expect(epub.locator('p.selected')).toContainText('書物');
  await page.getByLabel('章の選択').selectOption('1');
  await expect(epub.locator('ruby').first().locator('rt')).toHaveCount(2);
  await epub.locator('p').nth(1).click();
  await expect(page.locator('.proof-position')).toContainText('2 / 3');
  await expect(page.locator('.pdf-toolbar button')).toHaveCount(0);
  await expect(page.getByLabel('PDF次ページ',{exact:true})).toHaveCount(1);
  await page.getByLabel('PDF次ページ').click();
  await expect(page.getByLabel('PDFページ番号')).toHaveValue('2');
  await page.getByLabel('PDF表示倍率').selectOption('1.5');
  await expect(page.getByLabel('PDF表示倍率')).toHaveValue('1.5');
  await page.getByText('表示設定',{exact:true}).click();
  await page.getByLabel('文字サイズ').press('ArrowRight');
  await expect(epub.locator('body')).toHaveCSS('font-size', '21px');
  await expect(page.locator('.paragraph-list')).toHaveCount(0);
  await page.getByRole('button', {name:'原本 非表示'}).click();
  await expect(page.locator('.pdf-pane')).toBeHidden();
  await page.getByRole('button', {name:'原本 表示'}).click();
  await expect(page.locator('canvas')).toBeVisible();
  const separator = page.getByRole('separator', {name:'原本ペインの幅'});
  const box = await separator.boundingBox();
  await page.mouse.move(box!.x + 5, box!.y + 100); await page.mouse.down();
  await page.mouse.move(box!.x + 65, box!.y + 100); await page.mouse.up();
  await page.screenshot({path:'../docs/phase1-preview.png', fullPage:true});
  expect(failures).toEqual([]);
});

test('file chooser imports EPUB/PDF, rejects invalid EPUB and keeps original unchanged', async ({page, request}) => {
  await page.goto('/');
  await page.locator('input[accept=".epub,.pdf,.eproof"]').setInputFiles([sample('book.epub'), sample('original.pdf')]);
  await expect(page.getByText('book.epub', {exact:true})).toBeVisible();
  await page.locator('input[accept=".epub,.pdf,.eproof"]').setInputFiles({name:'invalid.epub', mimeType:'application/epub+zip', buffer:Buffer.from('not zip')});
  await expect(page.getByRole('alert')).toContainText('ZIP');
  const response = await request.post('/api/books', {multipart: {file: {name:'book.epub', mimeType:'application/epub+zip', buffer: await (await import('node:fs/promises')).readFile(sample('book.epub'))}}});
  const book = await response.json();
  const original = await request.get(`/api/books/${book.id}/original`);
  expect(await original.body()).toEqual(await (await import('node:fs/promises')).readFile(sample('book.epub')));
});

test('drop imports EPUB and small screen can collapse panes', async ({page}) => {
  await page.goto('/');
  const bytes = await (await import('node:fs/promises')).readFile(sample('book.epub'));
  const transfer = await page.evaluateHandle((bytes) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([new Uint8Array(bytes)], 'drop.epub', {type:'application/epub+zip'}));
    return transfer;
  }, Array.from(bytes));
  await page.locator('.app').dispatchEvent('drop', {dataTransfer: transfer});
  await expect(page.frameLocator('iframe').locator('ruby').first()).toBeVisible();
  await page.setViewportSize({width:600,height:900});
  await expect(page.getByRole('button',{name:'編集',exact:true})).toBeVisible();
  await expect(page.locator('.pdf-pane')).toBeHidden();
  await expect(page.locator('.info-pane')).toBeHidden();
  await expect(page.locator('iframe')).toBeVisible();
});

test('six pages render across JPEG to CCITT switch, including pages 4–6', async ({page, request}) => {
  const decoder = await request.get('/pdfjs/wasm/jbig2.wasm');
  expect(decoder.ok()).toBe(true);
  expect((await decoder.body()).subarray(0, 4)).toEqual(Buffer.from([0,97,115,109]));
  await page.goto('/');
  await page.locator('input[accept=".epub,.pdf,.eproof"]').setInputFiles(sample('decoder-regression.pdf'));
  await expect(page.getByLabel('PDF次ページ')).toBeEnabled();
  for (const number of [1, 2, 3, 4, 5, 6, 4, 1]) {
    await page.getByLabel('PDFページ番号').fill(String(number));
    await expect(page.getByText('ページ描画中…')).toHaveCount(0);
    await expect.poll(() => page.locator('canvas').evaluate((c: HTMLCanvasElement) => {
      if (!c.width || !c.height) return 0;
      const data = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      let dark = 0;
      for (let i = 0; i < data.length; i += 4) if (data[i] < 100 && data[i + 3] > 0) dark++;
      return dark;
    })).toBeGreaterThan(1000);
  }
});
