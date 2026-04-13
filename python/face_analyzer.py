"""
face_analyzer.py
Claude Vision APIで馬の顔特徴を分析してDBに保存するスクリプト

使い方: python face_analyzer.py [--winners-only]
"""
import os
import sys
import json
import base64
import time
import psycopg2
import anthropic
from collections import Counter
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

ANALYSIS_ROUNDS = 3        # 多数決のための分析回数
QUALITY_THRESHOLD = 0.5   # この値未満の画像は分析をスキップ

QUALITY_PROMPT = """
この画像の品質を評価してください。
必ずJSON形式のみで返答してください（説明文・コードブロック記号は不要）。

{
  "quality_score": 0.0から1.0の数値（1.0が最高品質）,
  "has_horse_face": true/false（馬の顔が正面または斜め正面で写っているか）,
  "is_frontal": true/false（顔が正面〜45度以内か）,
  "is_clear": true/false（ピントが合っていて鮮明か）,
  "face_size": "large/medium/small"（顔が画像に占める割合）,
  "reject_reason": "合格の場合はnull、不合格の理由を短く"
}
"""

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
  "eye_aspect_ratio": 0.1〜1.0の数値（目の縦の長さ÷横の長さ。細長いほど小さい値）,
  "nose_width_ratio": 0.1〜0.6の数値（鼻の横幅÷顔全体の横幅の推定比率）,
  "face_aspect_ratio": 0.5〜2.0の数値（顔の縦÷横。面長ほど大きい値）,
  "jaw_strength_score": 0.0〜1.0の数値（顎の強さ・発達具合。強いほど1.0に近い）,
  "overall_intensity": 0.0〜1.0の数値（全体的な迫力・存在感。強いほど1.0に近い）,
  "confidence": 0.0〜1.0の数値（この分析の確信度）
}

