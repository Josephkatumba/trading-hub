import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.broker_calendar import BrokerCalendar
from research.intelligence_preview import evaluate
from market_intel.live import frames as load_frames
from quant_live.store import Store


def ts(date):
    return datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.c = BrokerCalendar.published()

    def test_verified_profile_required_and_unknown_symbol(self):
        bad = copy.deepcopy(self.c.profile)
        del bad['source']
        with self.assertRaises(ValueError):
            BrokerCalendar(bad)
        self.assertEqual(self.c.state('OTHER',ts('2026-10-20T12:00')), 'UNKNOWN')

    def test_daily_break_and_weekend_reopen(self):
        # Oct: GMT+3 server, so Monday 01:02 = Sunday 22:02 UTC.
        for stamp,state in [('2026-10-25T22:01','DAILY_BREAK'),
                            ('2026-10-25T22:02','SCHEDULED_OPEN'),
                            ('2026-10-24T12:00','WEEKEND_CLOSURE'),
                            ('2026-10-26T21:30','DAILY_BREAK'),
                            ('2026-10-26T20:58','UNKNOWN')]:
            self.assertEqual(self.c.state('XAUUSD',ts(stamp)),state)

    def test_dst_uses_broker_basis_not_fixed_utc(self):
        for stamp in ('2026-07-01T22:02','2026-12-01T23:02'):
            self.assertEqual(self.c.state('XAUUSD',ts(stamp)),'SCHEDULED_OPEN')
        self.assertEqual(self.c.state('XAUUSD',ts('2026-12-01T22:30')),'DAILY_BREAK')

    def test_crypto_saturday_maintenance_is_not_global_weekend_close(self):
        self.assertEqual(self.c.state('BTCUSD',ts('2026-10-23T21:30')),'DAILY_BREAK')
        self.assertEqual(self.c.state('BTCUSD',ts('2026-10-24T12:00')),'SCHEDULED_OPEN')

    def test_profile_overrides_and_partial_bars(self):
        profile=copy.deepcopy(self.c.profile)
        profile['date_overrides']={'XAUUSD': {'2026-10-20': {'sessions':[]}}}
        c=BrokerCalendar(profile)
        self.assertEqual(c.state('XAUUSD',ts('2026-10-20T12:00')),'DAILY_BREAK')
        # H4 at midnight server contains the 01:02 reopen; it is expected.
        start=ts('2026-10-25T21:00')
        self.assertIn(start,self.c.expected('XAUUSD',start,start+14400,'H4'))

    def test_missing_open_bar_not_excused_by_nearby_weekend(self):
        friday=ts('2026-10-23T17:00') # server 20:00 H4
        monday=ts('2026-10-25T21:00') # server Monday 00:00 H4
        rows=[{'utc':friday},{'utc':monday}]
        q=self.c.gaps('XAUUSD',rows,'H4',monday+14400)
        self.assertEqual(q['unexpected_missing'],0)
        self.assertEqual(q['normal_closed_intervals'],1)
        self.assertEqual(self.c.gaps('XAUUSD',rows,'H4',monday+28800)['unexpected_missing'],1)

    def test_h4_alignment_forming_stale_and_restart(self):
        now=ts('2026-10-21T12:00')
        stamps=self.c.expected('BTCUSD',now-80*14400,now,'H4')
        h4=[{'utc':t,'open':100,'high':101,'low':99,'close':100,'spread':.01} for t in stamps]
        # Store reload preserves closure filtering and revision exclusion.
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp)
            with store.db() as db:
                for b in h4:
                    db.execute('INSERT INTO candles VALUES (?,?,?,?)',('BTCUSD','H4',b['utc'],json.dumps(b)))
            a=load_frames(store,'BTCUSD',now,{'H4':80})['H4']
            b=load_frames(Store(tmp),'BTCUSD',now,{'H4':80})['H4']
            self.assertEqual(a,b)
            self.assertTrue(all(x['utc']+14400<=now for x in a))
            with store.db() as db:
                db.execute('INSERT INTO candle_revisions(symbol,tf,utc,body,at) VALUES (?,?,?,?,?)',
                           ('BTCUSD','H4',a[-1]['utc'],'{}',now))
            self.assertNotIn(a[-1],load_frames(Store(tmp),'BTCUSD',now,{'H4':80})['H4'])
        last=next(x for x in reversed(h4) if x['utc']+14400<=now)
        f={'H4':[dict(last)]}
        missing=evaluate('BTCUSD',{},None,now,calendar=self.c)
        self.assertIn('H4: insufficient history',missing['blockers'])
        f['H4'][0]['utc']+=60
        invalid=evaluate('BTCUSD',f,None,now,calendar=self.c)
        self.assertIn('misaligned broker timeframe',invalid['data_quality']['H4']['errors'])
        f['H4']=[dict(last,utc=last['utc']-3*14400)]
        self.assertIn('H4: stale or absent history',evaluate('BTCUSD',f,None,now,calendar=self.c)['blockers'])

    def test_calendar_never_waives_quote_freshness_during_closure(self):
        now=ts('2026-10-24T12:00')
        q={'bid':100,'ask':100.01,'tick_at':now-3600}
        r=evaluate('XAUUSD',{},q,now,calendar=self.c)
        self.assertEqual(r['market_state'],'WEEKEND_CLOSURE')
        self.assertEqual(r['quote_state'],'UNAVAILABLE_OR_STALE')

    def test_future_and_forming_h4_do_not_change_context(self):
        now=ts('2026-10-21T12:00')
        times=self.c.expected('BTCUSD',now-70*14400,now,'H4')
        history=[{'utc':t,'open':100,'high':101,'low':99,'close':100} for t in times if self.c.close_at(t,'H4')<=now]
        f={'H4':history}
        expected=evaluate('BTCUSD',f,None,now,calendar=self.c)
        forming=self.c.utc((self.c.clock(now)//14400)*14400)
        f['H4']=history+[{'utc':forming,'open':900,'high':999,'low':1,'close':998},
                         {'utc':forming+14400,'open':900,'high':999,'low':1,'close':998}]
        self.assertEqual(evaluate('BTCUSD',f,None,now,calendar=self.c),expected)

    def test_dst_ambiguous_wall_clock_does_not_choose_an_offset(self):
        # Broker wall-clock 08:30 repeats on the NY fall-back Sunday.
        server=ts('2026-11-01T08:30')
        self.assertIsNone(self.c.utc(server))


if __name__=='__main__':
    unittest.main()
