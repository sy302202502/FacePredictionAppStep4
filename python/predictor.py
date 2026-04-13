"""
predictor.py
当年の重賞出走予定馬の顔を分析し、過去勝ち馬との類似度でTOP5を予想するスクリプト

精度向上の実装:
  1. 差分分析: 勝ち馬率 - 負け馬率 の差が大きい特徴を重視
  2. レース種別プロファイル: 対象レースの種別に合ったプロファイルで比較
  3. 数値特徴量スコアリング: ラベルだけでなく数値の近さも加味
  4. 多数決分析: 出走馬も3回分析して安定化

使い方:
  python predictor.py "レース名" "馬名1,horse_id1" "馬名2,horse_id2" ...
  または
  python predictor.py "レース名" horses.json
"""
import sys
import os
import json
import base64
import time
import psycopg2
import anthropic
import requests
from collections import Counter
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '../uploads/candidates')
ANALYSIS_ROUNDS = 3

LABEL_KEYS = ['nose_shape', 'eye_size', 'eye_shape', 'face_contour',
              'forehead_width', 'nostril_size', 'jaw_line', 'overall_impression']
NUMERIC_KEYS = ['eye_aspect_ratio', 'nose_width_ratio', 'face_aspect_ratio',
                'jaw_strength_score', 'overall_intensity']

CATEGORY_LABEL = {
    'sprint': '短距離（〜1400m）',
    'mile':   'マイル（1600〜1800m）',
    'middle': '中距離（2000〜2200m）',
    'long':   '長距離（2400m〜）',
    'dirt':   'ダート',
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
  "eye_aspect_ratio": 0.1から1.0の数値（目の縦÷横。細長いほど小さい）,
  "nose_width_ratio": 0.1から0.6の数値（鼻幅÷顔幅の推定比率）,
  "face_aspect_ratio": 0.5から2.0の数値（顔の縦÷横。面長ほど大きい）,
  "jaw_strength_score": 0.0から1.0の数値（顎の強さ）,
  "overall_intensity": 0.0から1.0の数値（全体的な迫力）,
  "confidence": 0.0から1.0の数値（分析の確信度）
}

