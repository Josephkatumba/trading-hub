"""Measure offline overlay cost after input loading, with bounded candle windows."""
import json
from pathlib import Path
import sys
import time
import tracemalloc

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'backend'))
from research.phase2_validation import SharedData, DATASET, COUNTS, TF, window, epoch
from research.broker_calendar import BrokerCalendar
from research.intelligence_preview import evaluate


if __name__=='__main__':
    d=SharedData(ROOT/'quant_labs/state/shared',DATASET)
    f={tf:d.read('XAUUSD',tf) for tf in COUNTS}
    clocks={tf:[b['utc']+TF[tf] for b in rows] for tf,rows in f.items()}
    now=epoch('2026-06-10T15:30')
    f=window(f,clocks,now);q={'bid':f['M15'][-1]['close'],'ask':f['M15'][-1]['close']+.01,'tick_at':now}
    c=BrokerCalendar.published()
    tracemalloc.start();start=time.perf_counter()
    evaluate('XAUUSD',f,q,now,calendar=c)
    cold=time.perf_counter()-start
    start=time.perf_counter()
    for _ in range(20): evaluate('XAUUSD',f,q,now,calendar=c)
    warm=(time.perf_counter()-start)/20
    current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    r={'cold_seconds':cold,'mean_warm_seconds_20_repeats':warm,'python_peak_allocation_bytes':peak,
       'python_retained_allocation_bytes':current,'calendar_cache':str(c.day_slots.cache_info()),
       'limits':'One Gold context; tracing overhead included; input loading and full historical data allocations excluded; no production measurement or RSS claim.'}
    with Path(sys.argv[1]).open('x') as h:json.dump(r,h,indent=1)
    print(json.dumps(r,indent=1))
