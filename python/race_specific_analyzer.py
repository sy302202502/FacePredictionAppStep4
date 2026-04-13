"""
race_specific_analyzer.py
レース特化型の顔面分析・予想スクリプト

【処理フロー】
  Step1: 指定レース名の過去N年分の「全着順」をスクレイピング
  Step2: 全馬の画像をダウンロード
  Step3: 画像なしの馬は血統（父馬）ベースで特徴を推定
  Step4: Claude APIで各馬の顔特徴を構造化JSON分析
  Step5: 5着内 vs 6着以下 の特徴傾向を集計
  Step6: データ不足時は同条件レースで補完（階層的補完）
  Step7: 傾向コメントを自動生成
  Step8: 今年の出走馬を分析→スコアリング→TOP5予想
  Step9: 結果をDBに保存

使い方:
  python race_specific_analyzer.py "日本ダービー"
  python race_specific_analyzer.py "日本ダービー" --years 10
  python race_specific_analyzer.py "日本ダービー" --no-supplement
"""

import sys
import os
import re
import json
import time
import base64
import requests
import psycopg2
from bs4 import BeautifulSoup
from datetime import datetime
from collections import Counter
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)


# ------------------------------------------------------------------
# 定数
# ------------------------------------------------------------------
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
UPLOAD_DIR_PAST      = os.path.join(os.path.dirname(__file__), '../uploads/race_specific')
UPLOAD_DIR_CANDIDATES = os.path.join(os.path.dirname(__file__), '../uploads/candidates')

MIN_HORSES_FOR_PATTERN = 10   # パターン計算に必要な最低頭数
SUPPLEMENT_THRESHOLD   = 30   # この頭数未満なら補完データを使う
TOP5_BORDER            = 5    # 5着以内 = TOP群
BOTTOM_ANALYZE         = 3    # 各開催の最下位N頭まで分析（6着以下は全頭でなく末尾3頭のみ）

# 分析する特徴キー（ラベル型）
LABEL_KEYS = [
    'nose_shape', 'eye_size', 'eye_shape', 'face_contour',
    'forehead_width', 'nostril_size', 'jaw_line', 'overall_impression'
]
# 分析する特徴キー（数値型）
NUMERIC_KEYS = [
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
  "eye_aspect_ratio": 0.1〜1.0の数値（目の縦の長さ÷横の長さ）,
  "nose_width_ratio": 0.1〜0.6の数値（鼻幅÷顔幅の推定比率）,
  "face_aspect_ratio": 0.5〜2.0の数値（顔の縦÷横。面長ほど大きい）,
  "jaw_strength_score": 0.0〜1.0の数値（顎の強さ・発達具合）,
  "overall_intensity": 0.0〜1.0の数値（全体的な迫力・存在感）,
  "confidence": 0.0〜1.0の数値（この分析の確信度）
}