馬の顔が写っていない場合は {"error": "馬の顔が確認できません"} と返してください。
"""

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def build_diff_profile(conn, race_category=None):
    """
    勝ち馬と負け馬の特徴分布を比較して差分プロファイルを構築。
    戻り値: (winner_dist, diff_weights, numeric_profile)
    """
    cur = conn.cursor()
    cat_cond = " AND race_category = %s" if race_category else ""

    cur.execute(f"""
        SELECT nose_shape, eye_size, eye_shape, face_contour,
               forehead_width, nostril_size, jaw_line, overall_impression,
               eye_aspect_ratio, nose_width_ratio, face_aspect_ratio,
               jaw_strength_score, overall_intensity, win_count
        FROM horse_face_feature
        WHERE nose_shape IS NOT NULL AND is_winner = TRUE{cat_cond}
    """, ([race_category] if race_category else []))
    winners = cur.fetchall()

    cur.execute(f"""
        SELECT nose_shape, eye_size, eye_shape, face_contour,
               forehead_width, nostril_size, jaw_line, overall_impression,
               eye_aspect_ratio, nose_width_ratio, face_aspect_ratio,
               jaw_strength_score, overall_intensity, 1 as weight
        FROM horse_face_feature
        WHERE nose_shape IS NOT NULL AND is_winner = FALSE{cat_cond}
    """, ([race_category] if race_category else []))
    losers = cur.fetchall()
    cur.close()

    if not winners:
        return {}, {}, {}

    def label_dist(rows):
        freq = {k: {} for k in LABEL_KEYS}
        totals = {k: 0 for k in LABEL_KEYS}
        for row in rows:
            w = row[13] or 1
            for idx, k in enumerate(LABEL_KEYS):
                val = row[idx]
                if val:
                    freq[k][val] = freq[k].get(val, 0) + w
                    totals[k] += w
        return {k: {v: c / totals[k] for v, c in freq[k].items()} for k in LABEL_KEYS if totals[k] > 0}

    def numeric_mean(rows):
        sums = {k: [] for k in NUMERIC_KEYS}
        for row in rows:
            for i, k in enumerate(NUMERIC_KEYS):
                v = row[8 + i]
                if v is not None:
                    sums[k].append(float(v))
        return {k: (sum(v) / len(v) if v else None) for k, v in sums.items()}

    w_dist = label_dist(winners)
    l_dist = label_dist(losers) if losers else {}

    diff_weights = {}
    for k in LABEL_KEYS:
        diff_weights[k] = {}
        all_vals = set(w_dist.get(k, {}).keys()) | set(l_dist.get(k, {}).keys())
        for val in all_vals:
            diff_weights[k][val] = round(
                w_dist.get(k, {}).get(val, 0.0) - l_dist.get(k, {}).get(val, 0.0), 4)

    w_num = numeric_mean(winners)
    l_num = numeric_mean(losers) if losers else {k: None for k in NUMERIC_KEYS}
    numeric_profile = {k: {'winner_mean': w_num.get(k), 'loser_mean': l_num.get(k)} for k in NUMERIC_KEYS}

    return w_dist, diff_weights, numeric_profile

def calc_score(features, winner_dist, diff_weights, numeric_profile):
    """最終スコア = 類似度40% + 差分40% + 数値20%"""
    # 類似度スコア
    sim_total, sim_count = 0.0, 0
    for k in LABEL_KEYS:
        val = features.get(k)
        if val and k in winner_dist:
            sim_total += winner_dist[k].get(val, 0.0) * 100
            sim_count += 1
    similarity_score = round(sim_total / sim_count, 2) if sim_count > 0 else 0.0

    # 差分スコア
    diff_total, diff_count = 0.0, 0
    for k in LABEL_KEYS:
        val = features.get(k)
        if val and k in diff_weights:
            diff_total += diff_weights[k].get(val, 0.0)
            diff_count += 1
    diff_score = round(((diff_total / diff_count) + 1) * 50, 2) if diff_count > 0 else 50.0

    # 数値スコア
    num_total, num_count = 0.0, 0
    for k in NUMERIC_KEYS:
        val = features.get(k)
        w_mean = numeric_profile.get(k, {}).get('winner_mean')
        l_mean = numeric_profile.get(k, {}).get('loser_mean')
        if val is not None and w_mean is not None:
            d_w = abs(val - w_mean)
            d_l = abs(val - l_mean) if l_mean is not None else None
            if d_l is not None and (d_w + d_l) > 0.001:
                num_total += d_l / (d_w + d_l) * 100
            else:
                num_total += max(0.0, 100 - d_w * 200)
            num_count += 1
    numeric_score = round(num_total / num_count, 2) if num_count > 0 else 50.0

    final_score = round(similarity_score * 0.4 + diff_score * 0.4 + numeric_score * 0.2, 2)
    return similarity_score, diff_score, final_score

def encode_image(path):
    with open(path, 'rb') as f:
        return base64.standard_b64encode(f.read()).decode('utf-8')

def call_api(client, image_data):
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
    return json.loads(raw[j_start:j_end])

def analyze_candidate(client, abs_path):
    """出走馬を3回分析して多数決・平均を返す"""
    image_data = encode_image(abs_path)
    label_votes = {k: [] for k in LABEL_KEYS}
    numeric_sums = {k: [] for k in NUMERIC_KEYS}

    for _ in range(ANALYSIS_ROUNDS):
        try:
            f = call_api(client, image_data)
            if 'error' in f:
                return None
            for k in LABEL_KEYS:
                if f.get(k):
                    label_votes[k].append(f[k])
            for k in NUMERIC_KEYS:
                v = f.get(k)
                if v is not None:
                    try:
                        numeric_sums[k].append(float(v))
                    except (TypeError, ValueError):
                        pass
            time.sleep(1.0)
        except Exception as e:
            print(f"      [分析エラー] {e}")
            time.sleep(2.0)

    result = {}
    for k in LABEL_KEYS:
        result[k] = Counter(label_votes[k]).most_common(1)[0][0] if label_votes[k] else None
    for k in NUMERIC_KEYS:
        vals = numeric_sums[k]
        result[k] = round(sum(vals) / len(vals), 4) if vals else None
    return result

def download_candidate_image(horse_id, horse_name):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(UPLOAD_DIR, f"{horse_id}.jpg")
    if os.path.exists(save_path):
        return f"/uploads/candidates/{horse_id}.jpg"
    for url_t in [
        f"https://cdn.netkeiba.com/horse/pic/{horse_id}_l.jpg",
        f"https://cdn.netkeiba.com/horse/pic/{horse_id}.jpg",
    ]:
        try:
            r = requests.get(url_t, headers=HEADERS, timeout=10)
            if r.status_code == 200 and len(r.content) > 5000:
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                return f"/uploads/candidates/{horse_id}.jpg"
        except Exception:
            pass
    return None

def save_prediction(conn, race_name, race_category, horse_name, horse_id,
                    image_path, sim_score, diff_score, final_score, rank, detail):
    from datetime import date
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO prediction_result
            (target_race_name, target_race_date, race_category,
             horse_name, horse_id, image_path,
             similarity_score, diff_score, final_score, rank_position, analysis_detail)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (race_name, date.today(), race_category,
          horse_name, horse_id, image_path,
          sim_score, diff_score, final_score, rank, detail))
    conn.commit()
    cur.close()

def infer_race_category(race_name):
    """レース名から種別を推測"""
    name = race_name
    if any(k in name for k in ['スプリント', '高松宮', 'スプリンターズ', 'セントウル']):
        return 'sprint'
    if any(k in name for k in ['マイル', 'NHK', '安田', 'ヴィクトリア']):
        return 'mile'
    if any(k in name for k in ['ダービー', '皐月', '秋華', 'エリザベス', '宝塚', '有馬', '天皇賞']):
        return 'middle'
    if any(k in name for k in ['菊花', 'ステイヤーズ', 'アルゼンチン']):
        return 'long'
    if any(k in name for k in ['チャンピオンズ', 'フェブラリー', 'かしわ', '帝王']):
        return 'dirt'
    return None

def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("使い方: python predictor.py \"レース名\" \"馬名1,horse_id1\" ...")
        print("  または: python predictor.py \"レース名\" horses.json")
        sys.exit(1)

    race_name = args[0]
    horse_list = []
    if len(args) == 2 and args[1].endswith('.json'):
        with open(args[1], 'r', encoding='utf-8') as f:
            horse_list = json.load(f)
    else:
        for arg in args[1:]:
            parts = arg.split(',', 1)
            if len(parts) == 2:
                horse_list.append({'name': parts[0].strip(), 'horse_id': parts[1].strip()})

    if not horse_list:
        print("[エラー] 出走馬リストが空です")
        sys.exit(1)

    race_category = infer_race_category(race_name)
    print(f"\n=== 予想開始: {race_name} ===")
    print(f"  種別: {CATEGORY_LABEL.get(race_category, '不明（全体プロファイル使用）')}")
    print(f"  出走馬: {len(horse_list)}頭\n")

    client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
    conn = get_conn()

    print("差分プロファイル構築中...")
    w_dist, diff_w, num_prof = build_diff_profile(conn, race_category)
    if not w_dist:
        print(f"  [{race_category}]データ不足 → 全体プロファイルを使用")
        w_dist, diff_w, num_prof = build_diff_profile(conn, None)
    if not w_dist:
        print("[エラー] 分析済みデータがありません。face_analyzer.pyを先に実行してください。")
        conn.close()
        sys.exit(1)
    print(f"  完了\n")

    results = []
    for i, horse in enumerate(horse_list):
        name = horse['name']
        hid = horse['horse_id']
        print(f"[{i+1}/{len(horse_list)}] {name} ({hid}) — {ANALYSIS_ROUNDS}回分析中...")

        image_path = download_candidate_image(hid, name)
        if not image_path:
            print(f"  [スキップ] 画像取得失敗")
            continue

        abs_path = os.path.join(os.path.dirname(__file__), '..', image_path.lstrip('/'))
        features = analyze_candidate(client, abs_path)
        if not features:
            print(f"  [スキップ] 顔分析失敗")
            continue

        sim, diff, final = calc_score(features, w_dist, diff_w, num_prof)
        results.append({'name': name, 'horse_id': hid, 'image_path': image_path,
                        'features': features, 'sim': sim, 'diff': diff, 'final': final})
        print(f"  類似:{sim:.1f} 差分:{diff:.1f} 最終:{final:.1f}")

    results.sort(key=lambda x: x['final'], reverse=True)

    print(f"\n{'='*55}")
    print(f"  【{race_name}】優勝候補 TOP5")
    print(f"  種別: {CATEGORY_LABEL.get(race_category, '全体')}")
    print(f"{'='*55}")
    for rank, r in enumerate(results[:5], 1):
        medals = ['1位', '2位', '3位', '4位', '5位']
        print(f"  {medals[rank-1]}: {r['name']:12s} 最終:{r['final']:.1f}点"
              f" (類似:{r['sim']:.1f} 差分:{r['diff']:.1f})")
        save_prediction(conn, race_name, race_category or 'all',
                        r['name'], r['horse_id'], r['image_path'],
                        r['sim'], r['diff'], r['final'],
                        rank, json.dumps(r['features'], ensure_ascii=False))
    print(f"{'='*55}")

    conn.close()

if __name__ == '__main__':
    main()
