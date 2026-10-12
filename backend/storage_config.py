"""One durable store location; preserve the legacy default for local users."""
import os
from pathlib import Path


def data_directory() -> Path:
    configured = os.getenv("TRADING_HUB_DATA_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError("TRADING_HUB_DATA_DIR must be an absolute path")
        return path
    return Path(__file__).resolve().parent / "data"
