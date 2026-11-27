import sys
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intelligence_chart import intelligence_chart

class ChartPresentationTests(unittest.TestCase):
    def setUp(self):
        import threading
        self.main = Mock(WATCHLIST=['XAUUSD', 'BTCUSD', 'EURUSD'], _SCAN_LOCK=threading.RLock())
        self.main.ensure_mt5.return_value = (True, '')
        self.main.resolve_mt5_symbol.return_value = 'XAUUSD'
        self.main.mt5.copy_rates_from_pos.return_value = [{'time':1791800100,'open':100,'high':102,'low':99,'close':101}]
        self.main.mt5.symbol_info.return_value = Mock(digits=2,trade_tick_size=.01)
    def test_overview_never_reads_research(self):
        with patch.dict(sys.modules, {'main':self.main}), patch('observations.setup_episodes') as episodes, patch('outcomes.outcomes_for_setups') as outcomes, patch.dict('os.environ',{'TRADING_HUB_MT5_SOURCE_TIMEZONE':'UTC'}):
            result=intelligence_chart('XAUUSD','M15',100)
            self.assertEqual(len(result['candles']),1)
            self.assertEqual(result['episodes'],[])
            episodes.assert_not_called(); outcomes.assert_not_called()
    def test_research_only_returns_selected_instrument_and_frame(self):
        rows=[{'setup_id':'a','symbol':'XAUUSD','timeframe':'M15'}, {'setup_id':'b','symbol':'BTCUSD','timeframe':'M15'}, {'setup_id':'c','symbol':'XAUUSD','timeframe':'H1'}]
        with patch.dict(sys.modules, {'main':self.main}), patch('observations.setup_episodes',return_value=rows), patch('outcomes.outcomes_for_setups',return_value=[]) as outcomes, patch.dict('os.environ',{'TRADING_HUB_MT5_SOURCE_TIMEZONE':'UTC'}):
            result=intelligence_chart('XAUUSD','M15',100,True)
            self.assertEqual(result['episodes'],rows[:1])
            outcomes.assert_called_once()
            self.assertEqual(outcomes.call_args.args[0],['a'])
