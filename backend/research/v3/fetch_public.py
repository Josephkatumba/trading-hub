"""Fetch the public datasets used by TradeDen V3 (no accounts, no keys).

    python -m research.v3.fetch_public          (from backend/)

Writes backend/data/research/v3/raw/ and appends one provenance row per file to
backend/data/research/v3/sources.jsonl (URL, UTC time, bytes, sha256).

Sources:
  FRED   - daily yields, real yields, breakevens, broad dollar index, fed funds; monthly macro series
  ALFRED - release dates (CPI, Employment Situation, Personal Income & Outlays, FOMC press release)
           and the value of each series AS FIRST PUBLISHED on each release date (no revisions = no look-ahead)
  CFTC   - Disaggregated Futures-Only Commitments of Traders history (2006 onward)
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2] / "data" / "research" / "v3"
RAW = ROOT / "raw"
UA = {"User-Agent": "Mozilla/5.0 (research-script)"}

FRED_DAILY = ["DGS2", "DGS10", "DFII10", "T10YIE", "DTWEXBGS", "DFF"]
FRED_MONTHLY = ["CPIAUCSL", "CPILFESL", "PAYEMS", "PCEPI", "PCEPILFE", "UNRATE"]
RELEASES = {"CPI": 10, "NFP": 50, "PCE": 54}
FIRST_RELEASE_SERIES = {"CPI": ["CPIAUCSL", "CPILFESL"], "NFP": ["PAYEMS", "UNRATE"], "PCE": ["PCEPI", "PCEPILFE"]}
COT_FILES = ["fut_disagg_txt_hist_2006_2016.zip"] + [f"fut_disagg_txt_{y}.zip" for y in range(2017, datetime.now().year + 1)]


def get(url: str, retries: int = 3) -> bytes:
    for k in range(retries):
        try:
            # curl, not Python HTTP clients: FRED stalls Python TLS clients but serves curl normally
            res = subprocess.run(["curl", "-sSfL", "-m", "120", "-A", UA["User-Agent"], url], capture_output=True, check=True)
            return res.stdout
        except Exception:
            if k == retries - 1:
                raise
            time.sleep(2 + 3 * k)
    raise RuntimeError(url)


def save(name: str, data: bytes, url: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / name).write_bytes(data)
    with (ROOT / "sources.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"file": name, "url": url, "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}) + "\n")


def release_dates(rid: int) -> list[str]:
    url = f"https://alfred.stlouisfed.org/release/downloaddates?rid={rid}&ff=txt"
    txt = get(url).decode("utf-8", "replace")
    dates = [ln.strip() for ln in txt.splitlines() if len(ln.strip()) == 10 and ln.strip()[4] == "-" and ln.strip()[:2] in ("19", "20")]
    return sorted(set(dates))


def _vintage_frame(series: str, chunk: list[str]) -> pd.DataFrame | None:
    url = ("https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=" + ",".join([series] * len(chunk))
           + "&vintage_date=" + ",".join(chunk))
    try:
        return pd.read_csv(io.BytesIO(get(url)))
    except Exception:
        return None


def first_release_values(series: str, dates: list[str]) -> pd.DataFrame:
    """For each release date: the latest observation in THAT vintage = first print, plus earlier values as known then.
    Columns are matched to dates by their names (SERIES_YYYYMMDD), never by position."""
    rows = []
    for k in range(0, len(dates), 10):          # ALFRED silently returns at most 12 vintages per request
        chunk = dates[k:k + 10]
        df = _vintage_frame(series, chunk)
        got = set() if df is None else {c.rsplit("_", 1)[-1] for c in df.columns[1:]}
        frames = [df] if df is not None else []
        frames += [f for f in (_vintage_frame(series, [d]) for d in chunk if d.replace("-", "") not in got) if f is not None]
        for frame in frames:
            for col in frame.columns[1:]:
                tag = col.rsplit("_", 1)[-1]
                if not (len(tag) == 8 and tag.isdigit()):
                    continue
                d = f"{tag[:4]}-{tag[4:6]}-{tag[6:]}"
                s = frame[[frame.columns[0], col]].dropna()
                if len(s) < 13:
                    continue
                rows.append({"release_date": d, "series": series, "period": s.iloc[-1, 0], "first_value": float(s.iloc[-1, 1]),
                             "prior_value_then": float(s.iloc[-2, 1]), "prior2_value_then": float(s.iloc[-3, 1]),
                             "prior3_value_then": float(s.iloc[-4, 1]), "value_12m_ago_then": float(s.iloc[-13, 1])})
        time.sleep(0.5)
    out = pd.DataFrame(rows).drop_duplicates("release_date")
    # keep only vintages that actually added a new period (a true release of this series)
    return out[out["period"] != out["period"].shift(1)].reset_index(drop=True)


def fomc_statement_dates(first_year: int = 2010) -> list[dict]:
    """Scheduled FOMC meeting statement dates from federalreserve.gov (unscheduled actions excluded)."""
    import re
    months = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                          "September", "October", "November", "December"], 1)}
    pages = ["https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"] + [
        f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm" for y in range(first_year, 2021)]
    out = {}
    for url in pages:
        html = get(url).decode("utf-8", "replace")
        save("fed_" + url.rsplit("/", 1)[-1], html.encode(), url)
        statements = set(re.findall(r"monetary(\d{8})a\.htm", html))
        scheduled = set()
        for mon, d1, d2, yr in re.findall(r"([A-Z][a-z]+)(?:/[A-Z][a-z]+)? (\d{1,2})(?:-(\d{1,2}))? Meeting - (\d{4})", html):
            if mon in months:
                scheduled.add(f"{yr}{months[mon]:02d}{int(d2 or d1):02d}")
        for block in re.split(r"(\d{4}) FOMC Meetings", html)[1:]:
            pass
        for yr, body in zip(re.findall(r"(\d{4}) FOMC Meetings", html), re.split(r"\d{4} FOMC Meetings", html)[1:]):
            for mon, dates in re.findall(r"<strong>([A-Z][a-z]+)(?:/[A-Z][a-z]+)?</strong></div>\s*<div class=\"fomc-meeting__date[^>]*>([^<]+)</div>", body):
                if "unscheduled" in dates.lower() or mon not in months:
                    continue
                m = re.search(r"(\d{1,2})(?:-(\d{1,2}))?", dates)
                if m:
                    scheduled.add(f"{yr}{months[mon]:02d}{int(m.group(2) or m.group(1)):02d}")
        for d in statements & scheduled:
            out[d] = {"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "source": url}
        time.sleep(0.5)
    return sorted(out.values(), key=lambda x: x["date"])


def main(start: str = "2006-01-01") -> None:
    for sid in FRED_DAILY + FRED_MONTHLY:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
        save(f"fred_{sid}.csv", get(url), url)
        print("FRED", sid)
    rel = {}
    for name, rid in RELEASES.items():
        d = [x for x in release_dates(rid) if x >= start]
        rel[name] = d
        print("release dates", name, len(d), d[0] if d else None, d[-1] if d else None)
    rel["FOMC"] = [x["date"] for x in fomc_statement_dates()]
    print("FOMC scheduled statements", len(rel["FOMC"]), rel["FOMC"][:2], rel["FOMC"][-2:])
    blob = json.dumps(rel, indent=1).encode()
    save("release_dates.json", blob, "ALFRED release dates rid 10/50/54 + federalreserve.gov FOMC calendars")
    for ev, series in FIRST_RELEASE_SERIES.items():
        for sid in series:
            df = first_release_values(sid, rel[ev])
            save(f"alfred_first_{sid}.csv", df.to_csv(index=False).encode(), f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={sid} (vintages = {ev} release dates)")
            print("first release", sid, len(df))
    for f in COT_FILES:
        url = f"https://www.cftc.gov/files/dea/history/{f}"
        try:
            data = get(url)
        except Exception as exc:  # the current-year file may not exist early in January
            print("skip", f, exc)
            continue
        z = zipfile.ZipFile(io.BytesIO(data))
        frames = [pd.read_csv(z.open(n), low_memory=False) for n in z.namelist()]
        df = pd.concat(frames, ignore_index=True)
        gold = df[df["CFTC_Contract_Market_Code"].astype(str).str.strip() == "088691"]
        save(f"cot_gold_{f.replace('.zip', '.csv')}", gold.to_csv(index=False).encode(), url)
        print("COT", f, len(gold))


if __name__ == "__main__":
    main()
