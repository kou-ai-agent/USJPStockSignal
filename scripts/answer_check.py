#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
answer_check.py - Answer check script
Runs every PM4:15 JST via GitHub Actions.
Outputs: data/answer_YYYYMMDD.json, data/score_history.json, data/index.json
"""

import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance required. pip install yfinance")
    sys.exit(1)

BASE_DIR      = Path(__file__).parent.parent
DATA_DIR      = BASE_DIR / "data"
MASTER_JSON   = DATA_DIR / "signal_master.json"

JST           = timezone(timedelta(hours=9))
TODAY_JST     = datetime.now(JST).strftime("%Y%m%d")
TODAY_DASH    = datetime.now(JST).strftime("%Y-%m-%d")

PREDICT_JSON  = DATA_DIR / f"predict_{TODAY_JST}.json"
OUTPUT_JSON   = DATA_DIR / f"answer_{TODAY_JST}.json"
SCORE_HISTORY = DATA_DIR / "score_history.json"
INDEX_JSON    = DATA_DIR / "index.json"

ANOMALY_THRESHOLD = 5.0
ANOMALY_MAJORITY  = 6
DIRECTION_THRESHOLD = 0.3


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_jp_price(code):
    symbol = f"{code}.T"
    try:
        info  = yf.Ticker(symbol).fast_info
        close = info.get("lastPrice") or info.get("previousClose")
        prev  = info.get("regularMarketPreviousClose") or info.get("previousClose")
        if not close or not prev or float(prev) == 0:
            return None
        chg = (float(close) - float(prev)) / float(prev) * 100
        if math.isnan(chg):
            return None
        return round(chg, 2)
    except Exception as e:
        print(f"  WARN: {symbol} failed - {e}")
        return None


def calc_theme_result(stocks):
    details = []
    for s in stocks:
        chg = s.get("change_pct")
        details.append({"code": s["code"], "name": s["name"], "change_pct": chg, "fetched": chg is not None})

    fetched = [d for d in details if d["fetched"]]
    if not fetched:
        return {"avg_chg": None, "direction": None, "used_count": 0, "excluded_count": 0, "anomaly_mode": False, "details": details}

    anomaly_stocks = [d for d in fetched if abs(d["change_pct"]) > ANOMALY_THRESHOLD]
    anomaly_mode   = len(anomaly_stocks) >= ANOMALY_MAJORITY

    if anomaly_mode:
        used     = fetched
        excluded = 0
    else:
        used     = [d for d in fetched if abs(d["change_pct"]) <= ANOMALY_THRESHOLD]
        excluded = len(anomaly_stocks)
        if not used:
            used        = fetched
            excluded    = 0
            anomaly_mode = True

    avg_chg   = sum(d["change_pct"] for d in used) / len(used)
    direction = "Long" if avg_chg > DIRECTION_THRESHOLD else "Short" if avg_chg < -DIRECTION_THRESHOLD else "Neutral"

    return {
        "avg_chg":        round(avg_chg, 2),
        "direction":      direction,
        "used_count":     len(used),
        "excluded_count": excluded,
        "anomaly_mode":   anomaly_mode,
        "details":        details,
    }


def judge(prediction, actual):
    if actual is None:
        return "skip"
    if prediction == "Neutral" or actual == "Neutral":
        return "skip"
    return "correct" if prediction == actual else "incorrect"


def update_score_history(history, date, stats):
    history.setdefault("records", [])
    history.setdefault("total_correct", 0)
    history.setdefault("total_incorrect", 0)
    history.setdefault("total_skip", 0)

    # 同日の記録があれば更新、なければ追加
    existing = next((r for r in history["records"] if r["date"] == date), None)
    if existing:
        history["total_correct"]   -= existing.get("correct", 0)
        history["total_incorrect"] -= existing.get("incorrect", 0)
        history["total_skip"]      -= existing.get("skip", 0)
        history["records"].remove(existing)

    history["records"].append({"date": date, **stats})
    history["records"].sort(key=lambda r: r["date"], reverse=True)

    history["total_correct"]   += stats["correct"]
    history["total_incorrect"] += stats["incorrect"]
    history["total_skip"]      += stats["skip"]

    judged = history["total_correct"] + history["total_incorrect"]
    history["overall_accuracy"] = round(history["total_correct"] / judged * 100, 1) if judged > 0 else None
    history["last_updated"] = date
    return history


def update_index_json(date_dash):
    """index.json を更新（PTSモニターと同じ構造）"""
    if INDEX_JSON.exists():
        data = load_json(INDEX_JSON)
    else:
        data = {"dates": []}

    dates = data.get("dates", [])
    if date_dash not in dates:
        dates.insert(0, date_dash)
        dates.sort(reverse=True)
        data["dates"] = dates

    with open(INDEX_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"index.json updated: {len(dates)} dates")


def main():
    print("=" * 60)
    print(f"answer_check.py start: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    print("=" * 60)

    for path, name in [(MASTER_JSON, "signal_master.json"), (PREDICT_JSON, f"predict_{TODAY_JST}.json")]:
        if not path.exists():
            print(f"ERROR: {name} not found.")
            sys.exit(1)

    master  = load_json(MASTER_JSON)
    predict = load_json(PREDICT_JSON)
    pred_map = {p["theme"]: p for p in predict["predictions"]}

    print(f"\nFetching JP stock prices ({len(master['themes'])} themes x 10 stocks)...")
    results = []
    stats   = {"correct": 0, "incorrect": 0, "skip": 0}

    for t in master["themes"]:
        theme  = t["theme"]
        stocks = t["jp_stocks"]
        pred   = pred_map.get(theme, {})
        prediction = pred.get("prediction")
        confidence = pred.get("confidence")
        reason     = pred.get("reason", "")

        print(f"\n  [{theme}] pred={prediction}[{confidence}]")

        stock_data = []
        for s in stocks:
            chg = fetch_jp_price(s["code"])
            stock_data.append({"code": s["code"], "name": s["name"], "change_pct": chg})
            status = f"{chg:+.2f}%" if chg is not None else "failed"
            print(f"    {s['code']} {s['name'][:10]:10s} {status}")
            time.sleep(0.15)

        theme_result = calc_theme_result(stock_data)
        actual_dir   = theme_result["direction"]
        verdict      = judge(prediction, actual_dir)
        stats[verdict] += 1

        anomaly_note = "(sector-wide)" if theme_result["anomaly_mode"] else \
                       f"({theme_result['excluded_count']} excluded)" if theme_result["excluded_count"] > 0 else ""
        icon = "✅" if verdict == "correct" else ("❌" if verdict == "incorrect" else "⏭")
        print(f"    avg={theme_result['avg_chg']}% actual={actual_dir} {anomaly_note}")
        print(f"    {icon} pred={prediction} actual={actual_dir} -> {verdict}")

        results.append({
            "theme":      theme,
            "prediction": prediction,
            "confidence": confidence,
            "reason":     reason,
            "actual": {
                "direction":      actual_dir,
                "avg_change_pct": theme_result["avg_chg"],
                "used_count":     theme_result["used_count"],
                "excluded_count": theme_result["excluded_count"],
                "anomaly_mode":   theme_result["anomaly_mode"],
            },
            "verdict": verdict,
            "details": theme_result["details"],
        })

    judged   = stats["correct"] + stats["incorrect"]
    accuracy = round(stats["correct"] / judged * 100, 1) if judged > 0 else None

    output = {
        "date":       TODAY_JST,
        "checked_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "results":    results,
        "stats":      {**stats, "judged": judged, "accuracy": accuracy},
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    history = load_json(SCORE_HISTORY) if SCORE_HISTORY.exists() else {}
    history = update_score_history(history, TODAY_JST, stats)
    with open(SCORE_HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    # index.json 更新（PTSモニターと同じ構造）
    update_index_json(TODAY_DASH)

    print("\n" + "=" * 60)
    print(f"Score: {stats['correct']} correct / {stats['incorrect']} incorrect / {stats['skip']} skip")
    print(f"Accuracy: {accuracy}% ({judged} judged)")
    print(f"Overall: {history.get('overall_accuracy')}%")
    print(f"Output: {OUTPUT_JSON}")
    print("=" * 60)


if __name__ == "__main__":
    main()
