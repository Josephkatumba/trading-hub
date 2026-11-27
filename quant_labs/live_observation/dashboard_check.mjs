import {chromium} from '@playwright/test';
import fs from 'node:fs';
const folder=new URL('./',import.meta.url);
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://localhost:5173/trading-hub/',{waitUntil:'domcontentloaded'});
 await page.locator('[data-view="quantLabs"]').click();
 await page.locator('#quantLabsData').getByText('Compression Escape',{exact:false}).first().waitFor();
 const text=await page.locator('#quantLabsData').innerText();
 if(!text.includes('Collector consumer enabled')||!text.includes('Running')||!text.includes('NO OUTBOUND DELIVERY'))throw Error('Live dashboard consumer state mismatch');
 await page.screenshot({path:new URL('dashboard-live.png',folder).pathname.replace(/^\/([A-Za-z]:)/,'$1'),fullPage:true});
 await page.locator('[data-view="markets"]').click();await page.locator('#intelligenceChart').waitFor();
 await page.locator('[data-view="radar"]').first().click();await page.locator('#radarRoot').waitFor();
 fs.writeFileSync(new URL('dashboard_check.json',folder),JSON.stringify({at:new Date().toISOString(),liveConsumerVisible:true,experimentalDeliveryDisabled:true,marketsVisible:true,gardenVisible:true,errors},null,2));
 if(errors.length)throw Error(JSON.stringify(errors));
 console.log('Genuine local dashboard: live paper consumer visible; Markets and Garden intact; no page errors.');
}finally{await browser.close();}
