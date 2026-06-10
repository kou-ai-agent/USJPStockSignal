#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
predict.py - Claude Haiku による日本株テーマ予測スクリプト
===========================================================
fetch_us.py の実行後に呼び出す。
米国終値データとシグナルマッピングを読み込み、
Claude Haiku に30テーマの翌日予測（Long/Short/Neutral）を依頼する。

出力ファイル例: data/predict_20260609.json
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic が必要です。pip install anthropic")
    sys.exit(1)

# =====================
# 設定
# =====================
BASE_DIR     = Path(__file__).parent.parent
DATA_DIR     = BASE_DIR / "data"
MASTER_JSON  = DATA_DIR / "signal_master.json"

JST          = timezone(timedelta(hours=9))
TODAY_JST    = datetime.now(JST).strftime("%Y%m%d")

US_CLOSE_JSON = DATA_DIR / f"us_close_{TODAY_JST}.json"
OUTPUT_JSON   = DATA_DIR / f"predict_{TODAY_JST}.json"

MODEL         = "claude-haiku-4-5-20251001"
MAX_TOKENS    = 4096


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt_pct(val) -> str:
    """騰落率を表示用文字列に変換。None/nanは'N/A'"""
    try:
        if val is None:
            return "N/A"
        v = float(val)
        if v != v:  # nan判定
            return "N/A"
        return f"{v:+.2f}%"
    except Exception:
        return "N/A"


def build_prompt(master: dict, us_close: dict) -> str:
    """Claude へのプロンプトを組み立てる"""

    mkt = us_close.get("market_summary", {})
    signals = us_close.get("signals", {})
    date = us_close.get("date", TODAY_JST)

    # 市場サマリー部分
    sp500_chg  = fmt_pct(mkt.get("sp500",  {}).get("change_pct"))
    nasdaq_chg = fmt_pct(mkt.get("nasdaq", {}).get("change_pct"))
    dow_chg    = fmt_pct(mkt.get("dow",    {}).get("change_pct"))
    vix_val    = mkt.get("vix",   {}).get("close", "N/A")
    vix_chg    = fmt_pct(mkt.get("vix",   {}).get("change_pct"))
    dxy_chg    = fmt_pct(mkt.get("dxy",   {}).get("change_pct"))
    us10y_val  = mkt.get("us10y", {}).get("close", "N/A")
    us10y_chg  = fmt_pct(mkt.get("us10y", {}).get("change_pct"))

    market_section = f"""## 米国市場サマリー（{date}）
- S&P500:   {sp500_chg}
- NASDAQ:   {nasdaq_chg}
- ダウ:     {dow_chg}
- VIX:      {vix_val}（{vix_chg}）
- ドル指数: {dxy_chg}
- 米10年債: {us10y_val}%（{us10y_chg}）"""

    # テーマ別シグナル部分
    theme_sections = []
    for t in master["themes"]:
        theme = t["theme"]
        sig   = t["us_signal"]
        prim  = sig.get("primary", {})
        pt    = prim.get("ticker", "")
        logic = sig.get("logic", "")

        # 主シグナルの騰落率
        prim_data = signals.get(pt, {}) or {}
        prim_chg  = fmt_pct(prim_data.get("change_pct")) if prim_data else "N/A"

        # 補助シグナルの騰落率
        sub_parts = []
        for sub in sig.get("sub", []):
            sub_data = signals.get(sub, {}) or {}
            sub_chg  = fmt_pct(sub_data.get("change_pct")) if sub_data else "N/A"
            sub_parts.append(f"{sub}:{sub_chg}")
        sub_str = "  補助: " + " / ".join(sub_parts) if sub_parts else ""

        theme_sections.append(
            f"【{theme}】主: {pt} {prim_chg}{sub_str}\n  連動ロジック: {logic}"
        )

    themes_section = "\n".join(theme_sections)

    # プロンプト全体
    prompt = f"""{market_section}

## テーマ別 米国シグナル騰落率
{themes_section}

---

## 予測依頼

上記の米国市場データを踏まえ、本日（{date}）の日本市場（翌営業日）における各テーマの方向性を予測してください。

### 出力形式
必ず以下のJSON形式のみで回答してください。前置き・後書き・マークダウン記法は不要です。

{{
  "date": "{date}",
  "predictions": [
    {{
      "theme": "テーマ名",
      "prediction": "Long" | "Short" | "Neutral",
      "confidence": "High" | "Medium" | "Low",
      "reason": "予測理由を1〜2文で（日本語）"
    }}
  ]
}}

### 予測基準
- Long:    米国シグナルが強く、翌日の日本側テーマ銘柄が上昇しやすい
- Short:   米国シグナルが弱く、翌日の日本側テーマ銘柄が下落しやすい
- Neutral: シグナルが混在、または連動性が低いと判断
- confidence: High=確信度高い / Medium=やや根拠あり / Low=不確実性大

### 注意事項
- VIXが20を超える場合はリスクオフとして全体に警戒
- 個別テーマのシグナルが強くても、市場全体が大幅下落の場合はNeutralまたはShort寄りに補正
- 連動性が構造的に低いテーマ（食品・不動産・通信）はNeutralを優先
- N/Aのシグナルは判断材料から除外し、他の情報で補完

全{len(master['themes'])}テーマすべて回答してください。"""

    return prompt


