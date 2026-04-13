"""
face_analyzer_local.py  ― ローカルllava:7bで馬の顔面分析（APIクレジット不要）

Ollama + llava:7b モデルを使って競走馬の写真を解析し、
コンディションスコアと日本語コメントをDBに保存する。

使い方:
  python face_analyzer_local.py 大阪杯
"""

import sys, os, re, json, time, base64, requests, random
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

OLLAMA_URL  = 'http://localhost:11434/api/generate'
OLLAMA_MODEL = 'llava:7b'
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── DB接続 ─────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST','localhost'), port=os.getenv('DB_PORT','5432'),
        dbname=os.getenv('DB_NAME','faceapp'), user=os.getenv('DB_USER','postgres'),
        password=os.getenv('DB_PASSWORD','postgrestest')
    )

# ── llavaで画像を英語分析 ───────────────────────────
def analyze_image_llava(image_path):
    """
    llava:7bに競走馬の画像を渡し、コンディション評価を得る。
    Returns: (score: float 0-100, raw_text: str)
    """
    abs_path = os.path.join(PROJECT_DIR, image_path.lstrip('/'))
    if not os.path.exists(abs_path):
        return None, None

    with open(abs_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    prompt = """Analyze this racehorse photo and rate its physical condition on a scale of 1-10.

Evaluate these aspects:
1. Eye brightness and alertness (1-10)
2. Coat shine and quality (1-10)
3. Body muscle tone and definition (1-10)
4. Overall energy and vitality (1-10)

Respond ONLY in this exact JSON format:
{
  "eyes": <score>,
  "coat": <score>,
  "muscle": <score>,
  "vitality": <score>,
  "summary": "<one sentence in English about the horse's condition>"
}"""

    try:
        resp = requests.post(OLLAMA_URL, json={
            'model': OLLAMA_MODEL,
            'prompt': prompt,
            'images': [img_b64],
            'stream': False,
            'options': {'temperature': 0.1}
        }, timeout=90)
        resp.raise_for_status()
        raw = resp.json().get('response', '')
        return raw
    except requests.exceptions.ConnectionError:
        print(f"    [エラー] Ollamaに接続できません。ollama serve が起動しているか確認してください")
        return None
    except requests.exceptions.Timeout:
        print(f"    [エラー] Ollamaの応答タイムアウト（90秒）")
        return None
    except Exception as e:
        print(f"    [エラー] llava分析失敗: {e}")
        return None

# ── JSON抽出 ────────────────────────────────────────
def parse_llava_response(raw):
    """レスポンスからJSONを抽出してスコアを計算"""
    if not raw:
        return None

    # JSON部分を抽出
    m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group())
        eyes    = float(data.get('eyes', 5))
        coat    = float(data.get('coat', 5))
        muscle  = float(data.get('muscle', 5))
        vitality= float(data.get('vitality', 5))
        summary = data.get('summary', '')
        # 40点満点 → 100点換算
        avg = (eyes + coat + muscle + vitality) / 4.0
        score = round(avg * 10, 1)
        return {
            'eyes': eyes, 'coat': coat, 'muscle': muscle, 'vitality': vitality,
            'summary': summary, 'face_score': score
        }
    except Exception:
        return None

# ── コンディションからコメント生成（バリエーション豊富版）───
EYES_HIGH = [
    "双眸に炎のような鋭さが宿り、今日の舞台への闘志がにじみ出ている",
    "瞳の奥に刃のような光を秘め、スタート前から覇気が満ちている",
    "目力が別格。ゲートが開く前から勝負師の顔つきだ",
    "眼光鋭く、周囲を圧倒するほどの気迫を放っている",
    "吸い込まれるような瞳の輝きに、底知れないポテンシャルを感じる",
    "視線が凛として定まり、心身の充実ぶりが伝わってくる",
]
EYES_MID = [
    "落ち着いた眼差しで冷静さをキープ、無駄なエネルギーを使っていない",
    "穏やかな表情の中に確かな集中力があり、安定感を感じさせる",
    "程よいリラックス状態。返し馬でガラッと変わる期待もある",
    "物静かな目つきが意外な切れ味を示唆する。侮れない",
    "冷静な眼差しの奥に燻る闘争心。ここ一番での爆発力に期待",
]
EYES_LOW = [
    "眼差しにやや覇気が感じられない。気持ちが乗りきっていないか",
    "目の輝きが今ひとつ。パドックでの気配を要チェック",
    "若干うつろな視線が気になる。状態面に疑問符がつく",
    "集中力の欠如が見受けられる。本番で巻き返せるか",
]

