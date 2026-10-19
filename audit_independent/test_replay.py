import unittest
from run_audit import replay, metrics

class ReplayTests(unittest.TestCase):
    def signal(self, **kw):
        return dict(start=0,entry=100,stop_loss=99,take_profit=102,direction='LONG',symbol='NAS100',**kw)
    def bar(self,t,lo=99.5,hi=100.5,op=100):
        return dict(utc=t,open=op,low=lo,high=hi,close=100,spread=0)
    def run_path(self,bars,start=0):
        s=self.signal(); s['start']=start
        return replay(s,bars,[b['utc'] for b in bars],3600)
    def test_boundary_stop_included(self):
        self.assertEqual(self.run_path([self.bar(0,98),self.bar(60,hi=103)])['status'],'SL')
    def test_intraminute_entry_is_unknown(self):
        self.assertEqual(self.run_path([self.bar(0,98)],10)['status'],'ENTRY_MINUTE_UNKNOWN')
    def test_tie_ambiguous(self):
        self.assertEqual(self.run_path([self.bar(0,98,103)])['status'],'AMBIGUOUS')
    def test_gap_cannot_declare_first_hit(self):
        self.assertEqual(self.run_path([self.bar(0),self.bar(900,hi=103)])['status'],'GAP_UNKNOWN')
    def test_short_ask_barrier(self):
        s=self.signal(); s.update(direction='SHORT',stop_loss=101,take_profit=98)
        b=self.bar(0,99,100.9); b['spread']=0.2
        self.assertEqual(replay(s,[b],[0],60)['status'],'SL')
    def test_stop_gap_fill(self):
        result=self.run_path([self.bar(0,98,100,98)])
        self.assertEqual(result['r'],-2)
    def test_cost_sensitivity(self):
        s=self.signal(); s['symbol']='EURUSD'; b=self.bar(0,98)
        normal=replay(s,[b],[0],60); stress=replay(s,[b],[0],60,2)
        self.assertLess(stress['r'],normal['r'])

if __name__=='__main__': unittest.main()
