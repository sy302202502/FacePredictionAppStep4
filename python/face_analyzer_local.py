"""
face_analyzer_local.py  ― ローカルllava:7bで馬の顔面分析（APIクレジット不要）

Ollama + llava:7b モデルを使って競走馬の写真を解析し、
コンディションスコアと日本語コメントをDBに保存する。

使い方:
  python face_analyzer_local.py 大阪杯
"""

import sys, os, json, time, requests, random
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR  = os.environ.get('UPLOAD_DIR', os.path.join(PROJECT_DIR, 'uploads'))

def _url_to_fs(url_path):
    """URL path (/uploads/...) をファイルシステムパスに変換する。"""
    rel = url_path.lstrip('/')
    if rel.startswith('uploads/'):
        rel = rel[len('uploads/'):]
    return os.path.join(UPLOAD_DIR, rel)

# LLM抽象化レイヤー
from llm_client import analyze_image as _llm_analyze_image, current_provider as _llm_provider
from llm_client import OLLAMA_MODEL, OLLAMA_BASE, PROVIDER as _PROVIDER
OLLAMA_URL = OLLAMA_BASE + '/api/generate'

# ── DB接続 ─────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST','localhost'), port=os.getenv('DB_PORT','5432'),
        dbname=os.getenv('DB_NAME','faceapp'), user=os.getenv('DB_USER','postgres'),
        password=os.getenv('DB_PASSWORD','postgrestest'),
        connect_timeout=int(os.getenv('PGCONNECT_TIMEOUT', '15')),
        options='-c statement_timeout=60000'
    )

# ── llavaで画像を英語分析 ───────────────────────────
def analyze_image_llava(image_path):
    """
    LLMに競走馬の画像を渡し、コンディション評価を得る。
    Returns: raw_text (str) or None on failure
    """
    abs_path = _url_to_fs(image_path)
    if not os.path.exists(abs_path):
        print(f"    [警告] 画像ファイルが見つかりません: {abs_path}")
        return None

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
        # validator: スコア解析できるレスポンスのみ採用（不可なら次プロバイダーへ）
        return _llm_analyze_image(abs_path, prompt,
                                  validator=lambda txt: parse_llava_response(txt) is not None)
    except Exception as e:
        print(f"    [エラー] LLM分析失敗: {e}")
        return None

# ── JSON抽出 ────────────────────────────────────────
def _clamp_score(v):
    """スコアを1〜10にクランプ。数値化できなければ None"""
    try:
        return min(10.0, max(1.0, float(v)))
    except (TypeError, ValueError):
        return None

def parse_llava_response(raw):
    """
    レスポンスからJSONを抽出してスコアを計算。
    必須キー(eyes/coat/muscle/vitality)が1つも取れなければ分析失敗としてNoneを返す
    （= 偽の50.0点を生成しない）。
    """
    if not raw:
        return None

    # マークダウン等を無視し、最初の { 〜 最後の } を抽出
    start = raw.find('{')
    end   = raw.rfind('}')
    if start == -1 or end == -1 or end <= start:
        print(f"[警告] JSONが見つかりません: {raw[:80]!r}")
        return None

    try:
        data = json.loads(raw[start:end + 1])
    except Exception as e:
        print(f"[警告] LLMレスポンスのJSON解析失敗: {e}")
        return None

    if not isinstance(data, dict):
        return None

    # 各スコアを取得（取れたものだけ採用）
    raw_scores = {k: _clamp_score(data.get(k))
                  for k in ('eyes', 'coat', 'muscle', 'vitality')}
    valid = {k: v for k, v in raw_scores.items() if v is not None}

    # 1つも有効スコアが取れなければ失敗扱い
    if not valid:
        print(f"[警告] 有効なスコアキーがありません: {list(data.keys())}")
        return None

    # 欠落キーは有効スコアの平均で補完（極端な偏りを避ける）
    fill = sum(valid.values()) / len(valid)
    eyes     = raw_scores['eyes']     if raw_scores['eyes']     is not None else fill
    coat     = raw_scores['coat']     if raw_scores['coat']     is not None else fill
    muscle   = raw_scores['muscle']   if raw_scores['muscle']   is not None else fill
    vitality = raw_scores['vitality'] if raw_scores['vitality'] is not None else fill
    summary  = data.get('summary', '')

    avg = (eyes + coat + muscle + vitality) / 4.0
    score = round(avg * 10, 1)
    return {
        'eyes': eyes, 'coat': coat, 'muscle': muscle, 'vitality': vitality,
        'summary': summary, 'face_score': score
    }

