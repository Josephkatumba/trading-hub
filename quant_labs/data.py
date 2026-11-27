"""Content-addressed read-only snapshots of existing broker caches."""
import gzip
import hashlib
import json
import os
from pathlib import Path

def digest(content):return hashlib.sha256(content).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def snapshot(cache,destination):
    cache,destination=Path(cache).resolve(),Path(destination).resolve()
    original=json.loads((cache/'manifest.json').read_text())
    from datetime import datetime
    from .evaluation.v1.foundation import validate_bars
    files={};quality={};durations={'M1':60,'M15':900,'H1':3600,'H4':14400,'D1':86400}
    # Content-addressed blobs, never modified or overwritten after creation.
    blobs=destination/'blobs';blobs.mkdir(parents=True,exist_ok=True)
    for file in sorted(cache.glob('*.json.gz')):
        content=file.read_bytes();sha=digest(content);target=blobs/(sha+'.gz')
        timeframe=file.name.split('_')[-1].split('.')[0]
        accepted,rejected=validate_bars(json.loads(gzip.decompress(content)),durations[timeframe],datetime.fromisoformat(original['end']).timestamp())
        quality[file.name]={'validated_bars':len(accepted),'excluded':rejected,'gaps':sum(b['utc']-a['utc']!=durations[timeframe] for a,b in zip(accepted,accepted[1:]))}
        if not target.exists():
            with target.open('xb') as handle:handle.write(content)
            target.chmod(0o444)
        elif digest(target.read_bytes())!=sha:raise ValueError('shared data blob integrity failure')
        files[file.name]={'sha256':sha,'bytes':len(content)}
    manifest={'schema':'market-snapshot-v1','files':files,'validation':quality,'broker_provenance':original,
              'session_information':'bar timestamps and gaps retained; broker session calendar unverified',
              'fields':'raw epoch, UTC, bid OHLC, broker-recorded price-unit spread, tick volume if present'}
    dataset=digest(canonical(manifest));path=destination/(dataset+'.json')
    if not path.exists():
        with path.open('xb') as handle:handle.write(canonical(manifest))
        path.chmod(0o444)
    return dataset

class SharedData:
    def __init__(self,root,dataset):
        self.root=Path(root).resolve()
        if len(dataset)!=64 or any(c not in '0123456789abcdef' for c in dataset):raise ValueError('invalid dataset ID')
        raw=(self.root/(dataset+'.json')).read_bytes()
        if digest(raw)!=dataset:raise ValueError('dataset manifest changed')
        self.manifest=json.loads(raw);self.dataset=dataset
    def read(self,symbol,timeframe):
        key=f'{symbol}_{timeframe}.json.gz'
        item=self.manifest['files'].get(key)
        if not item:return []
        path=self.root/'blobs'/(item['sha256']+'.gz');raw=path.read_bytes()
        if digest(raw)!=item['sha256']:raise ValueError('shared market data changed')
        from datetime import datetime
        from .evaluation.v1.foundation import validate_bars
        durations={'M1':60,'M15':900,'H1':3600,'H4':14400,'D1':86400}
        return validate_bars(json.loads(gzip.decompress(raw)),durations[timeframe],datetime.fromisoformat(self.manifest['broker_provenance']['end']).timestamp())[0]
    def metadata(self,symbol):return self.manifest['broker_provenance']['symbols'][symbol]['meta']
