"""Transparent research commission proxies, never represented as broker-confirmed fees."""
SCHEDULE={'EURUSD':.00007,'GBPUSD':.00007,'USDJPY':.007,'USDCHF':.00007,'USDCAD':.00007,'AUDUSD':.00007,'NZDUSD':.00007,
          'EURJPY':.007,'GBPJPY':.007,'XAUUSD':.07,'XAGUSD':.0014,'BTCUSD':0.,'ETHUSD':0.,'NAS100':0.,'US500':0.,'GER40':0.}
def commission_price(symbol):return SCHEDULE.get(symbol)
