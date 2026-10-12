import {test,expect} from "@playwright/test";
test("authenticated markets renders broker candles, overlays, widget and mobile layout",async({page})=>{
 const errors=[];page.on("pageerror",e=>errors.push(e.message));
 await page.addInitScript(()=>localStorage.setItem("th_engine_url",location.origin));
 const start=1791800000,iso=t=>new Date(t*1000).toISOString();
 const candles=Array.from({length:100},(_,i)=>({time:start+i*900,open:100+i/10,high:102+i/10,low:99+i/10,close:101+i/10}));
 await page.route("**/api/**",async route=>{
  const path=new URL(route.request().url()).pathname;
  const data=path==="/api/auth/me"?{user:{id:"browser-test"},csrf:"test",entitlements:{plan:"free",symbols:["XAUUSD","EURUSD","GBPUSD"]}}:
   path.startsWith("/api/journal/")?{records:[],next_cursor:null}:
   path==="/api/market/chart"?{symbol:"XAUUSD",timeframe:"M15",candles,digits:2,tick_size:.01,
    episodes:[{symbol:"XAUUSD",strategy_id:"smc",setup_id:"test-setup",direction:"LONG",observed_at:iso(start+900),proposed_entry:101,proposed_stop_loss:99,proposed_take_profit:106}],
    outcomes:[{setup_id:"test-setup",observation_id:"test-obs",horizon:"1h",horizon_end:iso(start+4500),label:"WIN",timestamp_quality:"VERIFIED"}]}:
   path==="/api/market/setup-episodes"?{current:[],confirmed:[],closed:[]}:
   path==="/api/market/outcomes"?{outcomes:[]}:
   {markets:[],strategies:[],status:"CONNECTED",live:false};
  await route.fulfill({contentType:"application/json",body:JSON.stringify(data)});
 });
 // Inspect official integration without requesting a third-party site in CI.
 let official=false;
 await page.route("https://s3.tradingview.com/**",async route=>{official=true;await route.fulfill({contentType:"application/javascript",body:"document.querySelector('.tradingview-widget-container__widget').textContent='Official widget loaded';"});});
 await page.goto("/");
 await expect(page.locator('[data-view="markets"]')).toBeVisible({timeout:5000}).catch(async error=>{console.log({errors,body:await page.locator('body').innerText()});throw error;});
 await page.locator('[data-view="markets"]').click();
 await expect(page.locator("#chartStatus")).toContainText("100 broker candles");
 await expect(page.locator("#intelligenceChart canvas").first()).toBeVisible();
 await page.selectOption("#chartPlan","test-setup");
 await expect(page.locator("#chartPlan")).toHaveValue("test-setup");
 await page.selectOption("#chartTimeframe","H1");
 await expect(page.locator("#chartStatus")).toContainText("H1");
 await page.click("#loadTradingView");
 await expect(page.locator("#tradingViewChart")).toContainText("Official widget loaded");
 expect(official).toBe(true);
 await page.setViewportSize({width:390,height:844});
 const size=await page.locator("#intelligenceChart").boundingBox();expect(size.width).toBeGreaterThan(100);expect(size.width).toBeLessThan(391);
 expect(errors).toEqual([]);
 await page.locator('[data-view="radar"]').first().click({force:true});
 await expect(page.locator("#radarRoot")).toBeVisible();
});
test("commercial sign-in cannot display legacy browser trades",async({page})=>{
 await page.addInitScript(()=>{
  localStorage.setItem("th_engine_url",location.origin);
  localStorage.setItem("th_trades",JSON.stringify([{id:"private-owner-secret",symbol:"PRIVATE_SECRET",side:"BUY"}]));
 });
 await page.route("**/api/**",route=>route.fulfill({status:401,contentType:"application/json",body:'{"detail":"Sign in required"}'}));
 await page.goto("/");
 await expect(page.locator("#root")).toContainText("Sign in");
 await expect(page.locator("#root")).not.toContainText("PRIVATE_SECRET");
 await expect(page.locator('[data-view="trades"]')).toHaveCount(0);
});
