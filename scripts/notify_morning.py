#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_morning.py - 朝処理(終値データ取得 + 予測生成)の完了通知
fetch_us.py / predict.py の後にworkflow内で実行する。
両スクリプトが失敗していても(出力jsonが無くても)動作し、
その場合は失敗通知をLINEに送る。
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from notifier_usjp import send_prediction_report  # noqa: E402

JST = timezone(timedelta(hours=9))
TODAY_JST = datetime.now(JST).strftime("%Y%m%d")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

EXPECTED_THEMES = 30  # signal_master.json の theme_count


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    us_close_path = DATA_DIR / f"us_close_{TODAY_JST}.json"
    predict_path = DATA_DIR / f"predict_{TODAY_JST}.json"

    # 終値データ取得が失敗 -> 朝処理全体が失敗扱い
    if not us_close_path.exists():
        send_prediction_report({
            "date": TODAY_JST,
            "error": f"終値データ({us_close_path.name})が生成されませんでした。終値取得処理が失敗した可能性があります。",
        })
        return

    us_close = load_json(us_close_path)
    fetch_stats = us_close.get("stats", {"total": 0, "ok": 0, "ng": 0})

    report = {"date": TODAY_JST, "fetch_stats": fetch_stats}

    if predict_path.exists():
        predict = load_json(predict_path)
        total = predict.get("stats", {}).get("total", EXPECTED_THEMES)
        ok = len(predict.get("predictions", []))
        report["prediction_stats"] = {"total": total, "ok": ok, "ng": total - ok}
    else:
        # 終値取得は成功したが予測生成が失敗
        report["prediction_stats"] = {"total": EXPECTED_THEMES, "ok": 0, "ng": EXPECTED_THEMES}

    send_prediction_report(report)


if __name__ == "__main__":
    main()
