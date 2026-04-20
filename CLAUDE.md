# 🏇 競馬顔面予想アプリ — AI向けプロジェクト説明プロンプト

## アプリ概要

競走馬の「顔面写真」をAI（llava:7b）で分析し、過去レースの勝ち馬・負け馬の顔の特徴パターンを学習して今週の出走馬を予想するWebアプリ。
オーナーは VTuber「舞鬼法師（MIKEY MASTER）」として活動する競馬好き。
デザインはネオングリーン×オレンジ×パープルのサイバーパンク/格闘ゲーム風。

---

## 技術スタック

| 層 | 技術 |
|---|---|
| バックエンド | Spring Boot 2.7.6 / Java 11 |
| テンプレートエンジン | Thymeleaf |
| DB | PostgreSQL（ローカル, DB名: faceapp） |
| 顔分析AI | llava:7b（Ollama ローカル実行） |
| スクレイピング | Python 3.9 / requests / BeautifulSoup |
| フロントエンド | Vanilla JS / CSS（glassmorphism + neon） |
| 外部データ | netkeiba.com（スクレイピング） |
| ローカル実行URL | http://localhost:8081 |

---

## ディレクトリ構成

```
FacePredictionAppStep4/
├── src/main/
│   ├── java/com/faceprediction/
│   │   ├── controller/     # Spring MVCコントローラー（12本）
│   │   ├── entity/         # JPAエンティティ
│   │   ├── repository/     # JPAリポジトリ
│   │   └── service/        # ビジネスロジック
│   └── resources/
│       ├── templates/      # Thymeleaf HTMLテンプレート（14ページ）
│       │   ├── fragments/navbar.html   # 共通ナビゲーション
│       │   ├── index.html              # ダッシュボード
│       │   ├── prediction/v2.html      # メイン予想ページ（VTuber UI）
│       │   ├── prediction/paddock.html # パドック写真分析
│       │   ├── prediction/weekly.html  # 週次パイプライン
│       │   ├── prediction/stats_predict.html # 統計予想
│       │   ├── calendar/index.html     # レースカレンダー
│       │   ├── entry/index.html        # 出走馬一覧
│       │   ├── accuracy/index.html     # 予想精度トラッキング
│       │   ├── horse/list.html         # 馬一覧
│       │   ├── horse/detail.html       # 馬詳細
│       │   ├── health/index.html       # ヘルスチェック
│       │   └── script/index.html       # スクリプト実行UI
│       └── application.properties
├── python/                 # 分析・スクレイピングスクリプト群（18本）
└── uploads/
    ├── candidates/         # 出走馬候補写真（horse_id.jpg）
    └── race_specific/      # 過去レース馬写真
```

---

## DBテーブル構成（PostgreSQL: faceapp）

| テーブル | 役割 |
|---|---|
| `horse_face_feature` | 馬の顔特徴データ（目・鼻・印象など8特徴＋数値5項目） |
| `race_entry` | 今週の出走馬データ（馬名・馬番・騎手・レース名） |
| `race_specific_prediction` | レース特化型予想結果（TOP5パターン・信頼度） |
| `race_specific_result` | 予想結果の個別馬スコア |
| `prediction_result` | 汎用予想結果 |
| `prediction_accuracy` | 予想精度トラッキング |
| `race_odds` | オッズデータ |
| `grade_race_result` | 重賞レース結果 |
| `stats_prediction` | 統計ベース予想 |

### horse_face_feature の主要カラム
```sql
horse_id, horse_name, image_path, finish_rank, race_category,
nose_shape, eye_size, eye_shape, face_contour, forehead_width,
nostril_size, jaw_line, overall_impression,
eye_aspect_ratio, nose_width_ratio, face_aspect_ratio,
jaw_strength_score, overall_intensity
```

---

## メイン分析スクリプト: race_specific_analyzer.py

```
使い方:
  python3 python/race_specific_analyzer.py "レース名" [年数] [検索ワード]

例:
  python3 python/race_specific_analyzer.py "皐月賞" 10
  python3 python/race_specific_analyzer.py "春雷S" 10 "春雷ステークス"
```

### 処理フロー（9ステップ）
| Step | 内容 |
|---|---|
| Step1 | netkeiba.comで過去N年分の開催を検索 |
| Step2 | 全着順データ取得＋馬写真ダウンロード |
| Step3 | llava:7bで顔特徴をJSON分析（8ラベル＋5数値） |
| Step3b | 画像なし馬は血統（父馬）ベースで推定 |
| Step3c | 父馬情報・体重統計を取得 |
| Step4 | 5着内 vs 6着以下 の特徴パターン集計 |
| Step5 | 傾向コメント自動生成 |
| Step6 | 今年の出走馬をrace_entryから取得 |
| Step7 | 各馬をスコアリング（顔40%・統計40%・体重10%・父馬10%） |
| Step8 | TOP5予想をDBに保存 |