COAT_HIGH = [
    "毛艶が水を弾くように光り輝き、これ以上ない仕上がりを誇る",
    "コートが絹のように艶めき、調教師も会心の仕上がりと語るだろう",
    "全身が照り輝くほどの毛艶。入念なケアの成果が一目で分かる",
    "鏡のように反射する毛並みは、最高潮のコンディションの証明",
    "光沢感抜群の被毛が、今が旬の状態であることを雄弁に物語る",
]
COAT_MID = [
    "毛並みは整っており、標準的な仕上がり",
    "コートは及第点。特段の心配はないが、もう一押し欲しい",
    "毛ヅヤは悪くない。維持調整がうまくいっている印象",
    "まとまった仕上がりで、急仕上げの気配はない",
]
COAT_LOW = [
    "毛艶にくすみが見られ、仕上がりに課題が残る",
    "被毛の光沢がやや欠け、本来のポテンシャルを出し切れていない可能性",
    "コートのコンディションが今ひとつ。デキ落ちの懸念あり",
    "毛並みの物足りなさが状態の陰りを示唆している",
]

MUSCLE_HIGH = [
    "全身の筋肉が均整のとれた盛り上がりを見せ、完璧な体型美を誇る",
    "ハリのある筋肉が理想的なフォルムを形成。まさに戦う体だ",
    "腹周りが絞れ、腰のラインが美しい。これが本来の姿だろう",
    "たくましい筋肉の張りが自信を体現しており、目を惹くフィジカルだ",
    "弾けんばかりの筋肉の充実度。力強い走りが期待できる",
]
MUSCLE_MID = [
    "体の張りはまずまずで、十分戦える体づくりができている",
    "筋肉量は標準的。この馬の能力があれば問題ない",
    "やや線は細いが、軽快さを活かした走りができる体型",
    "コンパクトにまとまった体型。小柄ながら瞬発力は秘めている",
]
MUSCLE_LOW = [
    "やや細身で馬体の張りが物足りない。疲れが残っていないか",
    "筋肉の盛り上がりが今ひとつ。デキの維持が心配",
    "馬体重に見合った張りが感じられない。叩き台の可能性も",
    "絞れすぎた印象。調整不足か、それとも軽量化が狙いか",
]

# 総合一言（スコア帯×パターン）
OVERALL_PERFECT = [
    "文句のつけようのない完璧な状態。本番での爆発に期待大",
    "全項目がハイレベルで揃い、「負けられない」気迫が漂う",
    "パドックでも主役オーラ全開。今日のベストコンディション",
    "写真の時点でこの出来栄え。レース当日はさらに上積みも",
    "馬自身が「今日がピーク」と語っているような仕上がり",
]
OVERALL_GOOD = [
    "全体的に好状態をキープ。本番での力発揮は十分できる",
    "及第点以上の仕上がり。あとは枠とペース次第",
    "崩れた部分がなく、安定したパフォーマンスが期待できる",
    "好調期をしっかりつかんだ印象。凡走するイメージが湧かない",
    "バランスの取れた好状態。鞍上の腕次第でどこまでも",
]
OVERALL_AVG = [
    "可もなく不可もなし。潜在能力が上回れば問題ない",
    "平均的な仕上がり。展開のアヤで一変する可能性は秘める",
    "特別なプラスもなければ、大きなマイナスもない。能力比べ",
    "コンディションは中程度。調教内容との兼ね合いで判断を",
    "実力馬なら多少のデキ落ちは関係ない。底力に期待",
]
OVERALL_POOR = [
    "心配な点が目立つ。今回は様子見が無難か",
    "コンディションに不安材料あり。出走回避も視野に？",
    "万全でない状態での出走ならば、過度な期待は禁物",
    "叩き台として使い、次走での変身に期待したい",
    "状態面でのマイナスが大きい。一発逆転を狙うなら次回",
]

