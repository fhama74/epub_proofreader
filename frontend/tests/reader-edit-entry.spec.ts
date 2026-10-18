import {test,expect} from '@playwright/test';
import {newProject} from './helpers';

for(const action of ['更新','確認済みにする']){
 test(`tablet text tap returns to reading after ${action}; toolbar editing continues`,async({page})=>{
  await page.setViewportSize({width:820,height:1180});await newProject(page);
  await page.frameLocator('iframe').locator('[data-paragraph="chapter0001-p00001"]').click();
  const editor=page.getByLabel('本文を編集',{exact:true});await expect(editor).toBeVisible();
  if(action==='更新')await editor.fill('吾輩は猫である。名前はまだない。追記。');
  await page.getByRole('button',{name:action,exact:true}).click();
  await expect(page.locator('.info-pane')).toBeHidden();await expect(page.locator('.epub-pane')).toBeVisible();
  await expect(page.locator('.epub-pane .pane-foot')).toContainText('校正対象：段落 1 / 3');
  await page.getByRole('button',{name:'編集',exact:true}).click();await expect(editor).toBeVisible();
  if(action==='更新')await editor.fill('吾輩は猫である。名前はまだない。さらに追記。');
  await page.getByRole('button',{name:action,exact:true}).click();
  await expect(editor).toHaveValue('今日は良い天汽だった。庭の向こうで、小さな鳥が鳴いている。');
  await expect(page.locator('.info-pane')).toBeVisible();await expect(page.locator('.epub-pane')).toBeHidden();
  await page.getByRole('button',{name:'読書に戻る',exact:true}).click();
  await expect(page.locator('.epub-pane')).toBeVisible();
  // A new tap must not inherit the previous toolbar entry mode.
  await page.frameLocator('iframe').locator('[data-paragraph="chapter0001-p00002"]').click();
  await page.getByRole('button',{name:'確認済みにする',exact:true}).click();
  await expect(page.locator('.info-pane')).toBeHidden();
 });
 test(`desktop ${action} advances exactly one unit even with a later AI finding`,async({page})=>{
  await page.route(/\/api\/books\/[^/]+\/ai(?:\/events)?$/,route=>{
   const id=new URL(route.request().url()).pathname.split('/')[3];
   const candidate={id:'later',book_id:id,chapter_id:'chapter0001',paragraph_id:'chapter0001-p00003',target:'text',start:0,end:1,original:'静',replacement:null,status:'pending',stale:false,reason:'test'};
   const data={jobs:[],results:[candidate]};
   return route.request().url().endsWith('/events')?route.fulfill({contentType:'text/event-stream',body:`data: ${JSON.stringify(data)}\n\n`}):route.fulfill({json:data});
  });
  await newProject(page);
  const editor=page.getByLabel('本文を編集',{exact:true});
  if(action==='更新')await editor.fill('吾輩は猫である。名前はまだない。追記。');
  await page.getByRole('button',{name:action,exact:true}).click();
  await expect(editor).toHaveValue('今日は良い天汽だった。庭の向こうで、小さな鳥が鳴いている。');
  await expect(page.locator('.info-pane')).toBeVisible();
  await expect(page.frameLocator('iframe').locator('.selected')).toContainText('天汽');
 });
}
