import {test,expect} from '@playwright/test';
import {newProject,openActions,menuAction} from './helpers';
test.use({viewport:{width:390,height:844},hasTouch:true});
test('phone has one-line project identity, a compact title and top operation menu',async({page})=>{
 await newProject(page);
 await expect.poll(()=>page.locator('header').evaluate(el=>el.getBoundingClientRect().height)).toBeLessThanOrEqual(48);
 await expect(page.getByText('原本と、一文字ずつ。',{exact:true})).toHaveCount(0);
 const positions=await page.locator('.project-summary').evaluate(el=>Array.from(el.children).map(e=>e.getBoundingClientRect().top));expect(Math.max(...positions)-Math.min(...positions)).toBeLessThan(8);
 await expect(page.locator('footer button')).toHaveCount(0);await openActions(page);
 await expect(page.getByRole('button',{name:'EPUB発行',exact:true})).toBeVisible();
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.getByLabel('操作メニュー',{exact:true}).click();
 await page.frameLocator('iframe').locator('[data-paragraph]').first().click();
 const editor=page.getByLabel('本文を編集',{exact:true});await expect(editor).toBeVisible();await editor.fill('吾輩は猫である。名前はまだない。追記。');await page.getByRole('button',{name:'更新',exact:true}).click();
 await expect(page.locator('.epub-pane')).toBeVisible();await expect(page.locator('.info-pane')).toBeHidden();
 await menuAction(page,'EPUB発行');await expect(page.getByRole('dialog',{name:'EPUB発行',exact:true})).toBeVisible();
});