def call_claude(prompt: str) -> dict:
    """Claude Haiku を呼び出して予測JSONを取得"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY が設定されていません。")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print("Claude Haiku に予測依頼中...")
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    # JSONブロックが ```json ... ``` で囲まれている場合に対応
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])

    try:
        result = json.loads(raw)
        return result
    except json.JSONDecodeError as e:
        print(f"ERROR: Claude の出力がJSONとして解析できません。\n{e}\n---\n{raw}")
        sys.exit(1)


def main():
    print("=" * 60)
    print(f"predict.py 開始: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    print("=" * 60)

    # ① ファイル存在確認
    for path, name in [(MASTER_JSON, "signal_master.json"), (US_CLOSE_JSON, f"us_close_{TODAY_JST}.json")]:
        if not path.exists():
            print(f"ERROR: {name} が見つかりません。({path})")
            sys.exit(1)

    master   = load_json(MASTER_JSON)
    us_close = load_json(US_CLOSE_JSON)
    print(f"テーマ数: {len(master['themes'])}")
    print(f"米国データ日付: {us_close['date']}")

    # ② プロンプト構築
    prompt = build_prompt(master, us_close)
    print(f"\nプロンプト文字数: {len(prompt)}")

    # ③ Claude 呼び出し
    result = call_claude(prompt)

    # ④ 予測数の確認
    predictions = result.get("predictions", [])
    print(f"予測テーマ数: {len(predictions)} / {len(master['themes'])}")

    # ⑤ メタ情報を付加して保存
    output = {
        "date":        TODAY_JST,
        "predicted_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "model":       MODEL,
        "us_date":     us_close["date"],
        "predictions": predictions,
        "stats": {
            "total":   len(master["themes"]),
            "long":    sum(1 for p in predictions if p.get("prediction") == "Long"),
            "short":   sum(1 for p in predictions if p.get("prediction") == "Short"),
            "neutral": sum(1 for p in predictions if p.get("prediction") == "Neutral"),
        }
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ⑥ サマリー表示
    print("\n--- 予測結果サマリー ---")
    for p in predictions:
        icon = "↑" if p["prediction"] == "Long" else ("↓" if p["prediction"] == "Short" else "→")
        conf = p.get("confidence", "?")[0]  # H/M/L
        print(f"  {icon}[{conf}] {p['theme']:12s} {p['prediction']:7s}  {p.get('reason','')[:40]}")

    s = output["stats"]
    print(f"\nLong: {s['long']} / Short: {s['short']} / Neutral: {s['neutral']}")
    print(f"\n出力: {OUTPUT_JSON}")
    # index.json 更新（朝の時点でカレンダーに当日を追加）
    index_path = DATA_DIR / "index.json"
    today_dash = datetime.now(JST).strftime("%Y-%m-%d")
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            idx = json.load(f)
    else:
        idx = {"dates": []}
    if today_dash not in idx["dates"]:
        idx["dates"].insert(0, today_dash)
        idx["dates"].sort(reverse=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    print(f"index.json updated: {today_dash}")
    print("=" * 60)


if __name__ == "__main__":
    main()