def build_face_comment(parsed, horse_name):
    if not parsed:
        return "写真からの分析データなし"

    score    = parsed['face_score']
    eyes     = parsed['eyes']
    coat     = parsed['coat']
    muscle   = parsed['muscle']
    vitality = parsed['vitality']

    # 各項目の評価フレーズをランダムに選択
    if eyes >= 8.5:
        eye_phrase = random.choice(EYES_HIGH)
    elif eyes >= 6.5:
        eye_phrase = random.choice(EYES_MID)
    else:
        eye_phrase = random.choice(EYES_LOW)

    if coat >= 8.5:
        coat_phrase = random.choice(COAT_HIGH)
    elif coat >= 6.5:
        coat_phrase = random.choice(COAT_MID)
    else:
        coat_phrase = random.choice(COAT_LOW)

    if muscle >= 8.5:
        muscle_phrase = random.choice(MUSCLE_HIGH)
    elif muscle >= 6.5:
        muscle_phrase = random.choice(MUSCLE_MID)
    else:
        muscle_phrase = random.choice(MUSCLE_LOW)

    # 最も気になる点と最も褒めるべき点を前後に配置
    scores_map = [('eyes', eyes), ('coat', coat), ('muscle', muscle), ('vitality', vitality)]
    best = max(scores_map, key=lambda x: x[1])[0]
    worst = min(scores_map, key=lambda x: x[1])[0]

    # フレーズ配列：ベスト項目 → その他 → 総合
    phrases = []
    order = ['eyes', 'coat', 'muscle']
    # ベスト項目を先頭に
    order.sort(key=lambda k: -({'eyes': eyes, 'coat': coat, 'muscle': muscle}[k]))
    phrase_map = {'eyes': eye_phrase, 'coat': coat_phrase, 'muscle': muscle_phrase}
    for k in order:
        phrases.append(phrase_map[k])

    # 総合一言
    if score >= 82:
        overall = random.choice(OVERALL_PERFECT)
    elif score >= 68:
        overall = random.choice(OVERALL_GOOD)
    elif score >= 54:
        overall = random.choice(OVERALL_AVG)
    else:
        overall = random.choice(OVERALL_POOR)

    # 2〜3フレーズ＋総合でコメント生成（長くなりすぎないよう上位2項目を採用）
    body = "。".join(phrases[:2])
    return f"{body}。{overall}"

# ── メイン ──────────────────────────────────────────
def main():
    race_name = sys.argv[1] if len(sys.argv) > 1 else '大阪杯'

    print(f"{'='*60}")
    print(f"  llava顔面分析: {race_name}")
    print(f"  モデル: {OLLAMA_MODEL} (ローカル・APIなし)")
    print(f"{'='*60}\n")

    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            # 対象レースの馬を取得
            cur.execute("""
                SELECT id, horse_name, image_path, rank_position
                FROM stats_prediction
                WHERE race_name = %s AND image_path IS NOT NULL
                ORDER BY rank_position
            """, (race_name,))
            horses = cur.fetchall()

            if not horses:
                print(f"❌ {race_name} の出走馬データがありません")
                return

            print(f"対象馬: {len(horses)}頭\n")

            for row_id, horse_name, image_path, rank in horses:
                print(f"  {rank}位 {horse_name} ... ", end='', flush=True)

                raw = analyze_image_llava(image_path)
                if raw is None:
                    print("写真なし/分析失敗")
                    continue

                parsed = parse_llava_response(raw)
                face_comment = build_face_comment(parsed, horse_name)
                face_score   = parsed['face_score'] if parsed else None

                # DB更新
                cur.execute("""
                    UPDATE stats_prediction
                    SET face_comment = %s, face_score = %s, face_analyzed_at = NOW()
                    WHERE id = %s
                """, (face_comment, face_score, row_id))
                conn.commit()

                if parsed:
                    print(f"スコア{face_score}点 | {face_comment}")
                else:
                    print(f"(JSON解析失敗) {face_comment}")

                # llavaへの負荷軽減
                time.sleep(0.5)

        finally:
            cur.close()
    finally:
        conn.close()

    print(f"\n{'='*60}")
    print(f"✅ {race_name} の顔面分析完了")
    print(f"   → /stats-predict?raceName={race_name} で確認")
    print(f"{'='*60}")
    print(f"\nRESULT:{json.dumps({'success':True,'race':race_name}, ensure_ascii=False)}")

    # llava:7b をRAMから即時解放（keep_alive=0）
    try:
        requests.post(OLLAMA_URL, json={'model': OLLAMA_MODEL, 'keep_alive': 0}, timeout=10)
        print("🧹 llava:7b をメモリから解放しました")
    except Exception:
        pass

if __name__ == '__main__':
    main()
