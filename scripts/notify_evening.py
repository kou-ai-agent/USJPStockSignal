#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_evening.py - 夜処理(答え合わせ)の完了通知
answer_check.py の後にworkflow内で実行する。
出力jsonが無い場合は失敗通知をLINEに送る。
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from notifier_usjp import send_accuracy_report  # noqa: E402

JST = timezone(timedelta(hours=9))
TODAY_JST = datetime.now(JST).strftime("%Y%m%d")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"


def main() -> None:
    answer_path = DATA_DIR / f"answer_{TODAY_JST}.json"

    if not answer_path.exists():
        send_accuracy_report({
            "date": TODAY_JST,
            "error": f"答え合わせ結果({answer_path.name})が生成されませんでした。答え合わせ処理が失敗した可能性があります。",
        })
        return

    with open(answer_path, encoding="utf-8") as f:
        answer = json.load(f)

    send_accuracy_report({"date": TODAY_JST, "stats": answer.get("stats", {})})


if __name__ == "__main__":
    main()
