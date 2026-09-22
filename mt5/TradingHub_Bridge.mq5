#property strict
#property version   "1.0"
#property description "Trading Hub MT5 bridge heartbeat. Read-only: never sends orders."

input int    HeartbeatSeconds = 5;
input string BridgeSymbol    = "XAUUSD";

string FileName = "trading_hub_heartbeat.json";

int OnInit()
{
   EventSetTimer(MathMax(1, HeartbeatSeconds));
   WriteHeartbeat();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   WriteHeartbeat();
}

void WriteHeartbeat()
{
   MqlTick tick;
   bool tick_ok = SymbolInfoTick(BridgeSymbol, tick);

   int handle = FileOpen(
      FileName,
      FILE_COMMON | FILE_WRITE | FILE_TXT | FILE_ANSI
   );

   if(handle == INVALID_HANDLE)
      return;

   string server = AccountInfoString(ACCOUNT_SERVER);
   long login = AccountInfoInteger(ACCOUNT_LOGIN);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   long build = TerminalInfoInteger(TERMINAL_BUILD);

   string bid = tick_ok ? DoubleToString(tick.bid, 8) : "0";
   string ask = tick_ok ? DoubleToString(tick.ask, 8) : "0";

   string json =
      "{"
      + "\"bridge\":\"Trading Hub MT5 Bridge\","
      + "\"version\":\"1.0\","
      + "\"timestamp\":\"" + TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS) + "\","
      + "\"login\":" + IntegerToString(login) + ","
      + "\"server\":\"" + server + "\","
      + "\"terminal_build\":" + IntegerToString((int)build) + ","
      + "\"symbol\":\"" + BridgeSymbol + "\","
      + "\"bid\":" + bid + ","
      + "\"ask\":" + ask + ","
      + "\"balance\":" + DoubleToString(balance, 2) + ","
      + "\"equity\":" + DoubleToString(equity, 2) + ","
      + "\"execution_enabled\":false"
      + "}";

   FileWriteString(handle, json);
   FileClose(handle);
}
