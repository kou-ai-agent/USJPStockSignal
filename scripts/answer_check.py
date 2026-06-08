#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
answer_check.py - 日本株答え合わせスクリプト
=============================================
毎日 PM4:00 JST（大引け後）に GitHub Actions から実行。
predict_YYYYMMDD.json の予測と日本株実際の騰落率を比較し、
精度スコアを蓄積する。

出力ファイル例:
  data/answer_20260609.json   （当日の答え合わせ結果）
  data/score_history.json     （累積精度スコア）

アノマリー除外ロジック:
  テーマ内で±ANOMALY_THRESHOLD%超の銘柄が ANOMALY_MAJORITY 未満
  → その銘柄だけ除外（個別アノマリーと判断）
  テーマ内で±ANOMALY_THRESHOLD%超の銘柄が ANOMALY_MAJORITY 以上
  → 除外せず全銘柄を使用（セクター全体の動きと判断）
"""

import json
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
BASE_DIR     = Path(__file__).parent.parent
DATA_DIR     = BASE_DIR / "data"
MASTER_JSON  = DATA_DIR / "signal_master.json"

JST          = timezone(timedelta(hours=9))
TODAY_JST    = datetime.now(JST).strftime("%Y%m%d")

PREDICT_JSON  = DATA_DIR / f"predict_{TODAY_JST}.json"
OUTPUT_JSON   = DATA_DIR / f"answer_{TODAY_JST}.json"
SCORE_HISTORY = DATA_DIR / "score_history.json"

# アノマリー除外パラメータ
ANOMALY_THRESHOLD = 5.0   # ±5%超を閾値とする
ANOMALY_MAJORITY  = 6     # 6銘柄以上が閾値超え → セクター全体の動きと判断

# 予測方向の判定閾値（テーマ平均騰落率）
DIRECTION_THRESHOLD = 0.3  # ±0.3%以内はNeutralとみなす


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_jp_price(code: str) -> float | None:
    """日本株1銘柄の終値騰落率を取得。失敗時はNone"""
    # 4桁数字 or 英数字混合コードに .T を付与
    symbol = f"{code}.T"
    try:
        info  = yf.Ticker(symbol).fast_info
        close = info.get("lastPrice") or info.get("previousClose")
        prev  = info.get("regularMarketPreviousClose") or info.get("previousClose")
        if not close or not prev or float(prev) == 0:
            return None
        chg = (float(close) - float(prev)) / float(prev) * 100
        return round(chg, 2)
    except Exception as e:
        print(f"  WARN: {symbol} 取得失敗 - {e}")
        return None


def calc_theme_result(stocks: list) -> dict:
    """
    テーマ内銘柄の騰落率リストから、アノマリー除外後の平均と方向を算出。
    戻り値: {
        "avg_chg": float,       平均騰落率
        "direction": str,       実際の方向（Long/Short/Neutral）
        "used_count": int,      使用銘柄数
        "excluded_count": int,  除外銘柄数
        "anomaly_mode": bool,   Trueならセクター全体の動きと判断（除外なし）
        "details": list         銘柄ごとの詳細
    }
    """
    details = []
    for s in stocks:
        chg = s.get("change_pct")
        details.append({
            "code":       s["code"],
            "name":       s["name"],
            "change_pct": chg,
            "fetched":    chg is not None,
        })

    # 取得できた銘柄のみ対象
    fetched = [d for d in details if d["fetched"]]
    if not fetched:
        return {
            "avg_chg": None, "direction": None,
            "used_count": 0, "excluded_count": 0,
            "anomaly_mode": False, "details": details
        }

    # アノマリー判定
    anomaly_stocks = [d for d in fetched if abs(d["change_pct"]) > ANOMALY_THRESHOLD]
    anomaly_mode   = len(anomaly_stocks) >= ANOMALY_MAJORITY

    if anomaly_mode:
        # セクター全体の動き → 全銘柄使用
        used     = fetched
        excluded = 0
    else:
        # 個別アノマリー除外
        used     = [d for d in fetched if abs(d["change_pct"]) <= ANOMALY_THRESHOLD]
        excluded = len(anomaly_stocks)
        if not used:
            # 全部除外になった場合は全銘柄使用にフォールバック
            used        = fetched
            excluded    = 0
            anomaly_mode = True

    avg_chg = sum(d["change_pct"] for d in used) / len(used)

    if avg_chg > DIRECTION_THRESHOLD:
        direction = "Long"
    elif avg_chg < -DIRECTION_THRESHOLD:
        direction = "Short"
    else:
        direction = "Neutral"

    return {
        "avg_chg":       round(avg_chg, 2),
        "direction":     direction,
        "used_count":    len(used),
        "excluded_count": excluded,
        "anomaly_mode":  anomaly_mode,
        "details":       details,
    }


def judge(prediction: str, actual: str) -> str:
    """予測と実績を比較して正解/不正解/スキップを返す"""
    if actual is None:
        return "skip"       # データ取得失敗
    if prediction == "Neutral" or actual == "Neutral":
        return "skip"       # Neutralは判定対象外（MVP）
    return "correct" if prediction == actual else "incorrect"


def update_score_history(history: dict, date: str, stats: dict) -> dict:
    """score_history.jsonを更新"""
    history.setdefault("records", [])
    history.setdefault("total_correct", 0)
    history.setdefault("total_incorrect", 0)
    history.setdefault("total_skip", 0)

    history["records"].append({"date": date, **stats})
    history["total_correct"]   += stats["correct"]
    history["total_incorrect"] += stats["incorrect"]
    history["total_skip"]      += stats["skip"]

    judged = history["total_correct"] + history["total_incorrect"]
    history["overall_accuracy"] = round(
        history["total_correct"] / judged * 100, 1
    ) if judged > 0 else None
    history["last_updated"] = date

    return history


def main():
    print("=" * 60)
    print(f"answer_check.py 開始: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    print("=" * 60)

    # ① ファイル存在確認
    for path, name in [
        (MASTER_JSON,  "signal_master.json"),
        (PREDICT_JSON, f"predict_{TODAY_JST}.json"),
    ]:
        if not path.exists():
            print(f"ERROR: {name} が見つかりません。")
            sys.exit(1)

    master  = load_json(MASTER_JSON)
    predict = load_json(PREDICT_JSON)

    # 予測をテーマ名でインデックス化
    pred_map = {p["theme"]: p for p in predict["predictions"]}

    # ② 日本株終値取得 + 答え合わせ
    print(f"\n日本株終値取得中（{len(master['themes'])}テーマ × 10銘柄）...")
    results = []
    stats   = {"correct": 0, "incorrect": 0, "skip": 0}

    for t in master["themes"]:
        theme  = t["theme"]
        stocks = t["jp_stocks"]
        pred   = pred_map.get(theme, {})
        prediction = pred.get("prediction")
        confidence = pred.get("confidence")
        reason     = pred.get("reason", "")

        print(f"\n  【{theme}】予測={prediction}[{confidence}]")

        # 各銘柄の騰落率を取得
        stock_data = []
        for s in stocks:
            chg = fetch_jp_price(s["code"])
            stock_data.append({
                "code":       s["code"],
                "name":       s["name"],
                "change_pct": chg,
            })
            if chg is not None:
                print(f"    {s['code']} {s['name'][:10]:10s} {chg:+.2f}%")
            else:
                print(f"    {s['code']} {s['name'][:10]:10s} 取得失敗")
            time.sleep(0.15)

        # テーマ結果算出
        theme_result = calc_theme_result(stock_data)
        actual_dir   = theme_result["direction"]
        avg_chg      = theme_result["avg_chg"]
        verdict      = judge(prediction, actual_dir)
        stats[verdict] += 1

        # 表示
        anomaly_note = "（セクター全体の動き・除外なし）" if theme_result["anomaly_mode"] else \
                       f"（{theme_result['excluded_count']}銘柄除外）" if theme_result["excluded_count"] > 0 else ""
        verdict_icon = "✅" if verdict == "correct" else ("❌" if verdict == "incorrect" else "⏭")
        print(f"    平均騰落率: {avg_chg:+.2f}% → 実際={actual_dir} {anomaly_note}")
        print(f"    {verdict_icon} 予測={prediction} 実際={actual_dir} → {verdict}")

        results.append({
            "theme":       theme,
            "prediction":  prediction,
            "confidence":  confidence,
            "reason":      reason,
            "actual": {
                "direction":      actual_dir,
                "avg_change_pct": avg_chg,
                "used_count":     theme_result["used_count"],
                "excluded_count": theme_result["excluded_count"],
                "anomaly_mode":   theme_result["anomaly_mode"],
            },
            "verdict":     verdict,
            "details":     theme_result["details"],
        })

    # ③ 当日スコア
    judged   = stats["correct"] + stats["incorrect"]
    accuracy = round(stats["correct"] / judged * 100, 1) if judged > 0 else None

    # ④ 当日JSON保存
    output = {
        "date":        TODAY_JST,
        "checked_at":  datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "results":     results,
        "stats": {
            **stats,
            "judged":   judged,
            "accuracy": accuracy,
        }
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ⑤ 累積スコア更新
    history = load_json(SCORE_HISTORY) if SCORE_HISTORY.exists() else {}
    history = update_score_history(history, TODAY_JST, stats)
    with open(SCORE_HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    # ⑥ サマリー
    print("\n" + "=" * 60)
    print(f"本日スコア: {stats['correct']}正解 / {stats['incorrect']}不正解 / {stats['skip']}スキップ")
    print(f"本日正解率: {accuracy}% （{judged}テーマ判定）")
    print(f"累積正解率: {history.get('overall_accuracy')}%")
    print(f"\n出力: {OUTPUT_JSON}")
    print(f"累積: {SCORE_HISTORY}")
    print("=" * 60)


if __name__ == "__main__":
    main()