# ── コンディションからコメント生成（バリエーション豊富版）───
EYES_HIGH = [
    "双眸に炎のような鋭さが宿り、今日の舞台への闘志がにじみ出ている",
    "瞳の奥に刃のような光を秘め、スタート前から覇気が満ちている",
    "目力が別格。ゲートが開く前から勝負師の顔つきだ",
    "眼光鋭く、周囲を圧倒するほどの気迫を放っている",
    "吸い込まれるような瞳の輝きに、底知れないポテンシャルを感じる",
    "視線が凛として定まり、心身の充実ぶりが伝わってくる",
    "獲物を見据える猛禽のような眼差し。勝負どころを知り尽くした目だ",
    "瞳に宿る静かな炎が、内に秘めた爆発力を物語っている",
    "一点を射抜くような視線の強さ。レースへの集中力は申し分ない",
    "黒目がちな瞳が爛々と輝き、生気がみなぎっている",
    "目の奥に確かな知性と闘気が同居する、王者の風格を感じる眼差し",
    "瞬きの少ない据わった目つきが、極限の集中状態を示している",
]
EYES_MID = [
    "落ち着いた眼差しで冷静さをキープ、無駄なエネルギーを使っていない",
    "穏やかな表情の中に確かな集中力があり、安定感を感じさせる",
    "程よいリラックス状態。返し馬でガラッと変わる期待もある",
    "物静かな目つきが意外な切れ味を示唆する。侮れない",
    "冷静な眼差しの奥に燻る闘争心。ここ一番での爆発力に期待",
    "気負いのない自然体の表情。実戦モードへの切り替えに注目",
    "涼しげな目元に余裕すら感じる。力を出し切れる精神状態か",
    "ほどよい緊張感をたたえた瞳。気持ちの入り方は悪くない",
    "淡々とした佇まいだが、目の芯には確かな光がある",
    "感情を表に出さないポーカーフェイス。秘めた闘志に賭けたい",
]
EYES_LOW = [
    "眼差しにやや覇気が感じられない。気持ちが乗りきっていないか",
    "目の輝きが今ひとつ。パドックでの気配を要チェック",
    "若干うつろな視線が気になる。状態面に疑問符がつく",
    "集中力の欠如が見受けられる。本番で巻き返せるか",
    "目元に疲れの色がにじむ。間隔詰めの影響が出ていないか心配",
    "どこか心ここにあらずの表情。気持ちのスイッチが入るかが鍵",
    "視線が定まらず落ち着きを欠く。イレ込みすぎの懸念も",
    "瞳の生気が乏しく、本来の気迫が影を潜めている",
]

COAT_HIGH = [
    "毛艶が水を弾くように光り輝き、これ以上ない仕上がりを誇る",
    "コートが絹のように艶めき、調教師も会心の仕上がりと語るだろう",
    "全身が照り輝くほどの毛艶。入念なケアの成果が一目で分かる",
    "鏡のように反射する毛並みは、最高潮のコンディションの証明",
    "光沢感抜群の被毛が、今が旬の状態であることを雄弁に物語る",
    "ビロードのような手触りを思わせる極上の毛並み。万全の仕上げだ",
    "陽光を浴びて黄金色に輝く馬体。これぞ勝負仕上げの艶",
    "皮膚の薄さまで伝わる研ぎ澄まされた被毛。究極まで磨かれている",
    "一頭だけ照明が当たっているかのような輝き。状態の良さは群を抜く",
    "毛先まで栄養が行き届いた極上のコート。心身の充実が透けて見える",
]
COAT_MID = [
    "毛並みは整っており、標準的な仕上がり",
    "コートは及第点。特段の心配はないが、もう一押し欲しい",
    "毛ヅヤは悪くない。維持調整がうまくいっている印象",
    "まとまった仕上がりで、急仕上げの気配はない",
    "季節なりの毛艶は確保。平行線ながら安定したデキ",
    "派手さはないが手入れの行き届いた毛並み。好調持続型か",
    "被毛の状態は水準級。叩かれつつ上向く余地を残す",
    "落ち着いた光沢の馬体。大きな減点材料は見当たらない",
]
COAT_LOW = [
    "毛艶にくすみが見られ、仕上がりに課題が残る",
    "被毛の光沢がやや欠け、本来のポテンシャルを出し切れていない可能性",
    "コートのコンディションが今ひとつ。デキ落ちの懸念あり",
    "毛並みの物足りなさが状態の陰りを示唆している",
    "冬毛の名残か、被毛にざらつきが見える。本調子まであと一息",
    "毛色が冴えず、ピークを過ぎた感も。過信は禁物",
    "艶を欠いた馬体が調整の難しさを物語る。割引が必要か",
]

