import os
import logging
import requests

logger = logging.getLogger(__name__)

# GitHub Secretsから取得する環境変数名(USJPStockSignal専用)
USJP_LINE_ACCESS_TOKEN = os.environ.get("USJP_LINE_ACCESS_TOKEN", "")

DASHBOARD_URL = "https://usjpstocksignal.pages.dev"


def send_prediction_report(report: dict) -> None:
    """
    朝処理(終値データ取得 + 予測生成)の完了通知。

    report = {
        "date": "20260612",
        "fetch_stats": {"total": 100, "ok": 100, "ng": 0, "failed_tickers": ["AAPL", ...]},
        "prediction_stats": {"total": 30, "ok": 30, "ng": 0},  # 未対応ならNoneでOK
        "error": "..."  # 処理自体が失敗した場合のみセット。他のキーは無視される。
    }
    """
    message = _build_prediction_message(report)
    _send_line(message)


def send_accuracy_report(report: dict) -> None:
    """
    夜処理(答え合わせ)の完了通知。

    report = {
        "date": "20260611",
        "stats": {"correct": 22, "incorrect": 1, "skip": 7, "judged": 23, "accuracy": 95.7},
        "error": "..."  # 処理自体が失敗した場合のみセット。他のキーは無視される。
    }
    """
    message = _build_accuracy_message(report)
    _send_line(message)


def _build_prediction_message(report: dict) -> str:
    date = report.get("date", "unknown")

    if report.get("error"):
        return (
            f"❌ USJPStockSignal 朝処理 失敗 [{date}]\n"
            f"終値データ取得または予測生成でエラーが発生しました。\n"
            f"エラー内容: {report['error']}"
        )

    fetch = report.get("fetch_stats", {})
    f_total = fetch.get("total", 0)
    f_ok = fetch.get("ok", 0)
    f_ng = fetch.get("ng", 0)
    failed_tickers = fetch.get("failed_tickers", [])

    pred = report.get("prediction_stats")
    p_ng = pred.get("ng", 0) if pred is not None else 0

    header = f"⚠️ USJPStockSignal 朝処理 一部失敗 [{date}]" if (f_ng > 0 or p_ng > 0) \
        else f"✅ USJPStockSignal 朝処理完了 [{date}]"

    lines = [header, "", f"📈 終値データ取得: {f_ok}/{f_total}件"]
    if f_ng > 0:
        detail = ", ".join(failed_tickers) if failed_tickers else f"{f_ng}件"
        lines.append(f"　 取得失敗: {detail}")

    if pred is not None:
        p_total = pred.get("total", 0)
        p_ok = pred.get("ok", 0)
        p_ng = pred.get("ng", 0)
        lines.append(f"🤖 予測生成: {p_ok}/{p_total}テーマ")
        if p_ng > 0:
            lines.append(f"　 生成失敗: {p_ng}件")

    lines += ["", f"詳細: {DASHBOARD_URL}"]
    return "\n".join(lines)


def _build_accuracy_message(report: dict) -> str:
    date = report.get("date", "unknown")

    if report.get("error"):
        return (
            f"❌ USJPStockSignal 答え合わせ 失敗 [{date}]\n"
            f"処理中にエラーが発生しました。\n"
            f"エラー内容: {report['error']}"
        )

    stats = report.get("stats", {})
    correct = stats.get("correct", 0)
    skip = stats.get("skip", 0)
    judged = stats.get("judged", correct + stats.get("incorrect", 0))
    accuracy = stats.get("accuracy", 0.0)

    lines = [
        f"📊 USJPStockSignal 答え合わせ完了 [{date}]",
        "",
        f"🎯 精度: {correct}/{judged}正解 ({accuracy}%)",
    ]
    if skip > 0:
        lines.append(f"　 (スキップ {skip}テーマ)")

    lines += ["", f"詳細: {DASHBOARD_URL}"]
    return "\n".join(lines)


def _send_line(message: str) -> None:
    if not USJP_LINE_ACCESS_TOKEN:
        logger.warning("USJP_LINE_ACCESS_TOKEN が設定されていません。")
        return

    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {
        "Authorization": f"Bearer {USJP_LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            json={"messages": [{"type": "text", "text": message}]},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("LINE通知を送信しました。")
    except Exception as e:
        logger.error(f"LINE通知エラー: {e}")
