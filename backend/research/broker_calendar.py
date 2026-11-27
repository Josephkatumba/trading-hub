"""Versioned, injectable broker schedules; never discover closures from missing bars.

Published indicative hours can classify expected closures for offline analysis.
They never excuse a stale quote, certify holidays, or authorize trading.
All schedules live in evidence-bearing JSON, not scanner constants.
"""
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
from market_intel.rules import offset, TF


class BrokerCalendar:
    def __init__(self, profile):
        self.profile = json.loads(json.dumps(profile))
        if self.profile['schema'] != 'broker-calendar-v1' or self.profile['server_basis'] != 'America/New_York+07:00':
            raise ValueError('unsupported calendar schema or clock basis')
        if not self.profile.get('source') or not self.profile.get('authority'):
            raise ValueError('calendar provenance required')
        for spec in self.profile['symbols'].values():
            for field in ('weekly', 'uncertain'):
                for ranges in spec.get(field, {}).values():
                    for a, b in ranges:
                        if not 0 <= a < b <= 1440:
                            raise ValueError('invalid session minutes')

    @classmethod
    def published(cls):
        return cls(json.loads(Path(__file__).with_name('broker_sessions.json').read_text()))

    def clock(self, utc):
        return utc + offset('US', utc) + 7*3600

    def utc(self, server):
        # Resolve against both candidate offsets; ambiguous/nonexistent wall times
        # remain unknown rather than silently choosing a side of a DST transition.
        candidates = [server-h*3600 for h in (2,3) if self.clock(server-h*3600) == server]
        return candidates[0] if len(candidates) == 1 else None

    def state(self, symbol, utc):
        local = datetime.fromtimestamp(self.clock(utc), timezone.utc)
        key, date = str(local.weekday()), local.date().isoformat()
        spec = self.profile['symbols'].get(symbol)
        if spec is None:
            return 'UNKNOWN'
        override = self.profile.get('date_overrides', {}).get(symbol, {}).get(date)
        if override is not None:
            ranges, uncertain = override['sessions'], override.get('uncertain', [])
        else:
            ranges, uncertain = spec['weekly'].get(key, []), spec.get('uncertain', {}).get(key, [])
        minute = local.hour*60 + local.minute + local.second/60
        if any(a <= minute < b for a,b in uncertain):
            return 'UNKNOWN'
        if any(a <= minute < b for a,b in ranges):
            return 'SCHEDULED_OPEN'
        return 'WEEKEND_CLOSURE' if not ranges and local.weekday() >= 5 else 'DAILY_BREAK'

    def aligned(self, utc, tf):
        return self.clock(utc) % TF[tf] == 0

    def close_at(self, utc, tf):
        # D1/H4 grid follows broker wall-clock, including DST boundaries.
        return self.utc(self.clock(utc)+TF[tf])

    @lru_cache(maxsize=8192)
    def day_slots(self, symbol, server_day, tf):
        step = TF[tf]
        slots = []
        for local in range(server_day*86400, (server_day+1)*86400, step):
            start, end = self.utc(local), self.utc(local+step)
            if start is None or end is None:
                continue
            # A partly open H1/H4/D1 bar is expected even if its open falls
            # inside maintenance. Uncertain minutes conservatively expect data.
            if any(self.state(symbol, t) in ('SCHEDULED_OPEN','UNKNOWN') for t in range(int(start), int(end),60)):
                slots.append(start)
        return tuple(slots)

    def expected(self, symbol, start, end, tf):
        first = int(self.clock(start)//86400)-1
        last = int(self.clock(end)//86400)+1
        return [t for day in range(first,last+1) for t in self.day_slots(symbol,day,tf) if start <= t < end]

    def gaps(self, symbol, bars, tf, now):
        if not bars:
            return {'unexpected_missing': 0, 'normal_closed_intervals': 0, 'stale': True}
        times = {b['utc'] for b in bars}
        expected = self.expected(symbol, bars[0]['utc'], now, tf)
        completed = [t for t in expected if self.close_at(t,tf) is not None and self.close_at(t,tf) <= now]
        missing = sum(t not in times for t in completed)
        normal = sum(b['utc']-a['utc'] != TF[tf] and not self.expected(symbol,a['utc']+TF[tf],b['utc'],tf)
                     for a,b in zip(bars,bars[1:]))
        latest = completed[-1] if completed else None
        return {'unexpected_missing': missing, 'normal_closed_intervals': normal,
                'stale': latest is not None and latest not in times}