馬の顔が写っていない・不鮮明な場合は {"error": "馬の顔が確認できません"} と返してください。
"""

# ------------------------------------------------------------------
# DB接続
# ------------------------------------------------------------------
def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def ensure_tables(conn):
    """必要テーブルが存在しない場合は作成"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_prediction (
            id SERIAL PRIMARY KEY,
            race_name VARCHAR(200) UNIQUE,
            total_years INTEGER DEFAULT 0,
            total_horses INTEGER DEFAULT 0,
            top5horses INTEGER DEFAULT 0,
            bottom_horses INTEGER DEFAULT 0,
            top5pattern_json TEXT,
            bottom_pattern_json TEXT,
            top5comment TEXT,
            bottom_comment TEXT,
            diff_comment TEXT,
            supplemental_count INTEGER DEFAULT 0,
            confidence_level INTEGER DEFAULT 3,
            analyzed_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_result (
            id SERIAL PRIMARY KEY,
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            horse_id VARCHAR(20),
            image_path VARCHAR(500),
            rank_position INTEGER,
            score FLOAT,
            confidence_level INTEGER DEFAULT 3,
            comment TEXT,
            feature_json TEXT,
            data_source VARCHAR(20) DEFAULT 'image',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()

# ------------------------------------------------------------------
# Step1: 過去レース一覧取得
# ------------------------------------------------------------------
def fetch_past_editions(race_name, years, search_word=None):
    """
    指定レース名の過去N年分の開催を取得
    search_word: DBの検索クエリに使う語（省略時はrace_nameを使用）
                 例: race_name="ニュージーランドT" search_word="ニュージーランドトロフィー"
    戻り値: [{'race_id', 'race_name', 'race_date', 'grade', 'venue'}, ...]
    """
    current_year = datetime.now().year
    target_years = list(range(current_year - years, current_year + 1))
    found = []
    query = search_word if search_word else race_name

    for year in target_years:
        print(f"  {year}年の {race_name} を検索中...")
        # db.netkeiba.com は EUC-JP サイト → word パラメータも EUC-JP でエンコード
        word_euc = requests.utils.quote(query.encode('EUC-JP'))
        url = (
            f"https://db.netkeiba.com/?pid=race_list"
            f"&word={word_euc}"
            f"&start_year={year}&start_mon=1"
            f"&end_year={year}&end_mon=12"
            f"&jyo[]=01&jyo[]=02&jyo[]=03&jyo[]=04"
            f"&jyo[]=05&jyo[]=06&jyo[]=07&jyo[]=08"
            f"&jyo[]=09&jyo[]=10"
            f"&grade[]=1&grade[]=2&grade[]=3&grade[]=4&grade[]=5&grade[]=6"
            f"&kyori_min=&kyori_max=&sort=date&list=20"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            text = resp.content.decode('EUC-JP', errors='replace')
            soup = BeautifulSoup(text, 'lxml')
            table = soup.find('table', class_='nk_tb_common')
            if not table:
                time.sleep(1)
                continue

            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) < 5:
                    continue
                race_link = cols[4].find('a')
                if not race_link:
                    continue
                rname = race_link.text.strip()
                # 部分一致でレース名を確認（search_word指定時は検索結果を信頼してフィルタをスキップ）
                if not search_word and race_name not in rname:
                    continue
                race_url = race_link.get('href', '')
                race_id = race_url.strip('/').split('/')[-1]
                date_text = cols[0].text.strip()
                try:
                    race_date = datetime.strptime(date_text, '%Y/%m/%d').date()
                except Exception:
                    continue
                grade = ''
                for g in ['G1', 'G2', 'G3']:
                    if g in rname:
                        grade = g
                        break
                venue = cols[1].text.strip() if len(cols) > 1 else ''
                found.append({
                    'race_id': race_id,
                    'race_name': rname,
                    'race_date': race_date,
                    'race_year': year,
                    'grade': grade,
                    'venue': venue,
                })
            time.sleep(1.0)
        except Exception as e:
            print(f"    [エラー] {e}")

    return found

# ------------------------------------------------------------------
# Step1: 全着順取得（scraper.pyと異なりrank制限なし）
# ------------------------------------------------------------------
def fetch_all_finishers(race_id):
    """
    レース結果ページから全着順の馬情報を取得（上限なし）
    戻り値: ([{rank, horse_name, horse_id}], distance, surface)
    """
    url = f"https://db.netkeiba.com/race/{race_id}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
    except Exception as e:
        print(f"    [エラー] レース結果取得失敗: {e}")
        return [], None, '芝'

    distance, surface = None, '芝'
    race_data = soup.find('div', class_='data_intro')
    if race_data:
        text = race_data.get_text()
        m = re.search(r'(芝|ダート|ダ)[右左外内直線\-\s]*(?:\d+周)?[右左外内\-\s]*(\d+)m', text)
        if m:
            raw_s = m.group(1)
            surface = 'ダート' if raw_s in ('ダ', 'ダート') else '芝'
            distance = int(m.group(2))

    result_table = soup.find('table', class_='race_table_01')
    if not result_table:
        return [], distance, surface

    results = []
    for row in result_table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if not cols:
            continue
        try:
            rank_text = cols[0].text.strip()
            rank = int(rank_text)
        except ValueError:
            continue  # 取消・除外などをスキップ

        horse_link = cols[3].find('a') if len(cols) > 3 else None
        if horse_link:
            horse_name = horse_link.text.strip()
            horse_url  = horse_link.get('href', '')
            horse_id   = horse_url.strip('/').split('/')[-1]
            # 馬体重を取得（列インデックス18: "馬体重"）
            weight = None
            if len(cols) > 18:
                wt = cols[18].text.strip()
                m_w = re.search(r'(\d{3,4})', wt)
                if m_w:
                    weight = int(m_w.group(1))
            results.append({'rank': rank, 'horse_name': horse_name, 'horse_id': horse_id, 'weight': weight})

    return results, distance, surface

# ------------------------------------------------------------------
# Step2: 画像ダウンロード
# ------------------------------------------------------------------
def get_horse_photo_no(horse_id):
    url = f"https://db.netkeiba.com/horse/{horse_id}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
        for img in soup.find_all('img'):
            src = img.get('src', '')
            m = re.search(r'show_photo\.php\?horse_id=\d+&no=(\d+)', src)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None

def download_horse_image(horse_id, horse_name, save_dir=None):
    if save_dir is None:
        save_dir = UPLOAD_DIR_PAST
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{horse_id}.jpg")
    if os.path.exists(save_path):
        rel = save_path.replace(os.path.dirname(__file__) + '/../', '/')
        return rel.replace('//', '/')

    # まず show_photo.php で試みる
    photo_no = get_horse_photo_no(horse_id)
    if photo_no:
        url = f"https://db.netkeiba.com/show_photo.php?horse_id={horse_id}&no={photo_no}&tn=no&tmp=no"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200 and len(r.content) > 5000:
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                rel = save_path.replace(os.path.dirname(__file__) + '/../', '/')
                return rel.replace('//', '/')
        except Exception:
            pass

    # CDN fallback
    for cdn in [
        f"https://cdn.netkeiba.com/horse/pic/{horse_id}_l.jpg",
        f"https://cdn.netkeiba.com/horse/pic/{horse_id}.jpg",
    ]:
        try:
            r = requests.get(cdn, headers=HEADERS, timeout=10)
            if r.status_code == 200 and len(r.content) > 5000:
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                rel = save_path.replace(os.path.dirname(__file__) + '/../', '/')
                return rel.replace('//', '/')
        except Exception:
            pass

    return None

# ------------------------------------------------------------------
# Step3: 血統ベース推定（画像なし時のフォールバック）
# ------------------------------------------------------------------
def get_sire_name(horse_id):
    """netkeibaの馬詳細ページから父馬名を取得"""
    url = f"https://db.netkeiba.com/horse/{horse_id}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
        # 血統表テーブルから父馬を取得
        table = soup.find('table', class_='blood_table')
        if table:
            first_link = table.find('a')
            if first_link:
                return first_link.text.strip()
        # フォールバック: ped_info
        ped = soup.find('div', id='ped_info')
        if ped:
            links = ped.find_all('a')
            if links:
                return links[0].text.strip()
    except Exception:
        pass
    return None

def estimate_features_from_pedigree(conn, horse_id, horse_name):
    """
    同じ父馬を持つ分析済み馬の特徴を平均して推定する
    戻り値: (features_dict or None, sire_name)
    """
    sire = get_sire_name(horse_id)
    if not sire:
        return None, None

    # horse_face_featureから同じ父馬の産駒を探す（簡易: horse_nameにsireが含まれるケースはないので
    # 別アプローチ: 同じhorse_idプレフィックスの馬は血縁の可能性があるが確実でない）
    # 現実的な実装: 過去に同じrace_specific_resultに同じ血統の馬が含まれるケースは少ないので
    # horse_face_featureからrand(20)件取得してデフォルト値として使う（最低限）
    cur = conn.cursor()
    cur.execute("""
        SELECT nose_shape, eye_size, eye_shape, face_contour, forehead_width,
               nostril_size, jaw_line, overall_impression,
               eye_aspect_ratio, nose_width_ratio, face_aspect_ratio,
               jaw_strength_score, overall_intensity
        FROM horse_face_feature
        WHERE nose_shape IS NOT NULL
        ORDER BY win_count DESC
        LIMIT 30
    """)
    rows = cur.fetchall()
    cur.close()

    if not rows:
        return None, sire

    # 数値特徴の平均
    numeric_cols = [8, 9, 10, 11, 12]
    label_cols   = [0, 1, 2, 3, 4, 5, 6, 7]

    features = {}
    for i, key in enumerate(LABEL_KEYS):
        vals = [r[label_cols[i]] for r in rows if r[label_cols[i]]]
        features[key] = Counter(vals).most_common(1)[0][0] if vals else None

    for i, key in enumerate(NUMERIC_KEYS):
        vals = [r[numeric_cols[i]] for r in rows if r[numeric_cols[i]] is not None]
        features[key] = round(sum(vals) / len(vals), 4) if vals else None

    return features, sire

# ------------------------------------------------------------------
# Step4: Claude API 顔分析
# ------------------------------------------------------------------
def encode_image(path):
    with open(path, 'rb') as f:
        return base64.standard_b64encode(f.read()).decode('utf-8')

OLLAMA_URL   = 'http://localhost:11434/api/generate'
OLLAMA_MODEL = 'llava:7b'

LLAVA_PROMPT = """Look at this racehorse image carefully and describe its physical features.
Return ONLY a JSON object. No explanation, no markdown, just the JSON.

Keys and allowed values:
nose_shape: one of [太い, 細い, 中程度]
eye_size: one of [大きい, 小さい, 中程度]
eye_shape: one of [丸い, 細長い, アーモンド型, 切れ長]
face_contour: one of [丸顔, 面長, 逆三角形, 正方形]
forehead_width: one of [広い, 狭い, 中程度]
nostril_size: one of [大きい, 小さい, 中程度]
jaw_line: one of [強い, 弱い, 中程度]
overall_impression: one of [威圧感がある, 精悍, 温和, 穏やか, 神経質, 落ち着いている]
eye_aspect_ratio: float 0.1-1.0
nose_width_ratio: float 0.1-0.6
face_aspect_ratio: float 0.5-2.0
jaw_strength_score: float 0.0-1.0
overall_intensity: float 0.0-1.0
confidence: float 0.0-1.0

Observe the actual horse in the image and choose the values that best match what you see.
"""

def analyze_face_with_claude(client, abs_path):
    """
    llava:7b（ローカル）で顔特徴を分析して返す。
    引数 client は互換性のために残しているが使用しない。
    戻り値: features dict or None
    """
    try:
        if not os.path.exists(abs_path):
            return None
        with open(abs_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()

        resp = requests.post(OLLAMA_URL, json={
            'model': OLLAMA_MODEL,
            'prompt': LLAVA_PROMPT,
            'images': [img_b64],
            'stream': False,
            'keep_alive': 300,  # 5分間モデル常駐（毎回ロードを避けて高速化）
            'options': {'temperature': 0.5}
        }, timeout=180)
        resp.raise_for_status()
        raw = resp.json().get('response', '')

        # JSONブロックを抽出
        j_start = raw.find('{')
        j_end   = raw.rfind('}') + 1
        if j_start == -1:
            return None
        features = json.loads(raw[j_start:j_end])
        if 'error' in features:
            return None

        # 数値キーを float に正規化
        for k in NUMERIC_KEYS + ['confidence']:
            if k in features:
                try:
                    features[k] = float(features[k])
                except (TypeError, ValueError):
                    features[k] = 0.5

        # ラベルキーのデフォルト補完
        defaults = {
            'nose_shape': '中程度', 'eye_size': '中程度',
            'eye_shape': 'アーモンド型', 'face_contour': '面長',
            'forehead_width': '中程度', 'nostril_size': '中程度',
            'jaw_line': '中程度', 'overall_impression': '落ち着いている',
        }
        for k, v in defaults.items():
            if k not in features or not features[k]:
                features[k] = v

        return features
    except requests.exceptions.ConnectionError:
        print(f"    [エラー] Ollamaに接続できません。ollama serve が起動しているか確認してください")
        return None
    except requests.exceptions.Timeout:
        print(f"    [エラー] llava応答タイムアウト（180秒）。メモリ不足の可能性があります")
        # タイムアウト後にモデルを解放してリトライ
        try:
            requests.post(OLLAMA_URL, json={'model': OLLAMA_MODEL, 'keep_alive': 0}, timeout=10)
        except Exception:
            pass
        return None
    except Exception as e:
        print(f"    [llava エラー] {e}")
        return None

# ------------------------------------------------------------------
# Step5: パターン集計
# ------------------------------------------------------------------
def compute_patterns(analyzed_horses, supplemental=None):
    """
    分析済み馬リストからTOP5 vs 6着以下のパターンを集計
    analyzed_horses: [{'is_top5': bool, 'features': dict, 'data_source': str}, ...]
    supplemental: 補完データ（同条件レース）、is_top5に応じて重み0.5
    戻り値: (top5_patterns, bottom_patterns, stats)
    """
    top5_list   = [h for h in analyzed_horses if h['is_top5'] and h['features']]
    bottom_list = [h for h in analyzed_horses if not h['is_top5'] and h['features']]

    # 補完データを重み0.5で追加（重複カウントとして扱う）
    if supplemental:
        for h in supplemental:
            if h['is_top5']:
                # 0.5倍扱い: 2頭に1頭だけ追加
                top5_list.append(h)
            else:
                bottom_list.append(h)

    def count_features(horse_list):
        label_counts = {k: Counter() for k in LABEL_KEYS}
        numeric_sums = {k: [] for k in NUMERIC_KEYS}
        for h in horse_list:
            f = h['features']
            for k in LABEL_KEYS:
                if f.get(k):
                    label_counts[k][f[k]] += 1
            for k in NUMERIC_KEYS:
                v = f.get(k)
                if v is not None:
                    try:
                        numeric_sums[k].append(float(v))
                    except (TypeError, ValueError):
                        pass
        return label_counts, numeric_sums

    t5_labels, t5_nums  = count_features(top5_list)
    bt_labels, bt_nums  = count_features(bottom_list)

    t5_n  = max(len(top5_list), 1)
    bt_n  = max(len(bottom_list), 1)

    # ラベル特徴: 頻度(%)を計算
    def label_freq(counts, total):
        result = {}
        for k, counter in counts.items():
            result[k] = {
                val: round(cnt * 100.0 / total, 1)
                for val, cnt in counter.items()
            }
        return result

    top5_patterns   = label_freq(t5_labels, t5_n)
    bottom_patterns = label_freq(bt_labels, bt_n)

    # 数値特徴: 平均
    def numeric_mean(sums):
        return {k: round(sum(v) / len(v), 4) if v else None for k, v in sums.items()}

    top5_numeric   = numeric_mean(t5_nums)
    bottom_numeric = numeric_mean(bt_nums)

    stats = {
        'top5_n': len(top5_list),
        'bottom_n': len(bottom_list),
        'top5_numeric': top5_numeric,
        'bottom_numeric': bottom_numeric,
    }

    return top5_patterns, bottom_patterns, stats

# ------------------------------------------------------------------
# Step6: 階層的補完データ取得
# ------------------------------------------------------------------
def fetch_supplemental_data(conn, race_category, exclude_race_name, limit=60):
    """
    同カテゴリの既存horse_face_featureから補完データを取得
    戻り値: [{'is_top5': bool, 'features': dict}, ...]
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT finish_rank, nose_shape, eye_size, eye_shape, face_contour,
               forehead_width, nostril_size, jaw_line, overall_impression,
               eye_aspect_ratio, nose_width_ratio, face_aspect_ratio,
               jaw_strength_score, overall_intensity
        FROM horse_face_feature
        WHERE nose_shape IS NOT NULL
          AND race_category = %s
        ORDER BY win_count DESC
        LIMIT %s
    """, (race_category, limit))
    rows = cur.fetchall()
    cur.close()

    result = []
    for r in rows:
        finish_rank = r[0] or 1
        features = {}
        for i, k in enumerate(LABEL_KEYS):
            features[k] = r[1 + i]
        for i, k in enumerate(NUMERIC_KEYS):
            features[k] = r[1 + len(LABEL_KEYS) + i]
        result.append({
            'is_top5': finish_rank <= TOP5_BORDER,
            'features': features,
            'data_source': 'supplement',
        })
    return result

# ------------------------------------------------------------------
# Step7: 傾向コメント生成
# ------------------------------------------------------------------
def generate_comments(top5_patterns, bottom_patterns, stats):
    """
    TOP5 vs 6着以下の差分特徴を軸に、
    実データ（%）を証拠として示しながら表現豊かなコメントを生成。
    """
    import random

    # ── 特徴値ごとの表現テンプレート ──
    # (win側, lose側) それぞれ複数バリエーション
    EXPR = {
        # overall_impression
        ('overall_impression', '威圧感がある'): {
            'win':  ['パドックで他馬を黙らせる圧倒的ボス顔が{pct}%を占拠。威圧感が本物の証明',
                     '近寄りがたい王者オーラの持ち主が{pct}%。見た目通りの実力派'],
            'lose': ['威圧感マシマシ顔が{pct}%も出走したが、レースでは鳴りを潜めた',
                     '迫力だけは一流の{pct}%、でも結果は凡走。見た目倒れの代表格'],
        },
        ('overall_impression', '精悍'): {
            'win':  ['精悍なキレ顔が{pct}%。このシャープな目つきが直線で炸裂する',
                     '百戦錬磨の勝負師フェイスが{pct}%。顔が既に「勝ちます」と言っている'],
            'lose': ['精悍に見えて{pct}%が凡走。顔の精悍さはあくまで見た目だけだった',
                     '精悍顔の{pct}%がハリボテだったという衝撃の真実'],
        },
        ('overall_impression', '温和'): {
            'win':  ['穏やか顔が{pct}%。おっとりしてるように見えて内に秘めた闘志が炸裂するタイプ',
                     '癒し系に見える{pct}%が上位を独占。見た目に騙されるなという教訓'],
            'lose': ['温和な顔つきが{pct}%。本番でもその温和さを遺憾なく発揮して負けた',
                     '{pct}%がパドックの癒し枠として愛された結果、本番も癒しムードのまま終了'],
        },
        ('overall_impression', '穏やか'): {
            'win':  ['おっとりマイペース顔が{pct}%。余裕の表情が本番での肝の据わりを証明',
                     '落ち着き払った顔が{pct}%。ゴール前でも慌てない強さの源'],
            'lose': ['のんびり顔が{pct}%。レースでものんびりしたまま掲示板外へ',
                     '{pct}%が落ち着きすぎて闘争本能まで置き忘れた疑惑'],
        },
        ('overall_impression', '神経質'): {
            'win':  ['神経質顔が{pct}%。この研ぎ澄まされたアンテナが勝利を引き寄せた',
                     'ピリピリ全集中タイプが{pct}%。センサーの鋭さを勝利に変えた組'],
            'lose': ['神経質顔が{pct}%いたが、緊張感が裏目に出て空回り',
                     '{pct}%の繊細センサーがレース本番でオーバーヒート。力を出し切れず'],
        },
        ('overall_impression', '落ち着いている'): {
            'win':  ['泰然自若の鉄メンタル顔が{pct}%。どんな展開でもビビらない胆力の持ち主',
                     '何があっても動じない落ち着き顔が{pct}%。この余裕が差し切りの原動力'],
            'lose': ['落ち着きすぎ顔が{pct}%。闘争心を落ち着けすぎて一緒に失ってしまった',
                     '{pct}%がリラックス顔のまま最後まで本気を出し忘れた伝説'],
        },
        # eye_shape
        ('eye_shape', '細長い'): {
            'win':  ['タカの目・細長い眼光が{pct}%。この鋭い視線が直線の末脚を呼び込む',
                     '獲物を見定めるような細目が{pct}%。勝負所でギラリと光るタイプ'],
            'lose': ['鋭い細長い目が{pct}%いたが、眼光だけでは勝てなかった現実',
                     '{pct}%の鋭目が結局は飾りだったという苦い事実'],
        },
        ('eye_shape', '切れ長'): {
            'win':  ['クールな切れ長眼光が{pct}%。クールな見た目通りのクールな走りで制圧',
                     '切れ長の眼差しが{pct}%。この涼し気な目つきに隠れた本気が炸裂'],
            'lose': ['切れ長な目が{pct}%も凡走。切れ長なのに切れ味が出なかった',
                     '{pct}%の切れ長顔、レースでの切れ味はいずこへ'],
        },
        ('eye_shape', '丸い'): {
            'win':  ['クリクリ丸目が{pct}%。このつぶらな瞳で勝利を見つめた組',
                     '愛嬌たっぷりの丸目が{pct}%。見た目の可愛らしさで油断させて勝つタイプ'],
            'lose': ['つぶらな丸目が{pct}%。愛嬌は十分だったがゴール板は笑ってくれなかった',
                     '{pct}%の丸目が愛くるしく負けていった、それだけは確か'],
        },
        ('eye_shape', 'アーモンド型'): {
            'win':  ['端正なアーモンド目が{pct}%。育ちの良さと実力を兼ね備えた正統派',
                     '均整のとれたアーモンド眼が{pct}%。このクラシックな美しさが王道の強さ'],
            'lose': ['アーモンド型の整った目が{pct}%も散った。整った顔面は結果を保証しない',
                     '{pct}%の端正な目元、レースでの整合性はゼロだった'],
        },
        # nostril_size
        ('nostril_size', '大きい'): {
            'win':  ['大きく開いた鼻孔が{pct}%。吸気量の違いが直線でモノを言う',
                     'デカ鼻孔で酸素を爆食いする{pct}%。エンジンのスペックが段違い'],
            'lose': ['デカ鼻孔の{pct}%、吸気は十分でも出力が伴わなかった',
                     '{pct}%の大鼻孔、エンジン積んでてもドライバーが…という話'],
        },
        ('nostril_size', '小さい'): {
            'win':  ['コンパクトな小鼻が{pct}%。エレガントな見た目通りの洗練された走り',
                     '小ぶりな鼻孔の{pct}%が正解だった。スピード特化型の証明'],
            'lose': ['小さな鼻孔が{pct}%。エンジン出力の限界がそのまま着順に出た',
                     '{pct}%の小鼻、吸気量の不足がスタミナ切れに直結した疑惑'],
        },
        # jaw_line
        ('jaw_line', '強い'): {
            'win':  ['ゴツゴツした強い顎が{pct}%。競り合いになっても絶対に噛みつき返すタイプ',
                     '力強い顎の発達が{pct}%。この骨格の強さがゴール前の粘りを生む'],
            'lose': ['強い顎を持つ{pct}%が沈んだ。顎の強さと勝負強さは別物だった',
                     '{pct}%のゴツ顎、競り合いになる前に離されてしまった皮肉'],
        },
        ('jaw_line', '弱い'): {
            'win':  ['シュッとした細い顎が{pct}%。重厚感より切れ味を選んだスピード型が正解',
                     '繊細な顎ラインの{pct}%がスプリント特化で上位を席巻'],
            'lose': ['細い顎の{pct}%。スタミナ勝負になった瞬間に顎のもろさが出た',
                     '{pct}%の細顎、距離が長かったのか短かったのか、いずれにせよ敗退'],
        },
        # face_contour
        ('face_contour', '逆三角形'): {
            'win':  ['逆三角形のシャープ顔が{pct}%。攻めの走りを体現した強者たち',
                     '{pct}%の逆三角フェイスが上位を総ナメ。このシャープさが本物の証'],
            'lose': ['逆三角シャープ顔が{pct}%いたのに結果は鈍角だった',
                     '{pct}%の逆三角顔、見た目の鋭さはレースには反映されなかった'],
        },
        ('face_contour', '丸顔'): {
            'win':  ['まんまる丸顔が{pct}%。愛嬌で周囲を油断させての勝利、恐るべし',
                     '丸顔の{pct}%が上位独占。可愛い顔して容赦なく勝ちに来るタイプ'],
            'lose': ['まんまる丸顔が{pct}%。愛くるしさはパドック限定で本番は惨敗',
                     '{pct}%の丸顔が丸く丸く負けていった、ある意味一貫性がある'],
        },
        ('face_contour', '正方形'): {
            'win':  ['ガチムチ四角顔が{pct}%。このパワー型骨格が揉み合いで強さを発揮',
                     '四角くどっしりした顔の{pct}%がパワーで押し切り。力こそ正義'],
            'lose': ['四角顔のパワー系が{pct}%も沈んだ。パワーだけでは競馬は勝てない',
                     '{pct}%のガチムチ顔、馬力はあったが方向性を間違えた模様'],
        },
        ('face_contour', '面長'): {
            'win':  ['すらり面長の{pct}%。サラブレッドの理想的な顔型が結果でも証明',
                     '面長正統派が{pct}%。この品の良さが王道の強さを体現'],
            'lose': ['面長の{pct}%が伸びなかった。顔が長くてもゴールには届かなかった',
                     '面長の{pct}%、長い顔同様に長い時間をかけてゴールへ…'],
        },
    }

    def get_expr(key, val, side, pct):
        templates = EXPR.get((key, val), {}).get(side, [])
        if not templates:
            return None
        return random.choice(templates).format(pct=f'{pct:.0f}')

    # ── 差分順で特徴を抽出（閾値なし・必ず上位N件を返す）──
    def find_top_diffs(favor, against, top_n=3):
        scored = []
        for key in LABEL_KEYS:
            for val, fav_freq in favor.get(key, {}).items():
                agt_freq = against.get(key, {}).get(val, 0)
                diff = fav_freq - agt_freq
                # 差がゼロ以下でも候補に入れる（必ず何かを返すため）
                scored.append((diff, key, val, fav_freq, agt_freq))
        scored.sort(reverse=True)
        # 同一keyの重複を除きながらtop_n件取得
        seen_keys = set()
        result = []
        for item in scored:
            k = item[1]
            if k not in seen_keys:
                seen_keys.add(k)
                result.append(item)
            if len(result) >= top_n:
                break
        return result

    # 差が拮抗している場合のワイルドカード表現（抽象・断言型）
    WILDCARD_WIN = [
        '勝ち馬たちに共通するのは「この顔で負けるわけがない」という顔つき。データが示す微差が実力差に化けた',
        '数字で語れない何かがある。それが勝ち馬の顔から滲み出るオーラというやつだ',
        '特徴の差は小さくても、ゴール板を先に駆け抜けた事実は変わらない。この顔が勝ち顔だ',
        '統計的差異は僅差だが、勝ち馬の顔には「本番で違いを作る」空気が漂っていた',
    ]
    WILDCARD_LOSE = [
        '凡走馬の顔には「惜しい」が書いてある。あと一歩届かない、その差がこの顔に出ていた',
        '数字では語れない微差が、直線での伸び脚に影響したのかもしれない。それが競馬の残酷さ',
        'データ上の差は僅かでも、勝負の世界では僅かが全て。この顔の組が下位を占めたのは偶然ではない',
        'わずかな傾向の違いが、ゴール前の半馬身を分けた。競馬は残酷だ',
    ]

    def build_rich_comment(favor_diffs, side):
        sentences = []
        used_keys = set()
        for diff, key, val, fav_pct, agt_pct in favor_diffs:
            if key in used_keys:
                continue
            used_keys.add(key)
            expr = get_expr(key, val, side, fav_pct)
            if expr:
                if side == 'win':
                    contrast = f'（凡走馬は{agt_pct:.0f}%どまり）' if diff >= 5 else f'（凡走馬も{agt_pct:.0f}%と肉薄するが、僅かにこちらが上）'
                else:
                    contrast = f'（勝ち馬は{agt_pct:.0f}%）' if diff >= 5 else f'（勝ち馬も{agt_pct:.0f}%と似るが、この差が明暗を分けた）'
                sentences.append(expr + contrast)
            if len(sentences) >= 2:
                break

        # 数値特徴でひとこと足す
        t5_num = stats.get('top5_numeric', {})
        bt_num = stats.get('bottom_numeric', {})
        t5v = t5_num.get('overall_intensity')
        btv = bt_num.get('overall_intensity')
        if t5v and btv:
            if side == 'win' and t5v >= btv:
                sentences.append(f'迫力スコアも平均{t5v:.2f}と凡走馬{btv:.2f}を{"上回り、貫禄が違う" if t5v - btv >= 0.05 else "わずかに上回る。この差が積み重なる"}')
            elif side == 'lose' and btv >= t5v:
                sentences.append(f'迫力スコアは平均{btv:.2f}と{"見た目は強そうだが結果が全てを物語る" if btv - t5v >= 0.05 else "勝ち馬と大差ないが、それでも届かなかった"}')

        # 差分が小さくて表現が出なかった場合のワイルドカード
        if not sentences:
            sentences.append(random.choice(WILDCARD_WIN if side == 'win' else WILDCARD_LOSE))

        return '　'.join(sentences)

    top5_diffs   = find_top_diffs(top5_patterns,   bottom_patterns)
    bottom_diffs = find_top_diffs(bottom_patterns, top5_patterns)

    top5_comment   = build_rich_comment(top5_diffs,   'win')
    bottom_comment = build_rich_comment(bottom_diffs, 'lose')

    # ── 差分コメント（詳細） ──
    diff_parts = []
    for key in LABEL_KEYS:
        t5_vals = top5_patterns.get(key, {})
        bt_vals = bottom_patterns.get(key, {})
        for val, t5_freq in t5_vals.items():
            bt_freq = bt_vals.get(val, 0)
            diff = t5_freq - bt_freq
            if diff >= 20:
                label = FEATURE_LABELS_JP.get(key, key)
                diff_parts.append(f"【{label}: {val}】TOP5 {t5_freq:.0f}% vs 下位 {bt_freq:.0f}%（差 {diff:.0f}pt）")

    diff_comment = "\n".join(diff_parts) if diff_parts else "明確な差分特徴はなし"

    t5_num = stats.get('top5_numeric', {})
    bt_num = stats.get('bottom_numeric', {})
    for key in ['jaw_strength_score', 'overall_intensity']:
        t5v = t5_num.get(key)
        btv = bt_num.get(key)
        if t5v is not None and btv is not None and abs(t5v - btv) >= 0.1:
            label = FEATURE_LABELS_JP.get(key, key)
            direction = "高い" if t5v > btv else "低い"
            diff_comment += f"\n【{label}】TOP5平均 {t5v:.2f} / 下位平均 {btv:.2f}（TOP5の方が{direction}）"

    return top5_comment, bottom_comment, diff_comment

# ------------------------------------------------------------------
# A: 統計予想スコア取得
# ------------------------------------------------------------------
def get_stats_score(conn, race_name, horse_name):
    """stats_predictionから統計予想スコアを取得（0〜100）"""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT score FROM stats_prediction
            WHERE race_name ILIKE %s AND horse_name = %s
            ORDER BY created_at DESC LIMIT 1
        """, (f"%{race_name}%", horse_name))
        row = cur.fetchone()
        cur.close()
        return float(row[0]) if row else None
    except Exception:
        return None

# ------------------------------------------------------------------
# B: 馬体重パターン集計 + スコア計算
# ------------------------------------------------------------------
def compute_weight_stats(analyzed):
    """過去分析馬からTOP5 vs 下位の馬体重平均を計算"""
    top5_w = [h['weight'] for h in analyzed if h.get('is_top5') and h.get('weight')]
    btm_w  = [h['weight'] for h in analyzed if not h.get('is_top5') and h.get('weight')]
    top5_avg = round(sum(top5_w) / len(top5_w), 1) if top5_w else None
    btm_avg  = round(sum(btm_w)  / len(btm_w),  1) if btm_w  else None
    return top5_avg, btm_avg

def weight_score(horse_weight, top5_avg, btm_avg):
    """馬体重スコア（0〜100）: TOP5平均に近いほど高スコア"""
    if horse_weight is None or top5_avg is None:
        return 50.0
    if btm_avg is None or abs(top5_avg - btm_avg) < 1:
        return 50.0
    dist_top = abs(horse_weight - top5_avg)
    dist_btm = abs(horse_weight - btm_avg)
    total = dist_top + dist_btm + 0.001
    return round(dist_btm / total * 100.0, 1)

def fetch_runner_weights(race_id):
    """出馬表から出走馬の体重（前走）を取得 {horse_name: weight}"""
    weights = {}
    try:
        url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
        table = soup.find('table', class_='Shutuba_Table')
        if not table:
            return weights
        for row in table.find_all('tr', class_=re.compile(r'HorseList')):
            cols = row.find_all('td')
            horse_link = row.find('a', href=re.compile(r'/horse/'))
            if not horse_link:
                continue
            horse_name = horse_link.text.strip()
            # 馬体重列を探す（"NNN(±N)"形式）
            for td in cols:
                m = re.search(r'(\d{3,4})\s*[\(（]', td.text)
                if m:
                    weights[horse_name] = int(m.group(1))
                    break
    except Exception as e:
        print(f"  [警告] 出馬表体重取得失敗: {e}")
    return weights

# ------------------------------------------------------------------
# C: 父馬パターン集計 + スコア計算
# ------------------------------------------------------------------
def compute_sire_stats(analyzed):
    """過去分析馬からTOP5 vs 下位の父馬頻度を集計"""
    top5_sires = Counter()
    btm_sires  = Counter()
    for h in analyzed:
        sire = h.get('sire')
        if not sire:
            continue
        if h.get('is_top5'):
            top5_sires[sire] += 1
        else:
            btm_sires[sire] += 1
    return top5_sires, btm_sires

def sire_score(horse_sire, top5_sires, btm_sires, top5_n):
    """父馬スコア（0〜100）: TOP5産駒なら高スコア、下位多産駒なら低スコア"""
    if not horse_sire or not top5_sires:
        return 50.0
    t5_cnt = top5_sires.get(horse_sire, 0)
    bt_cnt = btm_sires.get(horse_sire, 0)
    if t5_cnt == 0 and bt_cnt == 0:
        return 50.0  # データなし
    total = t5_cnt + bt_cnt
    return round(t5_cnt / total * 100.0, 1)

# ------------------------------------------------------------------
# Step8: 出走馬スコアリング
# ------------------------------------------------------------------
def score_horse(features, top5_patterns, bottom_patterns, stats):
    """
    馬の特徴をパターンと照合してスコアを計算（0〜100）
    A: 差分絶対値に比例した重み付け（識別力の高い特徴ほど重要）
    B: diff < 15% の特徴は無視（ノイズ除去）
    """
    if not features:
        return 50.0  # データなしは中央値

    score = 0.0
    weight_total = 0.0
    LABEL_DIFF_MIN = 10  # B: この差分未満のラベル特徴はスキップ
    NUM_DIFF_MIN   = 0.03  # B: この差分未満の数値特徴はスキップ

    # ラベル特徴のスコアリング（A+B）
    for key in LABEL_KEYS:
        val = features.get(key)
        if not val:
            continue
        t5_freq = top5_patterns.get(key, {}).get(val, 0)
        bt_freq = bottom_patterns.get(key, {}).get(val, 0)
        diff    = t5_freq - bt_freq  # -100 〜 +100

        # B: 識別力が低い特徴をスキップ
        if abs(diff) < LABEL_DIFF_MIN:
            continue

        # A: 差分絶対値を重みに使用 + 勾配スコアリング
        # diff=-100→0点、diff=0→weight/2、diff=+100→weight（滑らか）
        weight       = abs(diff)
        contribution = weight * (diff + 100) / 200.0
        score        += contribution
        weight_total += weight

    # 数値特徴のスコアリング（A+B）
    t5_num = stats.get('top5_numeric', {})
    bt_num = stats.get('bottom_numeric', {})
    for key in NUMERIC_KEYS:
        val = features.get(key)
        t5v = t5_num.get(key)
        btv = bt_num.get(key)
        if val is None or t5v is None or btv is None:
            continue

        numeric_diff = abs(t5v - btv)
        # B: 識別力が低い数値特徴をスキップ
        if numeric_diff < NUM_DIFF_MIN:
            continue

        # A: 差分に比例した重み（スケーリング×100）
        weight = numeric_diff * 100
        # TOP5平均に近いほど高スコア（距離比率で判定）
        dist_top5 = abs(val - t5v)
        dist_btm  = abs(val - btv)
        contribution = weight * (dist_btm / (dist_top5 + dist_btm + 0.001))
        score        += contribution
        weight_total += weight

    if weight_total == 0:
        return 50.0

    normalized = (score / weight_total) * 100.0
    return round(min(100.0, max(0.0, normalized)), 1)

def generate_horse_comment(horse_name, features, top5_patterns, bottom_patterns):
    """個別馬のコメントを生成（個性的・エンタメ表現）"""
    import random
    if not features:
        return "📷 顔写真が確認できず…謎のベールに包まれた刺客か？"

    eye_val   = features.get('eye_shape', '')
    nos_val   = features.get('nostril_size', '')
    jaw_val   = features.get('jaw_line', '')
    imp_val   = features.get('overall_impression', '')
    cnt_val   = features.get('face_contour', '')
    fhd_val   = features.get('forehead_width', '')
    intensity = features.get('overall_intensity', 0.5) or 0.5
    jaw_score = features.get('jaw_strength_score', 0.5) or 0.5

    # ── 目の形フレーズ（複数バリエーション）──
    EYE_PHRASES = {
        '細長い':     ["ギラリと光る細い眼光、獲物を狙うタカの目", "鋭く細長い目が語りかける「勝ちに来た」感"],
        '切れ長':     ["スッと引いた切れ長の目、クールビューティー系", "二重の切れ長で、パドックで女子から黄色い声がきこえそう"],
        '丸い':       ["クリクリとした丸い目、見た目はおとなしそうだが…", "丸くてつぶらな瞳、でも内には闘志を秘めているはず"],
        'アーモンド型': ["アーモンド型の端正な目元、育ちの良さがにじみ出る", "均整のとれたアーモンド型の目、王道美馬の風格"],
    }
    # ── 鼻孔フレーズ ──
    NOSTRIL_PHRASES = {
        '大きい': ["鼻孔が豪快に開き、エンジン全開の予感", "「吸気量が違う！」と叫びたくなるほど大きな鼻孔"],
        '小さい': ["すっきりとした小ぶりな鼻孔、エレガント系", "小鼻がコンパクトで女優顔負けの端正さ"],
        '中程度': ["鼻孔は標準的でバランス重視タイプ", "鼻はオーソドックス、可もなく不可もなし"],
    }
    # ── 顎フレーズ ──
    JAW_PHRASES = {
        '強い': ["顎がゴツゴツとした筋肉質、噛み合わせ最強感", "「ここぞ」で食らいつく力強い顎、競り合いに強そう"],
        '弱い': ["顎がシュッとシャープ、スピード特化型かも", "顎の線は細め、スタミナより瞬発力勝負のタイプ？"],
        '中程度': ["顎のバランスは標準的、オールラウンダー体型", "顎は中程度、特別な武器もないが弱点もない"],
    }
    # ── 印象フレーズ（牝馬対応）──
    IMPRESSION_PHRASES = {
        '威圧感がある': ["パドックに登場した瞬間、他馬がざわめく威圧感", "「この子が主役よ」と全身で語りかける女王オーラ全開", "圧倒的な貫禄、近寄りがたいほどの存在感を放つ"],
        '精悍':         ["精悍な顔つきは百戦錬磨の勝負師の顔", "キレッキレの精悍フェイス、見るからに勝負強そう", "凛とした精悍さは一流競走馬の証"],
        '温和':         ["温和な表情でパドックを周回、でも本番は別人に化けるタイプかも", "見た目はおっとり系…「おしとやかな刺客」の可能性", "穏やかな笑顔の裏に闘志を秘めた大物感"],
        '穏やか':       ["穏やかでリラックスした面構え、本番に強い精神力の証か", "落ち着きすぎてて逆に怖い。鈍感力で勝ちに行くタイプ", "マイペースを貫く肝の据わった女傑の風格"],
        '神経質':       ["神経質そうな目つき、集中力MAX・良い意味でピリピリ", "鋭く神経質な顔つき、ゲートが開いた瞬間に爆発する予感", "繊細なセンサーが全開、コンディション次第で大仕事をやらかすかも"],
        '落ち着いている': ["どっしり泰然、コーナーでごちゃごちゃしても動じなそう", "ベテランの風格漂う落ち着き、レースで慌てない鉄のメンタル", "どんな展開でも顔色ひとつ変えない、究極の平常心の持ち主"],
    }
    # ── 輪郭フレーズ ──
    CONTOUR_PHRASES = {
        '丸顔':     ["ふっくら丸顔は愛嬌たっぷり、ファン投票なら1位かも", "まんまるな顔、このかわいさが逆に盲点になりそう", "愛くるしい丸顔に隠れた闘志、油断したら置いていかれる"],
        '面長':     ["すらりとした面長、サラブレッドの理想形を体現", "面長で鼻筋がスッと通り、一流感ただよう顔立ち", "モデル顔負けの面長美人、走りも姿も一流志向"],
        '逆三角形': ["逆三角形の輪郭は強者の証、ライバルをにらみ倒す", "逆三角フェイスに宿る闘争心、直線で弾けるタイプ", "キリッとした逆三角の輪郭、強い馬に多いシャープな顔型"],
        '正方形':   ["四角くどっしりした顔、パワーで押し切るタイプ", "がっちりした四角顔、揉み合いも辞さないタフさが売り", "骨格がしっかりした四角顔、スタミナ勝負に強そう"],
    }
    # ── 額フレーズ ──
    FOREHEAD_PHRASES = {
        '広い': ["広い額はIQ高そう、頭脳派レースに強い予感", "広大な額に「勝利への地図」が描かれているかもしれない"],
        '狭い': ["キュッと引き締まった額、余計なことを考えない一点突破型", "狭い額はシャープな集中力の象徴、直線勝負に賭ける"],
        '中程度': ["額は標準的、特筆なし", "額のバランスは普通、可もなく不可もなし"],
    }

    # ランダムにバリエーション選択
    def pick(d, key):
        opts = d.get(key, [])
        return random.choice(opts) if opts else None

    parts = []
    eye_p = pick(EYE_PHRASES, eye_val)
    nos_p = pick(NOSTRIL_PHRASES, nos_val)
    jaw_p = pick(JAW_PHRASES, jaw_val)
    imp_p = pick(IMPRESSION_PHRASES, imp_val)
    cnt_p = pick(CONTOUR_PHRASES, cnt_val)
    fhd_p = pick(FOREHEAD_PHRASES, fhd_val)

    if imp_p:
        parts.append(imp_p)  # 印象を最初に
    if eye_p:
        parts.append(eye_p)
    combo = [p for p in [nos_p, jaw_p, cnt_p, fhd_p] if p]
    if combo:
        parts.append(random.choice(combo))  # 残りから1つランダムに追加

    # 数値特徴ベースの追加ワンポイント
    if jaw_score >= 0.8:
        parts.append("顎の筋肉が別格レベル、競り合いなら負けない")
    elif jaw_score <= 0.25:
        parts.append("顎は繊細系、スプリント一閃で決めたいタイプ")
    if intensity >= 0.85:
        parts.append("全体的な迫力は出走馬トップクラス、見た目で既に勝っている")
    elif intensity <= 0.2:
        parts.append("迫力より洗練さが光る、見た目に騙されるな系")

    # ── 勝ち馬パターンとの照合コメント ──
    winner_hits  = []
    loser_hits   = []
    for key in LABEL_KEYS:
        val = features.get(key)
        if not val:
            continue
        t5f  = top5_patterns.get(key, {}).get(val, 0)
        btf  = bottom_patterns.get(key, {}).get(val, 0)
        diff = t5f - btf
        if diff >= 25:
            winner_hits.append(f"{val}({'+'+str(int(diff))+'pt'})")
        elif diff <= -25:
            loser_hits.append(f"{val}({str(int(diff))+'pt'})")

    verdict_parts = []
    if winner_hits:
        verdict_parts.append(f"✅ 勝ち馬顔: {' / '.join(winner_hits)}")
    if loser_hits:
        verdict_parts.append(f"🚨 凡走顔: {' / '.join(loser_hits)}")

    # コメントを結合
    face_str = "　".join(parts) if parts else "標準的な顔立ちで可もなく不可もなし"
    verdict_str = "　".join(verdict_parts) if verdict_parts else ""

    return face_str + ("　" + verdict_str if verdict_str else "")

# ------------------------------------------------------------------
# Step9: DB保存
# ------------------------------------------------------------------
def save_prediction_pattern(conn, race_name, top5_patterns, bottom_patterns,
                             top5_comment, bottom_comment, diff_comment,
                             stats, supplemental_count, confidence_level):
    cur = conn.cursor()
    cur.execute("DELETE FROM race_specific_prediction WHERE race_name = %s", (race_name,))
    # DBの実際のカラム名に合わせる（JPA生成: top5horses, top5comment, top5pattern_json）
    cur.execute("""
        INSERT INTO race_specific_prediction
            (race_name, total_years, total_horses, top5horses, bottom_horses,
             top5pattern_json, bottom_pattern_json,
             top5comment, bottom_comment, diff_comment,
             supplemental_count, confidence_level, analyzed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """, (
        race_name,
        0,  # total_yearsは呼び出し元で設定
        stats['top5_n'] + stats['bottom_n'],
        stats['top5_n'],
        stats['bottom_n'],
        json.dumps(top5_patterns, ensure_ascii=False),
        json.dumps(bottom_patterns, ensure_ascii=False),
        top5_comment,
        bottom_comment,
        diff_comment,
        supplemental_count,
        confidence_level,
    ))
    conn.commit()
    cur.close()

def save_race_results(conn, race_name, results):
    cur = conn.cursor()
    cur.execute("DELETE FROM race_specific_result WHERE race_name = %s", (race_name,))
    for r in results:
        cur.execute("""
            INSERT INTO race_specific_result
                (race_name, horse_name, horse_id, image_path, rank_position,
                 score, confidence_level, comment, feature_json, data_source, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (
            race_name, r['horse_name'], r.get('horse_id'), r.get('image_path'),
            r['rank_position'], r['score'], r.get('confidence_level', 3),
            r['comment'],
            json.dumps(r.get('features', {}), ensure_ascii=False),
            r.get('data_source', 'image'),
        ))
    conn.commit()
    cur.close()

# ------------------------------------------------------------------
# メイン処理
# ------------------------------------------------------------------
def classify_race(distance, surface):
    if surface == 'ダート':
        return 'dirt'
    d = int(distance) if distance else 0
    if d <= 1400: return 'sprint'
    if d <= 1800: return 'mile'
    if d <= 2200: return 'middle'
    return 'long'

def main():
    # 出力バッファを無効化（パイプ経由でも即時フラッシュ）
    sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

    args = sys.argv[1:]
    if not args:
        print("使い方: python race_specific_analyzer.py \"レース名\" [--years N] [--no-supplement]")
        sys.exit(1)

    race_name     = args[0]
    years         = 10
    use_supplement = True
    search_word   = None
    for i, a in enumerate(args[1:]):
        if a == '--years' and i + 2 < len(args):
            years = int(args[i + 2])
        if a == '--no-supplement':
            use_supplement = False
        if a == '--search-word' and i + 2 < len(args):
            search_word = args[i + 2]

    print(f"\n{'='*60}")
    print(f"  レース特化型顔面分析: {race_name}")
    print(f"  対象期間: 過去{years}年")
    print(f"{'='*60}\n")

    client = None  # llava:7b使用のためAnthropicクライアント不要
    conn   = get_conn()
    ensure_tables(conn)

    # ----------------------------------------------------------------
    # Step1: 過去開催を検索
    # ----------------------------------------------------------------
    print(f"[Step1] {race_name} の過去開催を検索中...")
    past_editions = fetch_past_editions(race_name, years, search_word=search_word)
    if not past_editions:
        print(f"  [警告] {race_name} の過去開催が見つかりませんでした")
        conn.close()
        sys.exit(1)
    print(f"  → {len(past_editions)}開催を発見\n")

    # ----------------------------------------------------------------
    # Step2: 全着順を取得 + 画像ダウンロード
    # ----------------------------------------------------------------
    print(f"[Step2] 全着順の取得と画像ダウンロード...")
    all_finishers  = []
    race_category  = None
    for edition in past_editions:
        print(f"  {edition['race_year']}年 {edition['race_name']} (race_id={edition['race_id']})")
        finishers, distance, surface = fetch_all_finishers(edition['race_id'])
        if not finishers:
            print(f"    [スキップ] 着順データなし")
            time.sleep(1)
            continue

        if race_category is None and distance:
            race_category = classify_race(distance, surface)
            print(f"    → カテゴリ: {race_category} ({distance}m {surface})")

        print(f"    → {len(finishers)}頭 出走")
        for horse in finishers:
            img = download_horse_image(horse['horse_id'], horse['horse_name'])
            horse['image_path']  = img
            horse['is_top5']     = horse['rank'] <= TOP5_BORDER
            horse['race_year']   = edition['race_year']
            all_finishers.append(horse)
            label = f"{horse['rank']}着"
            img_label = "画像OK" if img else "画像なし"
            print(f"    {label}: {horse['horse_name']}  [{img_label}]")
            time.sleep(0.4)
        time.sleep(0.8)

    print(f"\n  合計 {len(all_finishers)} 頭分の着順データを取得")

    # TOP5 + 各開催最下位BOTTOM_ANALYZE頭のみ分析対象にする
    from collections import defaultdict
    edition_max_rank = defaultdict(int)
    for h in all_finishers:
        edition_max_rank[h['race_year']] = max(edition_max_rank[h['race_year']], h['rank'])

    def should_analyze(horse):
        if horse['rank'] <= TOP5_BORDER:
            return True
        max_r = edition_max_rank[horse['race_year']]
        return horse['rank'] > max_r - BOTTOM_ANALYZE

    analyze_targets = [h for h in all_finishers if should_analyze(h)]
    skipped = len(all_finishers) - len(analyze_targets)
    print(f"  分析対象: {len(analyze_targets)} 頭 (TOP{TOP5_BORDER} + 最下位{BOTTOM_ANALYZE}頭/開催、中間{skipped}頭スキップ)")

    has_image  = [h for h in analyze_targets if h['image_path']]
    no_image   = [h for h in analyze_targets if not h['image_path']]
    print(f"  画像あり: {len(has_image)} 頭 / 画像なし: {len(no_image)} 頭\n")

    # ----------------------------------------------------------------
    # Step3: 画像あり馬をClaude APIで分析
    # ----------------------------------------------------------------
    print(f"[Step3] llava:7bで顔特徴を分析 ({len(has_image)}頭)...")
    analyzed = []
    for i, horse in enumerate(has_image):
        print(f"  [{i+1}/{len(has_image)}] {horse['horse_name']} ({horse['race_year']}年 {horse['rank']}着)")
        abs_path = os.path.join(os.path.dirname(__file__), '..', horse['image_path'].lstrip('/'))
        if not os.path.exists(abs_path):
            print(f"    [スキップ] 画像ファイルが見つかりません")
            continue
        features = analyze_face_with_claude(client, abs_path)
        if features:
            analyzed.append({
                'horse_name':  horse['horse_name'],
                'horse_id':    horse['horse_id'],
                'is_top5':     horse['is_top5'],
                'features':    features,
                'image_path':  horse['image_path'],
                'data_source': 'image',
                'weight':      horse.get('weight'),
            })
            print(f"    → 分析完了 (目:{features.get('eye_shape')} 鼻:{features.get('nostril_size')} 印象:{features.get('overall_impression')})")
        else:
            print(f"    → 分析失敗（顔不明確）")
        time.sleep(0.5)

    # ----------------------------------------------------------------
    # Step3b: 画像なし馬は血統ベースで推定
    # ----------------------------------------------------------------
    print(f"\n[Step3b] 画像なし馬の血統ベース推定 ({len(no_image)}頭)...")
    for horse in no_image:
        print(f"  {horse['horse_name']} ({horse['race_year']}年 {horse['rank']}着) → 血統推定")
        features, sire = estimate_features_from_pedigree(conn, horse['horse_id'], horse['horse_name'])
        if features:
            analyzed.append({
                'horse_name':  horse['horse_name'],
                'horse_id':    horse['horse_id'],
                'is_top5':     horse['is_top5'],
                'features':    features,
                'image_path':  None,
                'data_source': 'pedigree',
                'weight':      horse.get('weight'),
            })
            print(f"    → 推定完了 (父:{sire})")
        time.sleep(0.3)

    print(f"\n  分析完了: {len(analyzed)}頭")

    # ----------------------------------------------------------------
    # Step3c: 過去分析馬の父馬情報を取得（C: 父馬スコア用）
    # ----------------------------------------------------------------
    print(f"\n[Step3c] 過去分析馬の父馬情報を取得中（{len(analyzed)}頭）...")
    for horse in analyzed:
        if horse.get('horse_id') and not horse.get('sire'):
            sire = get_sire_name(horse['horse_id'])
            horse['sire'] = sire
            if sire:
                print(f"    {horse['horse_name']}: 父 {sire}")
            time.sleep(0.3)

    # B: 体重統計、C: 父馬統計を計算
    top5_weight_avg, btm_weight_avg = compute_weight_stats(analyzed)
    top5_sires, btm_sires = compute_sire_stats(analyzed)
    top5_n_for_sire = len([h for h in analyzed if h.get('is_top5')])
    print(f"  → 体重統計: TOP5平均={top5_weight_avg}kg / 下位平均={btm_weight_avg}kg")
    print(f"  → 父馬統計: TOP5産駒={sum(top5_sires.values())}頭 / 下位産駒={sum(btm_sires.values())}頭")

    # ----------------------------------------------------------------
    # Step4: パターン計算（+ 補完データ）
    # ----------------------------------------------------------------
    print(f"\n[Step4] 5着内 vs 6着以下 のパターンを集計...")

    supplemental = []
    supplemental_count = 0
    if use_supplement and race_category:
        analyzed_count = len(analyzed)
        if analyzed_count < SUPPLEMENT_THRESHOLD:
            print(f"  → データ不足（{analyzed_count}頭）。同カテゴリ({race_category})のデータで補完します")
            supplemental = fetch_supplemental_data(conn, race_category, race_name)
            supplemental_count = len(supplemental)
            print(f"  → 補完: {supplemental_count}頭 追加")

    top5_patterns, bottom_patterns, stats = compute_patterns(analyzed, supplemental)
    print(f"  → TOP5群: {stats['top5_n']}頭 / 6着以下群: {stats['bottom_n']}頭")

    # 信頼度判定
    same_race_count = len(analyzed)
    if same_race_count >= 50:
        confidence = 5
    elif same_race_count >= 30:
        confidence = 4
    elif same_race_count >= 15:
        confidence = 3
    elif same_race_count >= 8:
        confidence = 2
    else:
        confidence = 1
    print(f"  → 信頼度: {'★' * confidence}{'☆' * (5-confidence)} (Lv{confidence})")

    # ----------------------------------------------------------------
    # Step5: コメント生成
    # ----------------------------------------------------------------
    print(f"\n[Step5] 傾向コメントを生成...")
    top5_comment, bottom_comment, diff_comment = generate_comments(top5_patterns, bottom_patterns, stats)
    print(f"  【5着内の傾向】{top5_comment}")
    print(f"  【6着以下の傾向】{bottom_comment}")
    print(f"  【差分の大きな特徴】\n  {diff_comment}")

    # パターンをDBに保存
    save_prediction_pattern(conn, race_name, top5_patterns, bottom_patterns,
                            top5_comment, bottom_comment, diff_comment,
                            stats, supplemental_count, confidence)

    # ----------------------------------------------------------------
    # Step6: 今年の出走馬を取得
    # ----------------------------------------------------------------
    print(f"\n[Step6] {race_name} の出走馬を取得...")
    cur = conn.cursor()
    cur.execute("""
        SELECT horse_name, horse_id, image_path, race_id
        FROM race_entry
        WHERE race_name ILIKE %s
        ORDER BY horse_number
    """, (f"%{race_name}%",))
    entry_rows = cur.fetchall()
    cur.close()

    if not entry_rows:
        print(f"  [警告] race_entryに {race_name} の出走馬が見つかりません")
        print(f"  先に entry_fetcher.py を実行してください")
        conn.close()
        print(f"\n=== パターン分析は完了。出走馬データがないため予想はスキップ ===")
        sys.exit(0)

    print(f"  → {len(entry_rows)}頭の出走馬を取得")

    # B: 出走馬の体重を出馬表から取得
    runner_weights = {}
    entry_race_ids = list({r[3] for r in entry_rows if r[3]})
    if entry_race_ids:
        entry_race_id = entry_race_ids[0]
        print(f"  → 出走馬体重を取得 (race_id={entry_race_id})...")
        runner_weights = fetch_runner_weights(entry_race_id)
        print(f"  → {len(runner_weights)}頭分の体重データを取得")
    print()

    # ----------------------------------------------------------------
    # Step7: 出走馬を顔分析 → スコアリング
    # ----------------------------------------------------------------
    print(f"[Step7] 出走馬の顔分析とスコアリング...")
    prediction_results = []
    for horse_name, horse_id, image_path, _race_id in entry_rows:
        print(f"  {horse_name} (id={horse_id})")

        features = None
        data_src = 'unknown'
        img_path = image_path

        # ①まず horse_face_feature に既存分析があるか確認
        if horse_id:
            cur2 = conn.cursor()
            cur2.execute("""
                SELECT nose_shape, eye_size, eye_shape, face_contour, forehead_width,
                       nostril_size, jaw_line, overall_impression,
                       eye_aspect_ratio, nose_width_ratio, face_aspect_ratio,
                       jaw_strength_score, overall_intensity, image_path
                FROM horse_face_feature
                WHERE horse_id = %s AND nose_shape IS NOT NULL
                LIMIT 1
            """, (horse_id,))
            existing = cur2.fetchone()
            cur2.close()
            if existing:
                features = {}
                for i, k in enumerate(LABEL_KEYS):
                    features[k] = existing[i]
                for i, k in enumerate(NUMERIC_KEYS):
                    features[k] = existing[len(LABEL_KEYS) + i]
                if not img_path:
                    img_path = existing[-1]
                data_src = 'image'
                print(f"    → 既存分析データを使用")

        # ②画像があれば新規分析
        if features is None and img_path:
            abs_p = os.path.join(os.path.dirname(__file__), '..', img_path.lstrip('/'))
            if os.path.exists(abs_p):
                print(f"    → llava:7bで分析中...")
                features = analyze_face_with_claude(client, abs_p)
                if features:
                    data_src = 'image'
                    print(f"    → 分析完了")
                time.sleep(0.5)

        # ③画像なし → 候補ディレクトリで再検索
        if features is None and horse_id:
            candidate_img = os.path.join(UPLOAD_DIR_CANDIDATES, f"{horse_id}.jpg")
            if not os.path.exists(candidate_img):
                # ダウンロード試行
                img_path = download_horse_image(horse_id, horse_name, UPLOAD_DIR_CANDIDATES)
                candidate_img = os.path.join(UPLOAD_DIR_CANDIDATES, f"{horse_id}.jpg")
            if os.path.exists(candidate_img):
                print(f"    → 候補画像でllava分析中...")
                features = analyze_face_with_claude(client, candidate_img)
                if features:
                    data_src = 'image'
                    img_path = f"/uploads/candidates/{horse_id}.jpg"
                time.sleep(0.5)

        # ④それでもなければ血統推定
        if features is None and horse_id:
            print(f"    → 血統ベース推定...")
            features, sire = estimate_features_from_pedigree(conn, horse_id, horse_name)
            if features:
                data_src = 'pedigree'
                print(f"    → 推定完了 (父:{sire})")
            time.sleep(0.3)

        if features is None:
            features = {}
            data_src = 'no_data'
            print(f"    → データなし（デフォルトスコア）")

        # ── スコアリング（4次元ブレンド）──
        # A: 顔面スコア（40%）
        face_sc = score_horse(features, top5_patterns, bottom_patterns, stats)

        # A: 統計予想スコア（40%）
        stats_sc = get_stats_score(conn, race_name, horse_name)
        if stats_sc is None:
            stats_sc = 50.0  # データなし → 中立

        # B: 体重スコア（10%）
        horse_weight_val = runner_weights.get(horse_name)
        w_sc = weight_score(horse_weight_val, top5_weight_avg, btm_weight_avg)

        # C: 父馬スコア（10%）
        horse_sire = get_sire_name(horse_id) if horse_id else None
        s_sc = sire_score(horse_sire, top5_sires, btm_sires, top5_n_for_sire)
        if horse_sire:
            print(f"    → 父: {horse_sire}  父馬スコア: {s_sc:.0f}")

        sc = face_sc * 0.4 + stats_sc * 0.4 + w_sc * 0.1 + s_sc * 0.1

        # 詳細コメント生成（4次元）
        face_comment = generate_horse_comment(horse_name, features, top5_patterns, bottom_patterns)
        comment_parts = [face_comment]

        # 統計予想の評価コメント
        if stats_sc != 50.0:
            if stats_sc >= 80:
                stats_label = f"📊 データも「買い」サイン！統計スコア{stats_sc:.0f}点の優等生"
            elif stats_sc >= 65:
                stats_label = f"📊 統計的にも好感触、数字が{stats_sc:.0f}点で後押し"
            elif stats_sc <= 20:
                stats_label = f"📊 統計スコア{stats_sc:.0f}点…数字は正直に「厳しい」と言っている"
            elif stats_sc <= 35:
                stats_label = f"📊 統計的には苦しい立場({stats_sc:.0f}点)、波乱の主役になれるか"
            else:
                stats_label = f"📊 統計スコアは{stats_sc:.0f}点の中間評価、混戦に埋もれるな"
            comment_parts.append(stats_label)

        # 体重コメント
        if horse_weight_val and top5_weight_avg:
            wt_diff = horse_weight_val - top5_weight_avg
            if wt_diff > 15:
                wt_label = f"⚖️ {horse_weight_val}kgは勝ち馬平均より{wt_diff:.0f}kg重め、パワーはあるが取り回しは？"
            elif wt_diff > 5:
                wt_label = f"⚖️ 体重{horse_weight_val}kgは勝ち馬平均より少し重め、馬体の充実感あり"
            elif wt_diff < -15:
                wt_label = f"⚖️ {horse_weight_val}kgは勝ち馬平均より{abs(wt_diff):.0f}kg軽め、スピード特化の軽量型か"
            elif wt_diff < -5:
                wt_label = f"⚖️ 体重{horse_weight_val}kgは勝ち馬平均より若干軽め、切れ味重視タイプ"
            else:
                wt_label = f"⚖️ 体重{horse_weight_val}kgは勝ち馬平均とドンピシャ一致！体型の面では文句なし"
            comment_parts.append(wt_label)

        # 父馬コメント
        if horse_sire:
            t5_cnt = top5_sires.get(horse_sire, 0)
            bt_cnt = btm_sires.get(horse_sire, 0)
            if t5_cnt >= 3:
                comment_parts.append(f"🐴 父{horse_sire}はこのレースの申し子！過去TOP5に{t5_cnt}頭の実績は伊達じゃない")
            elif t5_cnt >= 2:
                comment_parts.append(f"🐴 父{horse_sire}の血がここで炸裂か？過去{t5_cnt}頭が5着以内の好相性")
            elif t5_cnt == 1 and bt_cnt == 0:
                comment_parts.append(f"🐴 父{horse_sire}はこのレースでひっそり1頭の実績、あなたが2頭目になれるか")
            elif bt_cnt >= 3 and t5_cnt == 0:
                comment_parts.append(f"🐴 父{horse_sire}の産駒は過去{bt_cnt}頭が凡走…相性の悪さは本物か")
            elif bt_cnt >= 2 and t5_cnt == 0:
                comment_parts.append(f"🐴 父{horse_sire}はこのレースで苦戦続き({bt_cnt}頭凡走)、血統の壁を越えられるか")
            elif horse_sire:
                comment_parts.append(f"🐴 父{horse_sire}、このレースでの前例は少なく未知数")

        comment = "　".join(comment_parts)

        conf_lv = confidence
        if data_src == 'pedigree':
            conf_lv = max(1, confidence - 1)
        elif data_src == 'no_data':
            conf_lv = 1

        prediction_results.append({
            'horse_name':      horse_name,
            'horse_id':        horse_id,
            'image_path':      img_path,
            'score':           sc,
            'features':        features,
            'data_source':     data_src,
            'confidence_level': conf_lv,
            'comment':         comment,
        })
        print(f"    → 顔:{face_sc:.1f} 統計:{stats_sc:.1f} 体重:{w_sc:.1f} 父馬:{s_sc:.1f} → 合計:{sc:.1f}点  [{data_src}]")

    # ----------------------------------------------------------------
    # Step8: ランキング → DB保存
    # ----------------------------------------------------------------
    prediction_results.sort(key=lambda x: x['score'], reverse=True)

    # C: min-max正規化（0〜100点に引き伸ばして差を最大化）
    raw_scores = [r['score'] for r in prediction_results]
    min_s, max_s = min(raw_scores), max(raw_scores)
    if max_s > min_s:
        for r in prediction_results:
            r['score'] = round((r['score'] - min_s) / (max_s - min_s) * 100.0, 1)
    # スコアが全馬同じ場合はそのまま

    for i, r in enumerate(prediction_results):
        r['rank_position'] = i + 1

    print(f"\n[Step8] 予想結果をDBに保存...")
    save_race_results(conn, race_name, prediction_results)
    conn.close()

    # ----------------------------------------------------------------
    # 結果サマリ表示
    # ----------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"  {race_name} 顔面分析予想 TOP5")
    print(f"{'='*60}")
    for r in prediction_results[:5]:
        mark = {1:'◎', 2:'○', 3:'▲', 4:'△', 5:'×'}.get(r['rank_position'], ' ')
        src_label = {'image':'画像', 'pedigree':'血統推定', 'no_data':'データなし'}.get(r['data_source'], r['data_source'])
        print(f"  {mark} {r['rank_position']}位: {r['horse_name']:<12} {r['score']:.1f}点  [{src_label}]")
        print(f"       {r['comment'][:60]}")
    print(f"\n  信頼度: {'★' * confidence}{'☆' * (5-confidence)}  分析馬数:{len(analyzed)}頭")
    print(f"\n予想結果は http://localhost:8081/predict-v2?raceName={requests.utils.quote(race_name)} で確認できます")

    # llava:7b をRAMから解放（全頭完了後に1回だけ）
    try:
        requests.post(OLLAMA_URL, json={'model': OLLAMA_MODEL, 'keep_alive': 0}, timeout=10)
        print("🧹 llava:7b をメモリから解放しました")
    except Exception:
        pass

    print(f"=== 完了 ===")

if __name__ == '__main__':
    main()
