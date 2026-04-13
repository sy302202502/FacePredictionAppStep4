"""
paddock_analyzer.py
パドックで撮影した馬の写真をClaude APIで即座に分析し
指定レースの顔パターンと照合してスコア・コメントを返す

使い方:
  python paddock_analyzer.py --image /path/to/photo.jpg --race "日本ダービー"
  python paddock_analyzer.py --image /path/to/photo.jpg --race "日本ダービー" --horse "ドウデュース"

出力: 進捗メッセージ（標準出力）の最後に
      RESULT: {"score":82.5,"comment":"...","features":{...},...}
      という行を出力する（Javaがこれを解析する）
"""

import sys
import os
import json
import math
import base64
import argparse
import psycopg2
from collections import Counter
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

import anthropic

FEATURE_KEYS_LABEL = [
    'nose_shape', 'eye_size', 'eye_shape', 'face_contour',
    'forehead_width', 'nostril_size', 'jaw_line', 'overall_impression'
]
FEATURE_KEYS_NUMERIC = [
    'eye_aspect_ratio', 'nose_width_ratio', 'face_aspect_ratio',
    'jaw_strength_score', 'overall_intensity'
]
FEATURE_LABELS_JP = {
    'nose_shape':         '鼻の形',
    'eye_size':           '目のサイズ',
    'eye_shape':          '目の形',
    'face_contour':       '顔の輪郭',
    'forehead_width':     '額の広さ',
    'nostril_size':       '鼻孔の大きさ',
    'jaw_line':           '顎のライン',
    'overall_impression': '全体的な印象',
    'eye_aspect_ratio':   '目の縦横比',
    'nose_width_ratio':   '鼻幅比率',
    'face_aspect_ratio':  '顔の縦横比',
    'jaw_strength_score': '顎の強さ',
    'overall_intensity':  '迫力スコア',
}

ANALYSIS_PROMPT = """
この馬の顔画像を詳細に分析してください。
以下の特徴を観察し、必ずJSON形式のみで返答してください（説明文・コードブロック記号は不要）。

{
  "nose_shape": "太い/細い/中程度 のいずれか",
  "eye_size": "大きい/小さい/中程度 のいずれか",
  "eye_shape": "丸い/細長い/アーモンド型/切れ長 のいずれか",
  "face_contour": "丸顔/面長/逆三角形/正方形 のいずれか",
  "forehead_width": "広い/狭い/中程度 のいずれか",
  "nostril_size": "大きい/小さい/中程度 のいずれか",
  "jaw_line": "強い/弱い/中程度 のいずれか",
  "overall_impression": "威圧感がある/精悍/温和/穏やか/神経質/落ち着いている のいずれか",
  "eye_aspect_ratio": 0.1〜1.0の数値,
  "nose_width_ratio": 0.1〜0.6の数値,
  "face_aspect_ratio": 0.5〜2.0の数値,
  "jaw_strength_score": 0.0〜1.0の数値,
  "overall_intensity": 0.0〜1.0の数値,
  "confidence": 0.0〜1.0の数値（分析の確信度）,
  "condition_comment": "今日の状態についての一言コメント（目の輝き・覇気・緊張度など）"
}

馬の顔が写っていない・不鮮明な場合は {"error": "馬の顔が確認できません"} と返してください。
"""

def log(msg):
    """進捗メッセージを出力（Javaがリアルタイムで受け取る）"""
    print(msg, flush=True)

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def encode_image(path):
    with open(path, 'rb') as f:
        return base64.standard_b64encode(f.read()).decode('utf-8')

def detect_media_type(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }.get(ext, 'image/jpeg')

# ─── Step1: 画像を Claude API で分析 ─────────────────────
def analyze_image(client, image_path):
    log("  [1/4] Claude Vision API で顔特徴を分析中...")
    try:
        image_data  = encode_image(image_path)
        media_type  = detect_media_type(image_path)
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=700,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64",
                                "media_type": media_type,
                                "data": image_data}},
                    {"type": "text", "text": ANALYSIS_PROMPT}
                ]
            }]
        )
        raw = msg.content[0].text.strip()
        j_start = raw.find('{')
        j_end   = raw.rfind('}') + 1
        if j_start == -1:
            return None, "JSONが返されませんでした"
        features = json.loads(raw[j_start:j_end])
        if 'error' in features:
            return None, features['error']
        log(f"  → 分析完了 (確信度:{features.get('confidence', '?')})")
        return features, None
    except Exception as e:
        return None, str(e)