### スコア計算式
```
total_score = face_score * 0.4
            + stats_score * 0.4
            + weight_score * 0.1
            + sire_score * 0.1
```

### 重要な定数
```python
OLLAMA_MODEL = 'llava:7b'
TOP5_BORDER = 5       # 5着以内をTOP群とする
BOTTOM_ANALYZE = 3    # 各開催の最下位3頭を分析
MIN_HORSES_FOR_PATTERN = 10
SUPPLEMENT_THRESHOLD = 30  # 30頭未満なら補完データ使用
```

---

## Pythonスクリプト一覧

| スクリプト | 役割 |
|---|---|
| `race_specific_analyzer.py` | レース特化型顔面分析・予想（メイン） |
| `entry_fetcher.py` | netkeiba出走馬データ取得 |
| `scraper.py` | 汎用スクレイピング |
| `face_analyzer_local.py` | llava:7bローカル顔分析 |
| `paddock_analyzer.py` | パドック写真分析 |
| `stats_predictor.py` | 統計ベース予想 |
| `weekly_pipeline.py` | 週次一括処理パイプライン |
| `accuracy_tracker.py` | 予想精度の自動記録 |
| `result_auto_fetcher.py` | レース結果自動取得 |
| `weight_learner.py` | 体重トレンド学習 |
| `odds_fetcher.py` | オッズデータ取得 |
| `composite_scorer.py` | 複合スコアリング |
| `scheduler.py` | 定期実行スケジューラ |
| `notifier.py` | 通知機能 |
| `pdf_exporter.py` | PDF出力 |
| `setup_db.py` | DB初期化 |

---

## デザインシステム（CSS変数）

```css
:root {
  --neon: #7dff4f;          /* ネオングリーン（メインアクセント） */
  --orange: #ff8000;        /* オレンジ（2番アクセント） */
  --purple: #8b5cf6;        /* パープル（VTuberカラー・3位） */
  --gold: #c9a84c;          /* ゴールド（1位のみ） */
  --crimson: #ff2244;       /* クリムゾン（警告・HP） */
  --deep: #050708;          /* 最深背景 */
  --surface: #0b0e0b;       /* 背景 */
  --text: #d4e8cc;          /* テキスト */
}
```

### UIコンセプト
- **格闘ゲームHP バー**：スコアを体力ゲージで表現
- **VTuber配信オーバーレイ**：スキャンライン・LIVE/ON AIRバッジ・スーパーチャットバナー
- **Glassmorphism カード**：半透明ガラスパネル＋ネオングロー
- **Glitch アニメーション**：タイトルのグリッチエフェクト
- **Intersection Observer**：スクロール時のHP バーアニメーション

---

## 主要ページとURL

| URL | ページ |
|---|---|
| `/` | ダッシュボード |
| `/predict-v2?raceName=レース名` | メイン予想結果（v2） |
| `/prediction/paddock` | パドック写真アップロード＆分析 |
| `/prediction/weekly` | 週次パイプライン実行 |
| `/prediction/stats-predict` | 統計ベース予想 |
| `/entry` | 出走馬一覧 |
| `/calendar` | レースカレンダー |
| `/accuracy` | 予想精度トラッキング |
| `/horse/list` | 馬一覧 |
| `/script` | Pythonスクリプト実行UI |
| `/health` | ヘルスチェック |

---

## よく使うコマンド

```bash
# Spring Boot起動
./mvnw spring-boot:run -Dspring-boot.run.jvmArguments="-Dserver.port=8081"

# 予想実行
python3 python/race_specific_analyzer.py "皐月賞" 10
python3 python/race_specific_analyzer.py "春雷S" 10 "春雷ステークス"

# 出走馬取得
python3 python/entry_fetcher.py

# ngrok（外部公開）
ngrok http 8081

# DB接続
psql -h localhost -U postgres -d faceapp

# GitHub
git remote: git@github.com:sy302202502/FacePredictionAppStep4.git
```

---

## 既知の注意点

- llava:7bはOllamaでローカル実行（`ollama serve`が必要）
- netkeibへのスクレイピングは1秒スリープを挟む
- OP/Listed戦はgradeフィルターに`grade[]=4&grade[]=5&grade[]=6`が必要（修正済）
- 分析温度は`temperature=0.5`（多様な結果のため）
- 80頭分析で約30〜40分かかる
- ngrok無料版はMac再起動でURLが変わる
