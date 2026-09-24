// Bundled sample trades once carried MT5 login numbers in account names and IDs
// (e.g. "XM Demo 333840872"). They were removed from src/importedData.js; this
// applies the same redaction to copies already saved in a browser (trades and
// journal keys) so reviews stay attached. Only sample records are affected.
const LEGACY_SAMPLE_ACCOUNT=/\b(XM Demo|ICMarkets Demo) \d{6,}\b/;
export const redactSampleText=value=>String(value??"").replace(LEGACY_SAMPLE_ACCOUNT,"$1");
export function redactSampleTrade(trade){
  if(!String(trade?.id||"").startsWith("MT5-"))return trade;
  return {...trade,id:redactSampleText(trade.id),account:redactSampleText(trade.account)};
}
export function migrateJournalKeys(journal){
  let changed=false;const out={};
  for(const [key,value] of Object.entries(journal||{})){
    const next=key.startsWith("MT5-")?redactSampleText(key):key;
    if(next!==key)changed=true;
    if(!(next in out)||next===key)out[next]=value;
  }
  return {journal:out,changed};
}
