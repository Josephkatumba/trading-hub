"""Redacted beta acceptance checks; never displays configuration values or secrets."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen
from sqlalchemy.engine import make_url


def configuration_checks():
    origin = urlsplit(os.getenv("TRADING_HUB_PUBLIC_ORIGIN", ""))
    issuer = urlsplit(os.getenv("TRADING_HUB_OIDC_ISSUER", ""))
    subjects = []
    try:
        subjects = json.loads(os.getenv("TRADING_HUB_BETA_SUBJECTS", "[]"))
    except ValueError:
        pass
    try:
        database = make_url(os.getenv("TRADING_HUB_DATABASE_URL", ""))
        db_valid = (database.drivername == "postgresql+psycopg" and bool(database.database) and
                    bool(database.username) and bool(database.password) and
                    (database.host in {"localhost", "127.0.0.1", "::1"} or database.query.get("sslmode") == "verify-full"))
    except Exception:
        db_valid = False
    data = os.getenv("TRADING_HUB_DATA_DIR", "")
    try:
        costs = json.loads(os.getenv("TRADING_HUB_COSTS_BY_SYMBOL", "{}"))
        import math
        cost_valid = isinstance(costs, dict) and all(math.isfinite(float(v)) and float(v) >= 0 for v in costs.values())
        minimum = float(os.getenv("TRADING_HUB_MIN_NET_RR", "1.5"))
        cost_valid = cost_valid and math.isfinite(minimum) and minimum >= 1.5
        global_cost = float(os.getenv("TRADING_HUB_ROUND_TRIP_COST_PRICE", "0"))
        cost_valid = cost_valid and math.isfinite(global_cost) and global_cost >= 0
    except (ValueError, TypeError):
        cost_valid = False
    return {
        "oidc_mode": os.getenv("TRADING_HUB_AUTH_MODE") == "oidc",
        "private_beta": os.getenv("TRADING_HUB_PRIVATE_BETA") == "1",
        "invitation_allowlist": isinstance(subjects, list) and bool(subjects) and all(isinstance(s, str) and s for s in subjects),
        "https_origin": origin.scheme == "https" and bool(origin.hostname) and not origin.username and origin.path in {"", "/"} and not origin.query and not origin.fragment,
        "https_issuer": issuer.scheme == "https" and bool(issuer.hostname) and not issuer.username and not issuer.query and not issuer.fragment,
        "oidc_credentials": bool(os.getenv("TRADING_HUB_OIDC_CLIENT_ID")) and bool(os.getenv("TRADING_HUB_OIDC_CLIENT_SECRET")),
        "session_secret": len(os.getenv("TRADING_HUB_SESSION_SECRET", "")) >= 32,
        "postgresql_secure_connection": db_valid,
        "persistent_data_path": bool(data) and Path(data).is_absolute() and "onedrive" not in data.lower(),
        "broker_time_basis": bool(os.getenv("TRADING_HUB_MT5_SOURCE_TIMEZONE")),
        "explicit_mt5_terminal": bool(os.getenv("TRADING_HUB_MT5_TERMINAL_PATH")) and Path(os.getenv("TRADING_HUB_MT5_TERMINAL_PATH", "")).is_file(),
        "reviewed_costs": os.getenv("TRADING_HUB_EXECUTION_COSTS_REVIEWED") == "1" and cost_valid,
    }


def online_checks():
    checks = {"oidc_discovery": False, "postgresql_schema": False}
    try:
        issuer = os.environ["TRADING_HUB_OIDC_ISSUER"].rstrip("/") + "/"
        with urlopen(issuer + ".well-known/openid-configuration", timeout=5) as response:
            metadata = json.loads(response.read(65536))
        checks["oidc_discovery"] = metadata.get("issuer") == issuer and all(
            urlsplit(metadata.get(k, "")).scheme == "https" for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"))
    except Exception:
        pass
    try:
        from commercial_store import CommercialStore
        db = CommercialStore(os.environ["TRADING_HUB_DATABASE_URL"])
        try:
            checks["postgresql_schema"] = db.healthy()
        finally:
            db.engine.dispose()
    except Exception:
        pass
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    checks = configuration_checks()
    if args.online and all(checks.values()):
        checks.update(online_checks())
    print(json.dumps({"ready": all(checks.values()), "checks": checks}, indent=2))
    raise SystemExit(0 if all(checks.values()) else 1)
