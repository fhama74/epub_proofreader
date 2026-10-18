import {test,expect} from '@playwright/test';
import {newProject} from './helpers';

test('confirmation shows its own progress and never reloads the chapter or book',async({page})=>{
 await newProject(page);await expect(page.getByLabel('本文を編集',{exact:true})).toHaveValue('吾輩は猫である。名前はまだない。');
 const id=await page.evaluate(()=>localStorage.getItem('lastBook'));
 let release!:()=>void;const gate=new Promise<void>(resolve=>release=resolve);
 await page.route('**/paragraphs/*/review',async route=>{await gate;await route.continue();});
 const requests:{url:string;method:string}[]=[];page.on('request',r=>requests.push({url:new URL(r.url()).pathname,method:r.method()}));
 await page.getByRole('button',{name:'確認済みにする',exact:true}).click();
 await expect(page.getByRole('button',{name:'確認中…',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'更新',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'更新中…',exact:true})).toHaveCount(0);
 release();await expect(page.getByLabel('現在の本文',{exact:true})).toContainText('今日は良い天汽');
 await expect(page.getByRole('button',{name:'確認済みにする',exact:true})).toBeEnabled();
 expect(requests.filter(r=>r.method==='POST' && r.url.endsWith('/review'))).toHaveLength(1);
 expect(requests.filter(r=>r.url===`/api/books/${id}` || r.url===`/api/books/${id}/project` || r.url===`/api/books/${id}/ai` || r.url.includes('/chapters/'))).toEqual([]);
 await page.getByLabel('前の段落・文',{exact:true}).click();await expect(page.getByLabel('段落の校閲状態：確定済み',{exact:true})).toBeVisible();
});