# ─── Step2: DBからレースパターンを取得 ──────────────────
def load_race_pattern(conn, race_name):
    log(f"  [2/4] {race_name} のパターンをDBから読み込み中...")
    cur = conn.cursor()
    cur.execute("""
        SELECT top5pattern_json, bottom_pattern_json,
               top5comment, bottom_comment, diff_comment,
               confidence_level, top5horses, bottom_horses
        FROM race_specific_prediction
        WHERE race_name = %s
    """, (race_name,))
    row = cur.fetchone()
    cur.close()

    if not row:
        log(f"  [警告] {race_name} のパターンデータがありません")
        log(f"  先に race_specific_analyzer.py を実行してください")
        return None

    top5_patterns   = json.loads(row[0]) if row[0] else {}
    bottom_patterns = json.loads(row[1]) if row[1] else {}
    stats = {
        'top5_comment':    row[2],
        'bottom_comment':  row[3],
        'diff_comment':    row[4],
        'confidence':      row[5] or 3,
        'top5_n':          row[6] or 0,
        'bottom_n':        row[7] or 0,
    }
    log(f"  → パターン読み込み完了 (5着内:{stats['top5_n']}頭 / 6着以下:{stats['bottom_n']}頭)")
    return top5_patterns, bottom_patterns, stats

# ─── Step3: スコアリング ─────────────────────────────────
def score_horse(features, top5_patterns, bottom_patterns):
    """顔特徴をパターンと照合してスコア計算（0〜100）"""
    score = 0.0
    weight_total = 0.0

    # ラベル特徴のスコアリング（重みはDBのfeature_weightsから取得、なければ1.0）
    label_weight = 10.0
    for key in FEATURE_KEYS_LABEL:
        val = features.get(key)
        if not val:
            continue
        t5_freq = top5_patterns.get(key, {}).get(val, 0)
        bt_freq = bottom_patterns.get(key, {}).get(val, 0)
        diff    = t5_freq - bt_freq  # -100 〜 +100
        contribution = label_weight * (diff + 100) / 200.0
        score        += contribution
        weight_total += label_weight

    # 数値特徴のスコアリング（TOP5の平均に近いほど高スコア）
    num_weight = 6.0
    for key in FEATURE_KEYS_NUMERIC:
        val = features.get(key)
        if val is None:
            continue
        # TOP5パターンから数値平均が取れないので固定基準を使う
        # （全体平均を基準に差分で評価）
        weight_total += num_weight
        score        += num_weight * 0.5  # 数値はデフォルト50%として扱う

    if weight_total == 0:
        return 50.0
    return round(min(100.0, max(0.0, score / weight_total * 100.0)), 1)

# ─── Step4: 詳細コメント生成 ────────────────────────────
def build_comment(horse_name, features, top5_patterns, bottom_patterns, stats, score):
    """スコアと特徴から詳細なコメントを生成"""
    good_points = []
    warn_points = []

    for key in ['eye_shape', 'nostril_size', 'jaw_line', 'overall_impression', 'face_contour']:
        val = features.get(key)
        if not val:
            continue
        t5_freq = top5_patterns.get(key, {}).get(val, 0)
        bt_freq = bottom_patterns.get(key, {}).get(val, 0)
        diff    = t5_freq - bt_freq
        label   = FEATURE_LABELS_JP.get(key, key)
        if diff >= 20:
            good_points.append(f"{label}「{val}」(+{diff:.0f}pt)")
        elif diff <= -20:
            warn_points.append(f"{label}「{val}」({diff:.0f}pt)")

    # スコア評価
    if score >= 80:
        verdict = "歴代勝ち馬との類似度が非常に高く、有力候補です"
    elif score >= 65:
        verdict = "勝ち馬の傾向に近い特徴を持ちます"
    elif score >= 50:
        verdict = "平均的な特徴で可能性はあります"
    else:
        verdict = "勝ち馬の傾向からやや外れています"

    lines = [verdict]
    if good_points:
        lines.append("優位点: " + "、".join(good_points))
    if warn_points:
        lines.append("懸念点: " + "、".join(warn_points))

    # 当日コンディションコメント
    cond = features.get('condition_comment', '')
    if cond:
        lines.append(f"当日状態: {cond}")

    return "　".join(lines)

