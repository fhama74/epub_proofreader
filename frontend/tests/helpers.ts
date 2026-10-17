import {expect,type Page} from '@playwright/test';
import path from 'node:path';
export async function newProject(page:Page,epub='book.epub',pdf?:string){
  await page.goto('/');
  await menuAction(page,'新規プロジェクト');
  await expect(page.getByRole('button',{name:'作成',exact:true})).toBeDisabled();
  await page.getByLabel('新規プロジェクトのEPUB',{exact:true}).setInputFiles(path.resolve('../samples',epub));
  if(pdf)await page.getByLabel('新規プロジェクトのPDF',{exact:true}).setInputFiles(path.resolve('../samples',pdf));
  await page.getByRole('button',{name:'作成',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'新規プロジェクト',exact:true})).toHaveCount(0);
  await expect(page.getByLabel('本文を編集',{exact:true})).toBeEnabled();
  const frame=page.frameLocator('iframe');
  await expect(frame.locator('#epub-content')).toBeVisible();
  await expect.poll(()=>frame.locator('#epub-content').evaluate(el=>el.ownerDocument.readyState)).toBe('complete');
}

export async function openActions(page:Page){if(await page.locator('.workspace-menu').getAttribute('open')===null)await page.getByLabel('操作メニュー',{exact:true}).click();}
export async function menuAction(page:Page,name:string){await openActions(page);await page.locator('.workspace-menu').getByRole('button',{name,exact:true}).click();}
