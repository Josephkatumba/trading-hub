"""Internal preview: python -m market_intel XAUUSD|BTCUSD [--json]. Reads the live store; never sends anything."""
import json
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from storage_config import data_directory
    from quant_live.store import Store
    from market_intel.live import intelligence
    symbol = (sys.argv[1] if len(sys.argv) > 1 else 'XAUUSD').upper()
    intel = intelligence(Store(data_directory() / 'quant_live'), symbol)
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(intel, indent=1, default=str) if '--json' in sys.argv else intel['telegram_preview'])


if __name__ == '__main__':
    main()