MUSCLE_HIGH = [
    "全身の筋肉が均整のとれた盛り上がりを見せ、完璧な体型美を誇る",
    "ハリのある筋肉が理想的なフォルムを形成。まさに戦う体だ",
    "腹周りが絞れ、腰のラインが美しい。これが本来の姿だろう",
    "たくましい筋肉の張りが自信を体現しており、目を惹くフィジカルだ",
    "弾けんばかりの筋肉の充実度。力強い走りが期待できる",
    "トモの筋肉が見事に発達し、爆発的な推進力を予感させる",
    "胸前の厚みと首差しのバランスが絶妙。完成度の高い馬体だ",
    "鋼のようにしなやかな筋肉が全身を覆う。アスリートの肉体美",
    "余分な脂肪が削ぎ落とされ、筋骨隆々の臨戦体型に仕上がった",
    "皮膚の下で躍動する筋肉のうねりが見える。パワーは申し分ない",
]
MUSCLE_MID = [
    "体の張りはまずまずで、十分戦える体づくりができている",
    "筋肉量は標準的。この馬の能力があれば問題ない",
    "やや線は細いが、軽快さを活かした走りができる体型",
    "コンパクトにまとまった体型。小柄ながら瞬発力は秘めている",
    "成長途上の馬体ながら、走りに必要な筋肉は備わっている",
    "全体のバランスは良好。あとは実戦でどこまでやれるか",
    "標準的な筋肉のつき方だが、柔らかさがあり伸びしろを感じる",
    "可もなく不可もない馬体。展開ひとつで上位進出も",
]
MUSCLE_LOW = [
    "やや細身で馬体の張りが物足りない。疲れが残っていないか",
    "筋肉の盛り上がりが今ひとつ。デキの維持が心配",
    "馬体重に見合った張りが感じられない。叩き台の可能性も",
    "絞れすぎた印象。調整不足か、それとも軽量化が狙いか",
    "トモの寂しさが気になる。距離延長ならなおさら割引",
    "腹回りに余裕があり、仕上がり途上の感は否めない",
    "全体的に緩さの残る馬体。一度使ってからが本番か",
]

# 総合一言（スコア帯×パターン）
OVERALL_PERFECT = [
    "文句のつけようのない完璧な状態。本番での爆発に期待大",
    "全項目がハイレベルで揃い、「負けられない」気迫が漂う",
    "パドックでも主役オーラ全開。今日のベストコンディション",
    "写真の時点でこの出来栄え。レース当日はさらに上積みも",
    "馬自身が「今日がピーク」と語っているような仕上がり",
    "鬼の目にも狂いなし。この仕上がりは本物だ",
    "心技体すべてが噛み合った会心のデキ。買い材料しかない",
    "デビュー以来最高と言いたくなる充実ぶり。勝ち負け必至",
    "陣営の本気がひしひしと伝わる渾身の仕上げ。勝負気配は最高潮",
]
OVERALL_GOOD = [
    "全体的に好状態をキープ。本番での力発揮は十分できる",
    "及第点以上の仕上がり。あとは枠とペース次第",
    "崩れた部分がなく、安定したパフォーマンスが期待できる",
    "好調期をしっかりつかんだ印象。凡走するイメージが湧かない",
    "バランスの取れた好状態。鞍上の腕次第でどこまでも",
    "順調さがうかがえる馬体。能力を出し切れる態勢は整った",
    "高値安定のコンディション。大崩れの心配は少ない",
    "攻め駆けするタイプの好気配。馬券圏内は十分視野",
    "じわじわと調子を上げてきた印象。ピークは今週末か",
]
OVERALL_AVG = [
    "可もなく不可もなし。潜在能力が上回れば問題ない",
    "平均的な仕上がり。展開のアヤで一変する可能性は秘める",
    "特別なプラスもなければ、大きなマイナスもない。能力比べ",
    "コンディションは中程度。調教内容との兼ね合いで判断を",
    "実力馬なら多少のデキ落ちは関係ない。底力に期待",
    "標準的な気配。人気の盲点になるなら妙味はある",
    "良くも悪くも平行線。相手なりに走れるタイプなら",
    "目立った上積みは見えないが、地力で足りるかどうか",
]
OVERALL_POOR = [
    "心配な点が目立つ。今回は様子見が無難か",
    "コンディションに不安材料あり。出走回避も視野に？",
    "万全でない状態での出走ならば、過度な期待は禁物",
    "叩き台として使い、次走での変身に期待したい",
    "状態面でのマイナスが大きい。一発逆転を狙うなら次回",
    "本調子には程遠い気配。見送りが賢明かもしれない",
    "良化の兆しが見えず厳しい評価に。巻き返しは次走以降",
    "気配・馬体ともに低調。今回は静観して次を待ちたい",
]

