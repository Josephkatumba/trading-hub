import {test,expect} from "@playwright/test";
test("authenticated markets renders broker candles, overlays, widget and mobile layout",async({page})=>{
 const errors=[];page.on("pageerror",e=>errors.push(e.message));page.on("console",m=>{if(m.type()==="error")errors.push(m.text());});
 await page.addInitScript(()=>localStorage.setItem("th_engine_url",location.origin));
 const start=1791800000,iso=t=>new Date(t*1000).toISOString();
 const candles=Array.from({length:100},(_,i)=>({time:start+i*900,open:100+i/10,high:102+i/10,low:99+i/10,close:101+i/10}));
 await page.route("**/api/**",async route=>{
  const path=new URL(route.request().url()).pathname;
  const query=new URL(route.request().url()).searchParams;
  const data=path==="/api/auth/me"?{user:{id:"browser-test"},csrf:"test",entitlements:{plan:"free",symbols:["XAUUSD","BTCUSD","EURUSD","GBPUSD"]}}:
   path.startsWith("/api/journal/")?{records:[],next_cursor:null}:
   path==="/api/market/chart"?{symbol:query.get("symbol"),timeframe:query.get("timeframe"),candles,digits:2,tick_size:.01,
    episodes:query.get("research")==="true"?[{timeframe:query.get("timeframe"),symbol:query.get("symbol"),strategy_id:"smc",setup_id:"test-setup",direction:"LONG",observed_at:iso(start+900),proposed_entry:101,proposed_stop_loss:99,proposed_take_profit:106}]:[],
    outcomes:query.get("research")==="true"?[{observed_at:iso(start+900),setup_id:"test-setup",observation_id:"test-obs",horizon:"1h",horizon_end:iso(start+4500),label:"WIN",timestamp_quality:"VERIFIED"}]:[]}:
   path==="/api/market/opportunities"?{opportunities:[{symbol:"XAUUSD",timeframe:"M15",mode:"LIVE",trade_qualified:true,direction:"LONG",strategy_id:"smc",source_timestamp:iso(start+900),entry:101,stop_loss:99,take_profit:106,rr:2.5}]}:
   path==="/api/market/setup-episodes"?{current:[],confirmed:[],closed:[]}:
   path==="/api/market/outcomes"?{outcomes:[]}:
   {markets:[],strategies:[],status:"CONNECTED",live:false};
  await route.fulfill({contentType:"application/json",body:JSON.stringify(data)});
 });
 // Inspect official integration without requesting a third-party site in CI.
 let official=false;
 await page.route("https://s3.tradingview.com/**",async route=>{official=true;await route.fulfill({contentType:"application/javascript",body:"document.querySelector('.tradingview-widget-container__widget').textContent='Official widget loaded';"});});
 await page.goto("/classic.html");
 await expect(page.locator('[data-view="markets"]')).toBeVisible({timeout:5000}).catch(async error=>{console.log({errors,body:await page.locator('body').innerText()});throw error;});
 await page.locator('[data-view="markets"]').click();
 await expect(page.locator("#chartStatus")).toContainText("100 broker candles");
 await expect(page.locator("#intelligenceChart canvas").first()).toBeVisible();
 await expect(page.locator("#chartMode")).toHaveValue("overview");
 await expect(page.locator("#researchFilters")).toBeHidden();
 await expect(page.locator("#chartRecords button")).toHaveCount(0);
 await page.selectOption("#chartMode","signals");
 await expect(page.locator("#chartRecords button")).toHaveCount(1);
 await page.locator("#chartRecords button").click();
 await expect(page.locator("#chartDetails")).toContainText("Qualified signal");
 await expect(page.locator("#chartDetails")).toContainText("2.5");
 await page.selectOption("#chartMode","research");
 await expect(page.locator("#researchFilters")).toBeVisible();
 await expect(page.locator("#chartRecords button")).toHaveCount(1);
 await page.locator("#chartRecords button").click();
 await expect(page.locator("#chartDetails")).toContainText("never an executed trade");
 await page.selectOption("#researchOutcome","LOSS");
 await expect(page.locator("#chartRecords button")).toHaveCount(0);
 await page.selectOption("#researchOutcome","WIN");
 await expect(page.locator("#chartRecords button")).toHaveCount(1);
 await page.selectOption("#researchOutcome","");
 await page.selectOption("#chartPlan","test-setup");
 await expect(page.locator("#chartPlan")).toHaveValue("test-setup");
 await page.selectOption("#chartTimeframe","H1");
 await expect(page.locator("#chartStatus")).toContainText("H1");
 for(const symbol of ["BTCUSD","EURUSD","XAUUSD"]){await page.selectOption("#chartSymbol",symbol);await expect(page.locator("#chartStatus")).toContainText(symbol);}
 await page.click("#chartZoomIn");await page.click("#chartZoomOut");await page.click("#resetChart");
 await page.click("#loadTradingView");
 await expect(page.locator("#tradingViewChart")).toContainText("Official widget loaded");
 expect(official).toBe(true);
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:"test-results/intelligence-desktop.png",fullPage:true,animations:"disabled"});
 await page.setViewportSize({width:390,height:844});
 const size=await page.locator("#intelligenceChart").boundingBox();expect(size.width).toBeGreaterThan(100);expect(size.width).toBeLessThan(391);
 await page.screenshot({path:"test-results/intelligence-mobile.png",fullPage:true,animations:"disabled"});
 expect(errors).toEqual([]);
 await page.setViewportSize({width:1280,height:900});
 await page.locator('[data-view="radar"]').first().evaluate(element=>element.click());
 await expect(page.locator("#radarRoot")).toBeVisible();
});
test("commercial sign-in cannot display legacy browser trades",async({page})=>{
 await page.addInitScript(()=>{
  localStorage.setItem("th_engine_url",location.origin);
  localStorage.setItem("th_trades",JSON.stringify([{id:"private-owner-secret",symbol:"PRIVATE_SECRET",side:"BUY"}]));
 });
 await page.route("**/api/**",route=>route.fulfill({status:401,contentType:"application/json",body:'{"detail":"Sign in required"}'}));
 await page.goto("/classic.html");
 await expect(page.locator("#root")).toContainText("Sign in");
 await expect(page.locator("#root")).not.toContainText("PRIVATE_SECRET");
 await expect(page.locator('[data-view="trades"]')).toHaveCount(0);
});
