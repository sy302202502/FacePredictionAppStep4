"""
notifier.py
LINE Notify で予想結果を通知するスクリプト

使い方:
  python notifier.py send "レース名"          # 予想結果をLINEに送信
  python notifier.py test                      # テスト通知

LINE Notify トークンの取得:
  1. https://notify-bot.line.me にアクセス
  2. ログイン → 「マイページ」→「トークンを発行する」
  3. トークン名: 競馬予想、通知先: 1:1で受け取る
  4. 発行されたトークンを .env の LINE_NOTIFY_TOKEN に設定
"""

import os
import sys
import json
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

LINE_NOTIFY_URL = "https://notify-api.line.me/api/notify"
LINE_TOKEN = os.getenv("LINE_NOTIFY_TOKEN", "")


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "faceapp"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgrestest"),
    )


def send_line(message: str, image_path: str = None) -> bool:
    """LINE Notify でメッセージを送信"""
    if not LINE_TOKEN:
        print("❌ LINE_NOTIFY_TOKEN が設定されていません (.env を確認してください)")
        return False

    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    data = {"message": message}

    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                files = {"imageFile": f}
                resp = requests.post(LINE_NOTIFY_URL, headers=headers, data=data, files=files, timeout=15)
        else:
            resp = requests.post(LINE_NOTIFY_URL, headers=headers, data=data, timeout=15)

        if resp.status_code == 200:
            return True
        else:
            print(f"❌ LINE送信失敗: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"❌ LINE送信エラー: {e}")
        return False


def fetch_predictions(race_name: str):
    """DBから予想結果を取得"""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT horse_name, rank_position, final_score,
                       similarity_score, diff_score, race_category, target_race_date
                FROM prediction_result
                WHERE target_race_name = %s
                ORDER BY rank_position ASC
                LIMIT 5
            """, (race_name,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def build_message(race_name: str, predictions: list) -> str:
    """通知メッセージを組み立てる"""
    rank_emoji = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
    category_label = {
        "sprint": "短距離", "mile": "マイル", "middle": "中距離",
        "long": "長距離", "dirt": "ダート"
    }

    race_date = str(predictions[0].get("target_race_date", "")) if predictions else ""
    category = category_label.get(predictions[0].get("race_category", ""), "") if predictions else ""

    lines = [
        "",
        "🏇 競馬顔面予想システム",
        f"━━━━━━━━━━━━━━",
        f"📋 {race_name}",
    ]
    if race_date:
        lines.append(f"📅 {race_date}  {category}")
    lines.append("━━━━━━━━━━━━━━")
    lines.append("【 TOP5 予想 】")

    for p in predictions:
        rank = p.get("rank_position", 0)
        name = p.get("horse_name", "不明")
        score = p.get("final_score") or 0.0
        emoji = rank_emoji.get(rank, f"{rank}.")
        lines.append(f"{emoji} {name}  {score:.1f}pt")

    lines.append("━━━━━━━━━━━━━━")
    lines.append(f"🕐 {datetime.now().strftime('%m/%d %H:%M')} 送信")
    return "\n".join(lines)


def cmd_send(race_name: str):
    """予想結果をLINEに送信"""
    print(f"レース: {race_name}")
    predictions = fetch_predictions(race_name)
    if not predictions:
        print(f"❌ 予想データが見つかりません: {race_name}")
        sys.exit(1)

    message = build_message(race_name, predictions)
    print("送信内容:")
    print(message)
    print()

    ok = send_line(message)
    if ok:
        print("✅ LINE通知を送信しました")
    else:
        sys.exit(1)


def fetch_v2_predictions(race_name: str):
    """新システム（顔面傾向分析）の予想結果をDBから取得"""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT r.horse_name, r.rank_position, r.score,
                       r.composite_score, r.win_odds, r.value_rating,
                       r.data_source, r.comment,
                       p.top5comment, p.confidence_level
                FROM race_specific_result r
                LEFT JOIN race_specific_prediction p ON p.race_name = r.race_name
                WHERE r.race_name = %s
                ORDER BY COALESCE(r.composite_score, r.score) DESC
                LIMIT 5
            """, (race_name,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def build_v2_message(race_name: str, predictions: list) -> str:
    """新システム用の通知メッセージを組み立てる"""
    rank_emoji = {1: "◎", 2: "○", 3: "▲", 4: "△", 5: "×"}
    src_label  = {"image": "画像", "pedigree": "血統推定", "no_data": "推定"}
    conf_level = predictions[0].get("confidence_level", 3) if predictions else 3
    stars = "★" * (conf_level or 3) + "☆" * (5 - (conf_level or 3))

    top5_comment = predictions[0].get("top5comment", "") if predictions else ""

    lines = [
        "",
        "🔬 顔面傾向分析予想",
        f"━━━━━━━━━━━━━━",
        f"📋 {race_name}",
        f"信頼度: {stars}",
    ]
    if top5_comment:
        # 長すぎる場合は省略
        lines.append(f"傾向: {top5_comment[:30]}...")
    lines.append("━━━━━━━━━━━━━━")
    lines.append("【 予想 TOP5 】")

    for i, p in enumerate(predictions, 1):
        name   = p.get("horse_name", "不明")
        score  = p.get("composite_score") or p.get("score") or 0.0
        odds   = p.get("win_odds")
        rating = p.get("value_rating", "")
        src    = src_label.get(p.get("data_source", ""), "")
        mark   = rank_emoji.get(i, f"{i}.")

        odds_str = f" {odds:.1f}倍" if odds else ""
        rating_str = f" [{rating}]" if rating and rating not in ("普通", "データなし") else ""
        src_str  = f" ({src})" if src and src != "画像" else ""
        lines.append(f"{mark} {name}  {score:.1f}pt{odds_str}{rating_str}{src_str}")

    lines.append("━━━━━━━━━━━━━━")
    lines.append(f"🕐 {datetime.now().strftime('%m/%d %H:%M')} 送信")
    lines.append("http://localhost:8081/predict-v2")
    return "\n".join(lines)

def cmd_send_v2(race_name: str):
    """新システムの予想結果をLINEに送信"""
    print(f"レース(新システム): {race_name}")
    predictions = fetch_v2_predictions(race_name)
    if not predictions:
        print(f"❌ 新システム予想データが見つかりません: {race_name}")
        # 旧システムにフォールバック
        print("旧システムで再試行...")
        cmd_send(race_name)
        return
    message = build_v2_message(race_name, predictions)
    print("送信内容:")
    print(message)
    ok = send_line(message)
    if ok:
        print("✅ LINE通知を送信しました")
    else:
        sys.exit(1)

def cmd_test():
    """テスト通知"""
    message = (
        "\n🏇 競馬顔面予想システム\n"
        "━━━━━━━━━━━━━━\n"
        "✅ LINE通知のテストです\n"
        f"🕐 {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
    )
    ok = send_line(message)
    if ok:
        print("✅ テスト通知を送信しました")
    else:
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("使い方:")
        print("  python notifier.py send 'レース名'     # 旧システム予想を送信")
        print("  python notifier.py send-v2 'レース名'  # 新システム予想を送信")
        print("  python notifier.py test                 # テスト送信")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "send":
        if len(sys.argv) < 3:
            print("❌ レース名を指定してください")
            sys.exit(1)
        cmd_send(sys.argv[2])
    elif cmd == "send-v2":
        if len(sys.argv) < 3:
            print("❌ レース名を指定してください")
            sys.exit(1)
        cmd_send_v2(sys.argv[2])
    elif cmd == "test":
        cmd_test()
    else:
        print(f"❌ 不明なコマンド: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