class PhrasePicker:
    """レース内でフレーズが重複しないよう、シャッフル済みプールから順に取り出す。
    プールを使い切った場合のみ再シャッフルして再利用する。"""
    def __init__(self):
        self._pools = {}

    def pick(self, options):
        key = id(options)
        pool = self._pools.get(key)
        if not pool:
            pool = options[:]
            random.shuffle(pool)
            self._pools[key] = pool
        return pool.pop()


def build_face_comment(parsed, horse_name, picker=None, horse_number=None):
    if not parsed:
        return "写真からの分析データなし"

    if picker is None:
        picker = PhrasePicker()

    score    = parsed['face_score']
    eyes     = parsed['eyes']
    coat     = parsed['coat']
    muscle   = parsed['muscle']
    vitality = parsed['vitality']

    # 各項目の評価フレーズを重複なしプールから選択
    if eyes >= 8.5:
        eye_phrase = picker.pick(EYES_HIGH)
    elif eyes >= 6.5:
        eye_phrase = picker.pick(EYES_MID)
    else:
        eye_phrase = picker.pick(EYES_LOW)

    if coat >= 8.5:
        coat_phrase = picker.pick(COAT_HIGH)
    elif coat >= 6.5:
        coat_phrase = picker.pick(COAT_MID)
    else:
        coat_phrase = picker.pick(COAT_LOW)

    if muscle >= 8.5:
        muscle_phrase = picker.pick(MUSCLE_HIGH)
    elif muscle >= 6.5:
        muscle_phrase = picker.pick(MUSCLE_MID)
    else:
        muscle_phrase = picker.pick(MUSCLE_LOW)

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
    comment = f"{body}。{overall}"
    # 馬番が分かる場合はコメント先頭に付ける（例:【3番】...）
    if horse_number is not None:
        comment = f"【{int(horse_number)}番】{comment}"
    return comment

