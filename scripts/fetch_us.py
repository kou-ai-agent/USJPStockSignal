#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_us.py - 米国市場終値取得スクリプト
=========================================
毎朝 AM5:30 JST（前日米国市場終了後）に GitHub Actions から実行。
signal_master.json に定義された米国ティッカーの終値・騰落率を取得し、
data/us_close_YYYYMMDD.json として保存する。

出力ファイル例: data/us_close_20260609.json
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance が必要です。pip install yfinance")
    sys.exit(1)

# =====================
# 設定
# =====================
BASE_DIR        = Path(__file__).parent.parent   # リポジトリルート
DATA_DIR        = BASE_DIR / "data"
MASTER_JSON     = DATA_DIR / "signal_master.json"

JST             = timezone(timedelta(hours=9))
TODAY_JST       = datetime.now(JST).strftime("%Y%m%d")
OUTPUT_JSON     = DATA_DIR / f"us_close_{TODAY_JST}.json"

# 市場全体サマリー用（全テーマ共通で取得）
MARKET_TICKERS = {
    "sp500":  "^GSPC",
    "nasdaq": "^IXIC",
    "dow":    "^DJI",
    "vix":    "^VIX",
    "dxy":    "DX-Y.NYB",   # ドル指数
    "us10y":  "^TNX",       # 米10年債利回り
}

# ティッカー変換マップ（ADR・指数対応）
TICKER_MAP = {
    "SOX":  "^SOX",
    "ABB":  "ABBNY",
}


def load_signal_tickers(master_path: Path) -> dict:
    """signal_master.json から米国ティッカーを抽出（重複排除）"""
    with open(master_path, encoding="utf-8") as f:
        data = json.load(f)

    tickers = {}  # ticker -> name
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


def fetch_price(ticker: str) -> dict | None:
    """
    1ティッカーの終値・前日終値・騰落率を取得。
    取得失敗時は None を返す。
    """
    symbol = TICKER_MAP.get(ticker, ticker)
    try:
        info     = yf.Ticker(symbol).fast_info
        close    = info.get("lastPrice") or info.get("previousClose")
        prev     = info.get("regularMarketPreviousClose") or info.get("previousClose")

        if not close or float(close) <= 0:
            return None

        close = round(float(close), 4)
        prev  = round(float(prev), 4) if prev else None
        chg   = round((close - prev) / prev * 100, 2) if prev else None

        return {
            "ticker":     symbol,
            "close":      close,
            "prev_close": prev,
            "change_pct": chg,
        }
    except Exception as e:
        print(f"  WARN: {ticker} ({symbol}) 取得失敗 - {e}")
        return None


def main():
    print("=" * 60)
    print(f"fetch_us.py 開始: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    print("=" * 60)

    # ① マスターJSONからティッカー一覧を取得
    if not MASTER_JSON.exists():
        print(f"ERROR: {MASTER_JSON} が見つかりません。")
        sys.exit(1)

    signal_tickers = load_signal_tickers(MASTER_JSON)
    print(f"シグナルティッカー数: {len(signal_tickers)}")

    # ② 市場サマリー取得
    print("\n--- 市場サマリー取得 ---")
    market_summary = {}
    for key, symbol in MARKET_TICKERS.items():
        result = fetch_price(symbol)
        if result:
            market_summary[key] = result
            print(f"  OK  {key:8s} {symbol:12s} close={result['close']:>10.2f}  chg={result['change_pct']:>+6.2f}%")
        else:
            print(f"  NG  {key:8s} {symbol:12s} 取得失敗")
        time.sleep(0.2)

    # ③ シグナルティッカー取得
    print("\n--- シグナルティッカー取得 ---")
    signals = {}
    ok_count = 0
    for ticker, name in sorted(signal_tickers.items()):
        result = fetch_price(ticker)
        if result:
            signals[ticker] = result
            if name:
                result["name"] = name
            ok_count += 1
            print(f"  OK  {ticker:6s}  close={result['close']:>10.2f}  chg={result['change_pct']:>+6.2f}%")
        else:
            signals[ticker] = None
            print(f"  NG  {ticker:6s}  取得失敗")
        time.sleep(0.2)

    # ④ 出力JSON組み立て
    output = {
        "date":           TODAY_JST,
        "fetched_at":     datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "market_summary": market_summary,
        "signals":        signals,
        "stats": {
            "total":   len(signal_tickers),
            "ok":      ok_count,
            "ng":      len(signal_tickers) - ok_count,
        }
    }

    # ⑤ 保存
    DATA_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"完了: OK {ok_count} / NG {len(signal_tickers) - ok_count}")
    print(f"出力: {OUTPUT_JSON}")
    print("=" * 60)

    # NGが多い場合は終了コード1（GitHub Actionsで検知できる）
    if ok_count < len(signal_tickers) * 0.8:
        print("WARN: 取得成功率が80%未満です。")
        sys.exit(1)


if __name__ == "__main__":
    main()
