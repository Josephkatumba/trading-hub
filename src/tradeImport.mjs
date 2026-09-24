// Deterministic IDs and a safe merge for CSV trade imports.
//
// Rules:
// - IDs never depend on file length, header text or wall-clock time, so the
//   same row always gets the same ID. Preference: explicit id column, then the
//   broker ticket/position, then a content hash.
// - Identical rows inside one file are legitimate (e.g. partial fills), so the
//   content hash includes the row's occurrence index among identical rows.
// - Merge never deletes or rewrites an existing trade. An incoming row is
//   skipped if its ID already exists, or if its content matches an existing
//   trade that has not already been matched (occurrence-aware), which also
//   catches files imported earlier under the old ID scheme.
// - Bundled sample records (TH-/MT5- prefixes) are never mixed into imported
//   data; they are reported as excluded and stay restorable from the bundle.

const SAMPLE_ID_PREFIXES=["TH-","MT5-"];

export function tradeOrigin(trade){
  if(trade?.origin==="sample"||trade?.origin==="import")return trade.origin;
  const id=String(trade?.id||"");
  return SAMPLE_ID_PREFIXES.some(p=>id.startsWith(p))?"sample":"import";
}

const numKey=v=>{const n=Number(v);return Number.isFinite(n)?String(Math.round(n*1e8)/1e8):"";};
export function tradeFingerprint(t){
  return [String(t.account||"").trim().toLowerCase(),String(t.symbol||"").trim().toUpperCase(),String(t.side||"").toUpperCase(),
    String(t.time||"").trim(),numKey(t.entry),numKey(t.exit),numKey(t.volume),numKey(t.pnl)].join("|");
}

// cyrb53: small, stable, non-cryptographic 53-bit string hash.
export function stableHash(str){
  let h1=0xdeadbeef,h2=0x41c6ce57;
  for(let i=0;i<str.length;i++){const c=str.charCodeAt(i);h1=Math.imul(h1^c,2654435761);h2=Math.imul(h2^c,1597334677);}
  h1=Math.imul(h1^(h1>>>16),2246822507)^Math.imul(h2^(h2>>>13),3266489909);
  h2=Math.imul(h2^(h2>>>16),2246822507)^Math.imul(h1^(h1>>>13),3266489909);
  return (4294967296*(2097151&h2)+(h1>>>0)).toString(36);
}

// rows: parsed trades carrying optional `explicitId` / `ticket` fields.
export function assignImportIds(rows){
  const seen=new Map();
  return rows.map(({explicitId,ticket,...trade})=>{
    let id;
    if(explicitId)id=String(explicitId);
    else if(ticket)id="IMP-T-"+stableHash(String(trade.account||"").toLowerCase()+"|"+ticket);
    else{
      const fp=tradeFingerprint(trade),n=seen.get(fp)||0;seen.set(fp,n+1);
      id="IMP-C-"+stableHash(fp)+"-"+n;
    }
    return {...trade,id,origin:"import"};
  });
}

export function mergeImportedTrades(existing,incoming){
  const kept=existing.filter(t=>tradeOrigin(t)==="import");
  const sampleExcluded=existing.length-kept.length;
  const fpById=new Map(kept.map(t=>[String(t.id),tradeFingerprint(t)]));
  const ids=new Set(fpById.keys());
  const available=new Map();
  for(const fp of fpById.values())available.set(fp,(available.get(fp)||0)+1);
  const consume=fp=>{if(fp!=null&&available.get(fp))available.set(fp,available.get(fp)-1);};
  const added=[];let skippedExistingId=0,skippedDuplicateContent=0;
  for(const t of incoming){
    const fp=tradeFingerprint(t);
    if(ids.has(String(t.id))){skippedExistingId++;consume(fpById.get(String(t.id)));fpById.delete(String(t.id));continue;}
    if(available.get(fp)){consume(fp);skippedDuplicateContent++;continue;}
    ids.add(String(t.id));added.push(t);
  }
  return {trades:[...added,...kept],added:added.length,skippedExistingId,skippedDuplicateContent,sampleExcluded};
}