馬の顔が写っていない・不鮮明な場合は {"error": "馬の顔が確認できません"} と返してください。
"""

LABEL_KEYS = ['nose_shape', 'eye_size', 'eye_shape', 'face_contour',
              'forehead_width', 'nostril_size', 'jaw_line', 'overall_impression']
NUMERIC_KEYS = ['eye_aspect_ratio', 'nose_width_ratio', 'face_aspect_ratio',
                'jaw_strength_score', 'overall_intensity']

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

def check_image_quality(client, image_data):
    """
    画像品質を事前チェック。
    戻り値: (quality_score, reject_reason or None)
    """
    try:
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                    {"type": "text", "text": QUALITY_PROMPT}
                ]
            }]
        )
        raw = msg.content[0].text.strip()
        j_start = raw.find('{')
        j_end = raw.rfind('}') + 1
        if j_start == -1:
            return 0.5, None
        result = json.loads(raw[j_start:j_end])
        score = float(result.get('quality_score', 0.5))
        reject = result.get('reject_reason')
        if not result.get('has_horse_face', True):
            return 0.0, "馬の顔が写っていない"
        if not result.get('is_frontal', True):
            return score * 0.5, "横向きの画像"
        if result.get('face_size') == 'small':
            return score * 0.7, "顔が小さすぎる"
        return score, None if score >= QUALITY_THRESHOLD else reject
    except Exception:
        return 0.5, None

def call_api(client, image_data):
    """1回分の分析API呼び出し"""
    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                {"type": "text", "text": ANALYSIS_PROMPT}
            ]
        }]
    )
    raw = msg.content[0].text.strip()
    j_start = raw.find('{')
    j_end = raw.rfind('}') + 1
    if j_start == -1:
        raise ValueError("JSONが返されませんでした")
    return json.loads(raw[j_start:j_end]), raw

def analyze_face_with_voting(client, abs_path):
    """
    3回分析して多数決でラベルを確定、数値は平均を取る
    戻り値: (確定済みfeatures dict, 全rawテキスト結合, 平均confidence)
    """
    image_data = encode_image(abs_path)
    label_votes = {k: [] for k in LABEL_KEYS}
    numeric_sums = {k: [] for k in NUMERIC_KEYS}
    confidences = []
    raws = []

    for round_n in range(1, ANALYSIS_ROUNDS + 1):
        try:
            features, raw = call_api(client, image_data)
            if 'error' in features:
                return None, features.get('error'), 0.0

            for k in LABEL_KEYS:
                if features.get(k):
                    label_votes[k].append(features[k])
            for k in NUMERIC_KEYS:
                v = features.get(k)
                if v is not None:
                    try:
                        numeric_sums[k].append(float(v))
                    except (TypeError, ValueError):
                        pass
            confidences.append(float(features.get('confidence', 0.5)))
            raws.append(raw)

            if round_n < ANALYSIS_ROUNDS:
                time.sleep(1.0)  # API連続呼び出し制限対策

        except Exception as e:
            print(f"      [分析{round_n}回目エラー] {e}")
            time.sleep(2.0)

    if not raws:
        return None, "全ての分析が失敗しました", 0.0

    # 多数決でラベル確定
    final = {}
    for k in LABEL_KEYS:
        votes = label_votes[k]
        if votes:
            final[k] = Counter(votes).most_common(1)[0][0]
        else:
            final[k] = None

    # 数値は平均
    for k in NUMERIC_KEYS:
        vals = numeric_sums[k]
        final[k] = round(sum(vals) / len(vals), 4) if vals else None

    avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    return final, '\n---\n'.join(raws), avg_conf

def save_feature(conn, row_id, features, raw_text, avg_confidence, analysis_count):
    """horse_face_featureの既存行を分析結果で更新"""
    cur = conn.cursor()
    cur.execute("""
        UPDATE horse_face_feature SET
            nose_shape        = %s,
            eye_size          = %s,
            eye_shape         = %s,
            face_contour      = %s,
            forehead_width    = %s,
            nostril_size      = %s,
            jaw_line          = %s,
            overall_impression= %s,
            eye_aspect_ratio  = %s,
            nose_width_ratio  = %s,
            face_aspect_ratio = %s,
            jaw_strength_score= %s,
            overall_intensity = %s,
            raw_analysis      = %s,
            avg_confidence    = %s,
            analysis_count    = %s
        WHERE id = %s
    """, (
        features.get('nose_shape'),
        features.get('eye_size'),
        features.get('eye_shape'),
        features.get('face_contour'),
        features.get('forehead_width'),
        features.get('nostril_size'),
        features.get('jaw_line'),
        features.get('overall_impression'),
        features.get('eye_aspect_ratio'),
        features.get('nose_width_ratio'),
        features.get('face_aspect_ratio'),
        features.get('jaw_strength_score'),
        features.get('overall_intensity'),
        raw_text,
        avg_confidence,
        analysis_count,
        row_id
    ))
    conn.commit()
    cur.close()

def main():
    winners_only = '--winners-only' in sys.argv
    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    print("=== 分析エンジン: Claude Vision API ===")
    conn = get_conn()
    cur = conn.cursor()

    # 未分析レコードを取得
    if winners_only:
        cur.execute("""
            SELECT id, horse_id, horse_name, image_path, race_category
            FROM horse_face_feature
            WHERE nose_shape IS NULL AND image_path IS NOT NULL AND is_winner = TRUE
            ORDER BY win_count DESC, id
        """)
        print("=== モード: 勝ち馬のみ分析 ===")
    else:
        cur.execute("""
            SELECT id, horse_id, horse_name, image_path, race_category
            FROM horse_face_feature
            WHERE nose_shape IS NULL AND image_path IS NOT NULL
            ORDER BY is_winner DESC, win_count DESC, id
        """)
        print("=== モード: 全馬分析（勝ち馬優先） ===")

    targets = cur.fetchall()
    cur.close()

    print(f"未分析: {len(targets)}頭 / 1頭あたり{ANALYSIS_ROUNDS}回分析して多数決を取ります\n")

    success = 0
    fail = 0
    for i, (row_id, horse_id, horse_name, image_path_rel, race_category) in enumerate(targets):
        print(f"[{i+1}/{len(targets)}] {horse_name} ({horse_id}) [{race_category}]")

        abs_path = os.path.join(os.path.dirname(__file__), '..', image_path_rel.lstrip('/'))
        if not os.path.exists(abs_path):
            print(f"  [スキップ] 画像ファイルなし")
            fail += 1
            continue

        try:
            # 品質チェック
            image_data_for_check = encode_image(abs_path)
            quality_score, reject_reason = check_image_quality(client, image_data_for_check)
            if quality_score < QUALITY_THRESHOLD:
                print(f"  [スキップ] 低品質画像 score={quality_score:.2f} 理由:{reject_reason}")
                fail += 1
                time.sleep(0.5)
                continue
            print(f"  品質OK: score={quality_score:.2f}")

            features, raw_text, avg_conf = analyze_face_with_voting(client, abs_path)

            if features is None:
                print(f"  [スキップ] {raw_text}")
                fail += 1
                continue

            save_feature(conn, row_id, features, raw_text, avg_conf, ANALYSIS_ROUNDS)

            # grade_race_resultの分析済みフラグを更新（勝ち馬のみ）
            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE grade_race_result SET analyzed = TRUE WHERE winner_horse_id = %s",
                (horse_id,)
            )
            conn.commit()
            cur2.close()

            print(f"  [完了] 確信度:{avg_conf} 鼻:{features.get('nose_shape')} 目:{features.get('eye_size')}")
            success += 1

        except Exception as e:
            print(f"  [エラー] {e}")
            fail += 1

        time.sleep(1.5)

    conn.close()
    print(f"\n=== 分析完了: 成功{success}頭 / 失敗{fail}頭 ===")

if __name__ == '__main__':
    main()
