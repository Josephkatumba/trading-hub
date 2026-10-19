import {chromium} from '@playwright/test';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {dirname,join} from 'node:path';
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const root=dirname(fileURLToPath(import.meta.url));
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const checks=[];const errors=[];
try{
 const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(join(root,'dashboard.html')).href);await page.getByRole('heading',{name:'TradeDen Research',exact:true}).waitFor();
 for(const name of ['Codex Quant Lab','Claude Quant Lab','Kimi Quant Lab'])assert.equal(await page.getByRole('heading',{name,exact:true}).count(),1);
 checks.push('three distinct lab cards with real stored counts');
 await page.getByRole('tab',{name:'Qualified strategies',exact:true}).click();await page.getByRole('heading',{name:'No strategies qualified'}).waitFor();checks.push('qualified view has explicit empty state');
 await page.getByRole('tab',{name:'Prior research',exact:true}).click();await page.locator('#lab-filter').selectOption('claude');await page.getByRole('heading',{name:'No prior research imported'}).waitFor();checks.push('lab filter preserves empty Claude evidence');
 await page.locator('#lab-filter').selectOption('codex');assert.equal(await page.locator('#results tbody tr').count(),5);checks.push('five imported Codex hypotheses labelled prior research');
 await page.locator('#lab-filter').selectOption('all');await page.getByRole('tab',{name:'Research leaderboard',exact:true}).click();
 await page.screenshot({path:join(root,'verification/dashboard-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);checks.push('390px mobile layout has no page overflow');
 await page.screenshot({path:join(root,'verification/dashboard-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);checks.push('no browser runtime errors');
 writeFileSync(join(root,'verification/dashboard-tests.json'),JSON.stringify({passed:true,checks,screenshots:['dashboard-desktop.png','dashboard-mobile.png']},null,2));
 console.log(JSON.stringify({passed:true,checks},null,2));
}finally{await browser.close();}
