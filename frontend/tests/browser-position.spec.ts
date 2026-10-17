import {test,expect} from '@playwright/test';
import {newProject} from './helpers';

test('browser positions survive a new session and another browser updating the project',async({page,browser,baseURL})=>{
  await newProject(page,'book.epub','original.pdf');
  const id=(await page.evaluate(()=>localStorage.getItem('lastBook')))!;
  const projectPath=`/api/books/${id}/project`;
  const initial=await (await page.request.get(projectPath)).json();
  await page.getByLabel('次の段落・文',{exact:true}).click();
  await expect(page.getByLabel('現在の本文',{exact:true})).toContainText('天汽');
  await page.getByLabel('本文にPDFを追従',{exact:true}).uncheck();
  await page.getByLabel('PDFページ番号',{exact:true}).fill('2');
  await expect.poll(()=>page.evaluate(id=>{
    const record=JSON.parse(localStorage.getItem(`eproof-view:${id}`)||'null');
    return [record?.view?.paragraphId,record?.view?.pdf?.page];
  },id)).toEqual(['chapter0001-p00002',2]);
  const browserA=await page.context().storageState();
  const other=await browser.newContext({baseURL,viewport:{width:1440,height:960}});
  const reopened=await browser.newContext({baseURL,viewport:{width:1440,height:960},storageState:browserA});
  try{
    await other.addInitScript(id=>localStorage.setItem('lastBook',id),id);
    const second=await other.newPage();await second.goto('/');
    await expect(second.getByLabel('本文を編集',{exact:true})).toBeEnabled();
    await second.getByLabel('章の選択',{exact:true}).selectOption('1');
    await second.getByLabel('次の段落・文',{exact:true}).click();
    await expect(second.getByLabel('現在の本文',{exact:true})).toContainText('東京');
    await expect.poll(()=>second.evaluate(id=>JSON.parse(localStorage.getItem(`eproof-view:${id}`)||'null')?.view?.paragraphId,id)).toBe('chapter0002-p00002');
    // Position-only navigation must not change the shared project's version/view.
    const unchanged=await (await second.request.get(projectPath)).json();
    expect(unchanged.version).toBe(initial.version);
    expect(unchanged.view).toEqual(initial.view);
    const response=await second.request.patch(projectPath,{data:{version:unchanged.version,statuses:{'chapter0002-p00001':'human_checked'}}});
    expect(response.ok()).toBe(true);
    // A new browser session retains A's own selection and PDF page, even after B's write.
    const firstAgain=await reopened.newPage();await firstAgain.goto('/');
    await expect(firstAgain.getByLabel('現在の本文',{exact:true})).toContainText('天汽');
    await expect(firstAgain.getByLabel('章の選択',{exact:true})).toHaveValue('0');
    await expect(firstAgain.getByLabel('PDFページ番号',{exact:true})).toHaveValue('2');
    await expect(firstAgain.getByRole('alert')).toHaveCount(0);
    await second.reload();
    await expect(second.getByLabel('章の選択',{exact:true})).toHaveValue('1');
    await expect(second.getByLabel('現在の本文',{exact:true})).toContainText('東京');
  }finally{
    await other.close();await reopened.close();
  }
});