# ── メイン ──────────────────────────────────────────
def main():
    race_name = sys.argv[1] if len(sys.argv) > 1 else '大阪杯'
    # 第2引数に race_id（推奨）。指定時は開催を一意に特定できるため、
    # 年またぎ同名レースの残存行を誤って対象にしない。
    race_id = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].isdigit() else None

    print(f"{'='*60}")
    print(f"  llava顔面分析: {race_name}" + (f" (race_id={race_id})" if race_id else ''))
    print(f"  モデル: {_llm_provider()}")
    print(f"{'='*60}\n")

    # 突合条件: race_id があれば race_id、なければ従来どおり race_name（手動実行互換）
    if race_id:
        cond, cond_arg = "race_id = %s", race_id
    else:
        cond, cond_arg = "race_name = %s", race_name

    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            # 対象レースの馬を取得（未分析の馬のみ — API呼び出しの節約）
            cur.execute(f"""
                SELECT id, horse_name, image_path, rank_position, horse_number
                FROM stats_prediction
                WHERE {cond}
                  AND image_path IS NOT NULL
                  AND face_comment IS NULL
                ORDER BY rank_position
            """, (cond_arg,))
            horses = cur.fetchall()

            if not horses:
                # 分析対象が0頭。ただし「全頭分析済み」と「画像未設定で分析不能」を
                # 区別する。後者を成功扱いにすると、1頭も分析していないのに
                # パイプラインが ✅done と記録してしまう（顔面0頭バグの温床）。
                cur.execute(f"""
                    SELECT COUNT(*),
                           COUNT(face_comment),
                           COUNT(*) FILTER (WHERE face_comment IS NULL AND image_path IS NULL)
                    FROM stats_prediction
                    WHERE {cond}
                """, (cond_arg,))
                total, analyzed, missing_img = cur.fetchone()
                if total == 0:
                    print(f"❌ {race_name} の出走馬データがありません")
                    print(f"\nRESULT:{json.dumps({'success': False, 'race': race_name, 'reason': 'no entries'}, ensure_ascii=False)}")
                    sys.exit(1)
                if missing_img > 0:
                    # image_path 未設定＝顔写真に紐付けできず分析不能。未完了として失敗終了。
                    # （image_path は weekly_pipeline / predict_by_race_id が horse_id で反映する）
                    print(f"❌ {race_name}: {missing_img}頭の image_path が未設定で分析できません（未完了）")
                    print(f"\nRESULT:{json.dumps({'success': False, 'race': race_name, 'reason': 'missing image_path'}, ensure_ascii=False)}")
                    sys.exit(1)
                print(f"✅ {race_name} は全頭分析済みのためスキップしました（{analyzed}/{total}頭）")
                return

            print(f"対象馬: {len(horses)}頭\n")

            success_count = 0
            picker = PhrasePicker()  # レース内でコメントが重複しないよう共有
            for row_id, horse_name, image_path, rank, horse_number in horses:
                print(f"  {rank}位 {horse_name} ... ", end='', flush=True)

                raw = analyze_image_llava(image_path)
                if raw is None:
                    # 全プロバイダー失敗（レート制限等）→ 記録せず次回再試行
                    print("写真なし/分析失敗（次回再試行）")
                    continue

                parsed = parse_llava_response(raw)
                if not parsed:
                    # JSON解析失敗 → 記録せず次回再試行（偽スコアを残さない）
                    print("JSON解析失敗（次回再試行）")
                    continue

                face_comment = build_face_comment(parsed, horse_name,
                                                  picker=picker, horse_number=horse_number)
                face_score   = parsed['face_score']

                # DB更新（解析成功時のみ）
                cur.execute("""
                    UPDATE stats_prediction
                    SET face_comment = %s, face_score = %s, face_analyzed_at = NOW()
                    WHERE id = %s
                """, (face_comment, face_score, row_id))
                conn.commit()
                success_count += 1

                print(f"スコア{face_score}点 | {face_comment}")

                # llavaへの負荷軽減
                time.sleep(0.5)

            if success_count == 0:
                # 1頭も分析できなかった場合は失敗として終了
                # （パイプライン側で face_failed と記録され、Discord通知に❌が出る）
                print(f"\n❌ {race_name}: {len(horses)}頭中0頭しか分析できませんでした")
                print(f"\nRESULT:{json.dumps({'success': False, 'race': race_name}, ensure_ascii=False)}")
                sys.exit(1)

            if success_count < len(horses):
                # 部分成功も「未完了」として正直に失敗を返す（偽成功防止）。
                # 未分析馬は face_comment IS NULL のまま残るため翌run で自動再試行される。
                # 重賞はDB検証+Discord警告で既に同じ扱いのため、全レースで基準を統一。
                remaining = len(horses) - success_count
                print(f"\n⚠️ {race_name}: {success_count}/{len(horses)}頭のみ分析成功（残り{remaining}頭は次回再試行）")
                print(f"\nRESULT:{json.dumps({'success': False, 'race': race_name, 'reason': 'partial', 'analyzed': success_count, 'remaining': remaining}, ensure_ascii=False)}")
                sys.exit(1)

        finally:
            cur.close()
    finally:
        conn.close()

    print(f"\n{'='*60}")
    print(f"✅ {race_name} の顔面分析完了")
    print(f"   → /stats-predict?raceName={race_name} で確認")
    print(f"{'='*60}")
    print(f"\nRESULT:{json.dumps({'success':True,'race':race_name}, ensure_ascii=False)}")

    # llava:7b をRAMから即時解放（keep_alive=0）— Ollama使用時のみ
    if _PROVIDER == 'ollama':
        try:
            requests.post(OLLAMA_URL, json={'model': OLLAMA_MODEL, 'keep_alive': 0}, timeout=10)
            print("🧹 llava:7b をメモリから解放しました")
        except Exception as e:
            print(f"[警告] モデル解放失敗: {e}")

if __name__ == '__main__':
    main()