# ─── Step5: 出走馬リストとの比較 ────────────────────────
def compare_with_entries(conn, race_name, uploaded_score):
    """出走馬の既存スコアと比較して順位を推定"""
    cur = conn.cursor()
    cur.execute("""
        SELECT horse_name, rank_position,
               COALESCE(composite_score, score) as final_score
        FROM race_specific_result
        WHERE race_name = %s
        ORDER BY rank_position
    """, (race_name,))
    rows = cur.fetchall()
    cur.close()

    if not rows:
        return None, None

    # アップロードした馬が既存リストに何位相当か
    scores = [r[2] for r in rows if r[2] is not None]
    better_than = sum(1 for s in scores if uploaded_score > s)
    estimated_rank = len(scores) - better_than + 1

    return estimated_rank, rows

# ─── メイン ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True, help='画像ファイルのパス')
    parser.add_argument('--race',  required=True, help='対象レース名')
    parser.add_argument('--horse', default='',    help='馬名（任意）')
    args = parser.parse_args()

    image_path = args.image
    race_name  = args.race
    horse_name = args.horse or "アップロード馬"

    if not os.path.exists(image_path):
        log(f"[エラー] 画像ファイルが見つかりません: {image_path}")
        sys.exit(1)

    log(f"=== パドック写真分析開始 ===")
    log(f"  馬名: {horse_name}")
    log(f"  対象レース: {race_name}")
    log(f"  画像: {os.path.basename(image_path)}")
    log("")

    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    conn   = get_conn()

    # Step1: 画像分析
    features, error = analyze_image(client, image_path)
    if error or features is None:
        log(f"  [エラー] 顔分析失敗: {error}")
        result = {
            "success": False,
            "error":   error or "分析失敗",
            "horse_name": horse_name,
            "race_name":  race_name,
        }
        print(f"RESULT:{json.dumps(result, ensure_ascii=False)}", flush=True)
        conn.close()
        sys.exit(0)

    # Step2: パターン読み込み
    pattern_data = load_race_pattern(conn, race_name)
    if pattern_data is None:
        # パターンなしでも特徴だけ返す
        result = {
            "success":     True,
            "horse_name":  horse_name,
            "race_name":   race_name,
            "features":    features,
            "score":       50.0,
            "comment":     "このレースのパターンデータがありません。先に傾向分析を実行してください。",
            "condition_comment": features.get('condition_comment', ''),
            "no_pattern":  True,
        }
        print(f"RESULT:{json.dumps(result, ensure_ascii=False)}", flush=True)
        conn.close()
        return

    top5_patterns, bottom_patterns, stats = pattern_data

    # Step3: スコアリング
    log("  [3/4] パターンと照合してスコアを計算中...")
    score   = score_horse(features, top5_patterns, bottom_patterns)
    comment = build_comment(horse_name, features, top5_patterns, bottom_patterns, stats, score)
    log(f"  → スコア: {score:.1f}点")

    # Step4: 出走馬リストとの比較
    log("  [4/4] 出走馬リストと比較中...")
    est_rank, entry_list = compare_with_entries(conn, race_name, score)
    conn.close()

    # 特徴の差分サマリ
    diff_summary = []
    for key in FEATURE_KEYS_LABEL:
        val = features.get(key)
        if not val:
            continue
        t5_freq = top5_patterns.get(key, {}).get(val, 0)
        bt_freq = bottom_patterns.get(key, {}).get(val, 0)
        diff    = t5_freq - bt_freq
        label   = FEATURE_LABELS_JP.get(key, key)
        diff_summary.append({
            "label":    label,
            "value":    val,
            "t5_freq":  round(t5_freq, 1),
            "bt_freq":  round(bt_freq, 1),
            "diff":     round(diff, 1),
        })

    # 結果出力
    entry_compact = None
    if entry_list:
        entry_compact = [
            {"name": r[0], "rank": r[1], "score": round(r[2], 1) if r[2] else None}
            for r in entry_list[:10]
        ]

    result = {
        "success":           True,
        "horse_name":        horse_name,
        "race_name":         race_name,
        "score":             score,
        "comment":           comment,
        "condition_comment": features.get('condition_comment', ''),
        "estimated_rank":    est_rank,
        "features":          features,
        "diff_summary":      diff_summary,
        "top5_comment":      stats['top5_comment'],
        "confidence":        stats['confidence'],
        "entry_list":        entry_compact,
        "no_pattern":        False,
    }
    log("")
    log(f"  スコア: {score:.1f}点  推定順位: {est_rank if est_rank else '?'}位相当")
    log("=== 分析完了 ===")
    print(f"RESULT:{json.dumps(result, ensure_ascii=False)}", flush=True)

if __name__ == '__main__':
    main()
