import {engineFetch} from "./engine.js";
import {TV_SYMBOLS,INTERVALS,widgetConfig,candlesForChart,chartMarkers,planLines} from "./chartModel.mjs";
import {identityState} from "./userJournal.mjs";
let chart=null,controller=null,generation=0,timer=null;
export function renderMarkets(){
  const symbols=identityState.entitlements?.symbols||Object.keys(TV_SYMBOLS);
  return `<section class="markets-workspace"><div class="kicker">MARKET INTELLIGENCE</div><h1>Markets</h1><p>Broker candles and TRADEden observations, beside an independent TradingView reference chart.</p><div class="chart-controls"><label>Market <select id="chartSymbol">${symbols.map(s=>`<option>${s}</option>`).join("")}</select></label><label>Timeframe <select id="chartTimeframe">${Object.keys(INTERVALS).map(s=>`<option ${s==="M15"?"selected":""}>${s}</option>`).join("")}</select></label><label>Plan <select id="chartPlan"><option value="">No overlay</option></select></label><button id="refreshChart" class="ghost">Refresh</button></div><h2>TRADEden Intelligence Chart</h2><p id="chartStatus" role="status">Loading verified broker candles…</p><div id="intelligenceChart" class="chart-canvas" aria-label="TRADEden broker candle chart"></div><p class="chart-caption">Arrows distinguish observations, confirmations and hypothetical outcomes. They are not executed trades. <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">Charts by TradingView Lightweight Charts™</a></p><h2>TradingView market reference</h2><p>TradingView symbols are mapped to comparable instruments; broker quotes and sessions may differ.</p><button id="loadTradingView" class="ghost">Load official TradingView chart</button><div id="tradingViewChart" class="chart-canvas"></div></section>`;
}
export function stopMarkets(){generation++;controller?.abort();controller=null;chart?.remove();chart=null;clearInterval(timer);timer=null;}
export async function initMarkets(){
  stopMarkets();
  const root=document.getElementById("intelligenceChart");if(!root)return;
  const token=generation;
  const {createChart,CandlestickSeries,createSeriesMarkers}=await import("lightweight-charts");
  if(token!==generation||!root.isConnected)return;
  chart=createChart(root,{autoSize:true,layout:{background:{color:"#10231f"},textColor:"#c4d8cf",attributionLogo:true},grid:{vertLines:{color:"#213c33"},horzLines:{color:"#213c33"}},timeScale:{timeVisible:true}});
  const series=chart.addSeries(CandlestickSeries,{upColor:"#78dba9",downColor:"#e98683",borderVisible:false,wickUpColor:"#78dba9",wickDownColor:"#e98683"});
  const markers=createSeriesMarkers(series,[]);let episodes=[],lines=[],requestNumber=0,widgetLoaded=false;
  const selection=()=>({symbol:document.getElementById("chartSymbol").value,timeframe:document.getElementById("chartTimeframe").value});
  function overlay(){for(const l of lines)series.removePriceLine(l);lines=planLines(episodes.find(e=>e.setup_id===document.getElementById("chartPlan").value)).map(l=>series.createPriceLine(l));}
  function widget(){
    const host=document.getElementById("tradingViewChart");host.replaceChildren();
    const wrap=document.createElement("div");wrap.className="tradingview-widget-container";wrap.style.height="100%";
    const inner=document.createElement("div");inner.className="tradingview-widget-container__widget";inner.style.height="100%";wrap.append(inner);
    const script=document.createElement("script");script.src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";script.async=true;
    const {symbol,timeframe}=selection();script.textContent=JSON.stringify(widgetConfig(symbol,timeframe));
    wrap.append(script);host.append(wrap);widgetLoaded=true;
    document.getElementById("loadTradingView").textContent="Reload TradingView chart";
  }
  async function load(){
    controller?.abort();controller=new AbortController();const number=++requestNumber;
    const {symbol,timeframe}=selection(),status=document.getElementById("chartStatus");status.textContent="Loading verified broker candles…";
    try{
      const data=await engineFetch(`/api/market/chart?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`,{signal:controller.signal});
      if(token!==generation||number!==requestNumber)return;
      const candles=candlesForChart(data.candles);if(!candles.length)throw new Error("No verified candles available");
      series.setData(candles);
      const precision=Number.isInteger(data.digits)?data.digits:2;
      series.applyOptions({priceFormat:{type:"price",precision,minMove:data.tick_size||10**(-precision)}});
      episodes=data.episodes||[];markers.setMarkers(chartMarkers(candles,episodes,data.outcomes));
      const select=document.getElementById("chartPlan"),previous=select.value;select.replaceChildren(new Option("No overlay",""));
      for(const e of episodes)select.add(new Option(`${e.strategy_id} · ${e.direction||"watch"} · ${e.setup_type||"observation"}`,e.setup_id));
      select.value=previous;overlay();chart.timeScale().fitContent();
      status.textContent=`${symbol} · ${timeframe} · ${candles.length} broker candles · verified UTC`;
    }catch(error){if(error.name!=="AbortError"&&token===generation){series.setData([]);markers.setMarkers([]);episodes=[];overlay();status.textContent="Broker chart unavailable. Sign in and check the market feed; no candles are fabricated.";}}
  }
  for(const id of ["chartSymbol","chartTimeframe"])document.getElementById(id).onchange=()=>{load();if(widgetLoaded)widget();};
  document.getElementById("chartPlan").onchange=overlay;
  document.getElementById("refreshChart").onclick=load;document.getElementById("loadTradingView").onclick=widget;
  await load();if(token===generation&&root.isConnected)timer=setInterval(load,60000);
}
