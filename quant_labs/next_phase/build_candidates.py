"""Record predeclared Codex exit variants and immutable executable research manifests."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];base=ROOT/'quant_labs/state/labs/codex/strategies'
template=(base/'trend_reclaim_r2/model.py').read_text(encoding='utf-8')
markets=['EURUSD','XAUUSD','BTCUSD']
rows=[]
for key,target in [(f'trend_reclaim_r{r}',r) for r in (2,3,4,5,7,9)]+[('range_sweep_reversion',None)]:
    folder=base/key;folder.mkdir(exist_ok=True)
    if target is not None:
        source=template.replace('TARGET_NET_R = 2',f'TARGET_NET_R = {target}')
        (folder/'model.py').write_text(source,encoding='utf-8')
    else:source=(folder/'model.py').read_text(encoding='utf-8')
    manifest={'lab':'codex','key':key,'version':'0.1.0','name':key.replace('_',' ').title(),'timeframe':'M15',
              'requirements':{'M15':300,'H1':160,'M1':120},'instruments':markets,'classification':'EXPERIMENTAL',
              'entry_type':'MARKET_PAPER_QUOTE','target_net_r':target,'declared_trials_in_phase':7,
              'research_stage':'OFFLINE_EVALUATION_ONLY_NOT_LIVE_REGISTERED',
              'hypothesis':'Persistent higher-timeframe trend pullback reclaim' if target else 'Failed range escape in a low-persistence regime',
              'planned_rr':'Cost-buffered net-R objective '+str(target) if target else 'Observed opposite range boundary, >=2 net planned R and <=9 gross R',
              'risk_model':'Structural stop, 0.5–3 ATR; fixed barriers and horizon; no execution',
              'known_limitations':'Already-exposed historical sample; quote/spread/commission proxies; gap, financing, selection and regime risks; no certified edge.',
              'authorship':{'lab':'codex','session_reference':'Actual Codex task 01a155be-ad08-7922-bb69-2762009efd16; CEO next development phase',
                            'statement':'Independently authored by this Codex session; six declared exit variants plus one range model. No Claude/Kimi authorship.'}}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    rows.append({'key':key,'version':manifest['version'],'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'target_net_r':target,'manifest':str(folder/'manifest.json'),'source':str(folder/'model.py')})
(Path(__file__).parent/'candidates.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print(json.dumps(rows,indent=2))
