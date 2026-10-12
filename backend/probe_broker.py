"""One observational scan in a disposable store. Never reads or writes live history."""
import json
import os
import tempfile
from pathlib import Path


def probe():
    with tempfile.TemporaryDirectory(prefix="tradeden-broker-probe-") as folder:
        os.environ["TRADING_HUB_DATA_DIR"] = folder
        os.environ["TRADING_HUB_AUTH_MODE"] = "private"
        os.environ["TRADING_HUB_PRIVATE_BETA"] = "0"
        import main
        try:
            markets = main.market_snapshot()
            _, scan, freshness = main.latest_scan()
            plans = [{"symbol": row["symbol"], "strategy": s.get("strategy_id"),
                      "entry": s.get("entry"), "stop": s.get("stop_loss"), "target": s.get("take_profit"),
                      "qualified": s.get("trade_qualified", False),
                      "pattern_confirmed": s.get("confirmed", False),
                      "net_rr": (s.get("qualification") or {}).get("executable_rr"),
                      "spread": row.get("spread"), "tick_age_seconds": row.get("tick_age_seconds"),
                      "failed": (s.get("qualification") or {}).get("failed", [])}
                     for row in markets for s in row.get("strategies", [])]
            chart = {"available": False}
            try:
                from intelligence_chart import intelligence_chart
                result = intelligence_chart("XAUUSD", "M15", 100)
                chart = {"available": True, "candles": len(result["candles"]), "time_basis": result["time_basis"]}
            except Exception:
                pass
            main.close_mt5()
            reconnected, _ = main.ensure_mt5()
            return {"scan_status": scan.get("status"), "market_count": len(markets), "reconnected": reconnected, "chart": chart,
                    "freshness": freshness.get("status"), "strategy_ids": sorted({s.get("strategy") for s in plans}),
                    "plans": plans, "execution_enabled": False, "live_history_modified": False}
        finally:
            main.close_mt5()


if __name__ == "__main__":
    print(json.dumps(probe(), indent=2))
