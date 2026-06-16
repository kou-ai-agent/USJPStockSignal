#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_us.py - US market closing price fetcher
Runs every morning AM5:30 JST via GitHub Actions.
Outputs: data/us_close_YYYYMMDD.json
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance required. pip install yfinance")
    sys.exit(1)

BASE_DIR    = Path(__file__).parent.parent
DATA_DIR    = BASE_DIR / "data"
MASTER_JSON = DATA_DIR / "signal_master.json"

JST       = timezone(timedelta(hours=9))
TODAY_JST = datetime.now(JST).strftime("%Y%m%d")
OUTPUT_JSON = DATA_DIR / f"us_close_{TODAY_JST}.json"

MARKET_TICKERS = {
    "sp500":  "^GSPC",
    "nasdaq": "^IXIC",
    "dow":    "^DJI",
    "vix":    "^VIX",
    "dxy":    "DX-Y.NYB",
    "us10y":  "^TNX",
}

TICKER_MAP = {
    "SOX": "^SOX",
    "ABB": "ABBNY",
}


def load_signal_tickers(master_path):
    with open(master_path, encoding="utf-8") as f:
        data = json.load(f)
    tickers = {}
    for t in data["themes"]:
        sig  = t["us_signal"]
        prim = sig.get("primary", {})
        pt   = prim.get("ticker", "").strip()
        if pt:
            tickers[pt] = prim.get("name", "")
        for sub in sig.get("sub", []):
            sub = sub.strip()
            if sub and sub not in tickers:
                tickers[sub] = ""
    return tickers


def fetch_price(ticker):
    symbol = TICKER_MAP.get(ticker, ticker)
    try:
        info  = yf.Ticker(symbol).fast_info
        close = info.get("lastPrice") or info.get("previousClose")
        prev  = info.get("regularMarketPreviousClose") or info.get("previousClose")
        if not close or float(close) <= 0:
            return None
        close = round(float(close), 4)
        prev_f = float(prev) if prev is not None else None
        prev = round(prev_f, 4) if (prev_f is not None and not math.isnan(prev_f)) else None
        if prev:
            chg = (close - prev) / prev * 100
            chg = None if math.isnan(chg) else round(chg, 2)
        else:
            chg = None
        return {"ticker": symbol, "close": close, "prev_close": prev, "change_pct": chg}
    except Exception as e:
        print(f"  WARN: {ticker} ({symbol}) failed - {e}")
        return None


def fmt_chg(val):
    if val is None:
        return "   N/A%"
    return f"{val:>+6.2f}%"


def main():
    print("=" * 60)
    print(f"fetch_us.py start: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    print("=" * 60)

    if not MASTER_JSON.exists():
        print(f"ERROR: {MASTER_JSON} not found.")
        sys.exit(1)

    signal_tickers = load_signal_tickers(MASTER_JSON)
    print(f"Signal tickers: {len(signal_tickers)}")

    print("\n--- Market Summary ---")
    market_summary = {}
    for key, symbol in MARKET_TICKERS.items():
        result = fetch_price(symbol)
        if result:
            market_summary[key] = result
            print(f"  OK  {key:8s} {symbol:12s} close={result['close']:>10.2f}  chg={fmt_chg(result['change_pct'])}")
        else:
            print(f"  NG  {key:8s} {symbol:12s} failed")
        time.sleep(0.2)

    print("\n--- Signal Tickers ---")
    signals   = {}
    ok_count  = 0
    for ticker, name in sorted(signal_tickers.items()):
        result = fetch_price(ticker)
        if result:
            signals[ticker] = result
            if name:
                result["name"] = name
            ok_count += 1
            print(f"  OK  {ticker:6s}  close={result['close']:>10.2f}  chg={fmt_chg(result['change_pct'])}")
        else:
            signals[ticker] = None
            print(f"  NG  {ticker:6s}  failed")
        time.sleep(0.2)

    output = {
        "date":           TODAY_JST,
        "fetched_at":     datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "market_summary": market_summary,
        "signals":        signals,
        "stats": {"total": len(signal_tickers), "ok": ok_count, "ng": len(signal_tickers) - ok_count}
    }

    DATA_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"Done: OK {ok_count} / NG {len(signal_tickers) - ok_count}")
    print(f"Output: {OUTPUT_JSON}")
    print("=" * 60)

    if ok_count < len(signal_tickers) * 0.8:
        print("WARN: Success rate below 80%")
        sys.exit(1)


if __name__ == "__main__":
    main()
