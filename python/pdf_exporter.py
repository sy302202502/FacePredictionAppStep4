"""
pdf_exporter.py
競馬顔面予想 PDF出力スクリプト

使い方:
  python pdf_exporter.py "レース名" /path/to/output.pdf
  python pdf_exporter.py "レース名"   # 標準出力にバイナリ出力
"""

import sys
import os
import json
import io
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras

# reportlab
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image as RLImage
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ─────────────────────────────────────────────
# 日本語フォント登録
# ─────────────────────────────────────────────
FONT_PATHS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode MS.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

def register_japanese_font():
    """利用可能な日本語フォントを登録する"""
    for path in FONT_PATHS:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("JpFont", path))
                return "JpFont"
            except Exception:
                continue
    # フォールバック: reportlab 組み込みフォント
    return "Helvetica"

FONT_NAME = register_japanese_font()


# ─────────────────────────────────────────────
# DB 接続
# ─────────────────────────────────────────────
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "faceapp"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgrestest"),
    )


# ─────────────────────────────────────────────
# DB からデータ取得
# ─────────────────────────────────────────────
def fetch_predictions(race_name: str):
    """予想結果を取得"""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT horse_name, horse_id, image_path,
                       similarity_score, diff_score, final_score,
                       rank_position, race_category, target_race_date,
                       analysis_detail
                FROM prediction_result
                WHERE target_race_name = %s
                ORDER BY rank_position ASC
            """, (race_name,))
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_stats_summary(race_name: str):
    """予想に使った統計の簡易サマリーを取得"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM horse_face_feature WHERE finish_rank = 1"
            )
            winner_count = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM horse_face_feature WHERE finish_rank > 1"
            )
            loser_count = cur.fetchone()[0]
        return winner_count, loser_count
    finally:
        conn.close()


# ─────────────────────────────────────────────
# PDF 生成
# ─────────────────────────────────────────────
def rank_color(rank: int):
    if rank == 1:
        return colors.HexColor("#FFD700")   # 金
    elif rank == 2:
        return colors.HexColor("#C0C0C0")   # 銀
    elif rank == 3:
        return colors.HexColor("#CD7F32")   # 銅
    else:
        return colors.HexColor("#6c757d")


def score_bar_table(score: float, max_width_pt: float = 120):
    """スコアバーを TableStyle で描画"""
    filled = max(0, min(score or 0, 100)) / 100 * max_width_pt
    empty = max_width_pt - filled
    data = [[""]]
    t = Table(data, colWidths=[max_width_pt], rowHeights=[8])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#e0e0e0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def build_score_bar(score: float, max_width_pt: float = 120):
    """スコアバーを段組みで表現"""
    filled_w = max(0, min(score or 0, 100)) / 100 * max_width_pt
    empty_w = max_width_pt - filled_w
    rows = [[""]]
    cols = []
    if filled_w > 0:
        cols.append(filled_w)
    if empty_w > 0:
        cols.append(empty_w)
    if not cols:
        cols = [max_width_pt]

    t = Table([[""]*len(cols)], colWidths=cols, rowHeights=[8])
    style = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("GRID", (0, 0), (-1, -1), 0, colors.white),
    ]
    if filled_w > 0:
        style.append(("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#4caf50")))
    if empty_w > 0 and len(cols) > 1:
        style.append(("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#e0e0e0")))
    elif empty_w > 0:
        style.append(("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#e0e0e0")))
    t.setStyle(TableStyle(style))
    return t


def make_horse_image(image_path: str, width_pt: float = 60, height_pt: float = 45):
    """馬の顔画像を RLImage で返す。存在しなければ None"""
    if not image_path:
        return None
    # DB 保存パスは /uploads/horses/xxx.jpg や /uploads/candidates/xxx.jpg 形式
    upload_base = Path(os.getenv("UPLOAD_BASE", str(Path.home() / "faceapp")))
    # image_path の先頭 "/" を除去して結合（サブディレクトリ構造を保持）
    relative = image_path.lstrip("/")
    full_path = upload_base / relative
    if not full_path.exists():
        return None
    try:
        img = RLImage(str(full_path), width=width_pt, height=height_pt)
        img.preserveAspectRatio = True
        return img
    except Exception:
        return None


def generate_pdf(race_name: str, output_path: str = None) -> bytes:
    """
    PDF を生成して bytes を返す。
    output_path が指定された場合はファイルにも書き出す。
    """
    predictions = fetch_predictions(race_name)
    winner_count, loser_count = fetch_stats_summary(race_name)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    # ─── スタイル ───
    base_style = ParagraphStyle(
        "Base",
        fontName=FONT_NAME,
        fontSize=10,
        leading=14,
    )
    title_style = ParagraphStyle(
        "Title",
        fontName=FONT_NAME,
        fontSize=18,
        leading=24,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1a237e"),
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        fontName=FONT_NAME,
        fontSize=11,
        leading=16,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
    )
    rank_style = ParagraphStyle(
        "Rank",
        fontName=FONT_NAME,
        fontSize=22,
        leading=28,
        alignment=TA_CENTER,
        textColor=colors.white,
    )
    horse_name_style = ParagraphStyle(
        "HorseName",
        fontName=FONT_NAME,
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#1a1a1a"),
    )
    score_label_style = ParagraphStyle(
        "ScoreLabel",
        fontName=FONT_NAME,
        fontSize=8,
        leading=12,
        textColor=colors.HexColor("#666666"),
    )
    score_val_style = ParagraphStyle(
        "ScoreVal",
        fontName=FONT_NAME,
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#222222"),
    )
    footer_style = ParagraphStyle(
        "Footer",
        fontName=FONT_NAME,
        fontSize=8,
        leading=12,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#999999"),
    )
    caption_style = ParagraphStyle(
        "Caption",
        fontName=FONT_NAME,
        fontSize=8,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#888888"),
    )

    story = []

    # ─── タイトル ───
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("競馬顔面予想システム", subtitle_style))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(race_name, title_style))
    story.append(Spacer(1, 1 * mm))

    race_date = ""
    if predictions:
        d = predictions[0].get("target_race_date")
        if d:
            race_date = str(d)
    if race_date:
        story.append(Paragraph(f"レース日: {race_date}", subtitle_style))

    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a237e")))
    story.append(Spacer(1, 4 * mm))

    # ─── 統計サマリー ───
    category = predictions[0].get("race_category", "不明") if predictions else "不明"
    summary_data = [
        [
            Paragraph("分析勝ち馬数", score_label_style),
            Paragraph("分析敗退馬数", score_label_style),
            Paragraph("レース種別", score_label_style),
            Paragraph("予想頭数", score_label_style),
        ],
        [
            Paragraph(f"{winner_count} 頭", score_val_style),
            Paragraph(f"{loser_count} 頭", score_val_style),
            Paragraph(str(category), score_val_style),
            Paragraph(f"{len(predictions)} 頭", score_val_style),
        ],
    ]
    summary_table = Table(summary_data, colWidths=[40 * mm] * 4)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eaf6")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROUNDEDCORNERS", [4]),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 6 * mm))

    # ─── 各馬カード ───
    if not predictions:
        story.append(Paragraph("予想データがありません。", base_style))
    else:
        for pred in predictions:
            rank = pred.get("rank_position", 0)
            horse_name = pred.get("horse_name", "不明")
            sim_score = pred.get("similarity_score") or 0.0
            diff_score = pred.get("diff_score") or 0.0
            final_score = pred.get("final_score") or 0.0
            image_path = pred.get("image_path")

            rc = rank_color(rank)

            # ランクバッジセル
            rank_cell = Table(
                [[Paragraph(str(rank), rank_style)]],
                colWidths=[14 * mm],
                rowHeights=[14 * mm],
            )
            rank_cell.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), rc),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
                ("ROUNDEDCORNERS", [7]),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))

            # 画像セル
            img = make_horse_image(image_path, width_pt=55, height_pt=42)
            if img is None:
                img = Paragraph("画像なし", caption_style)

            # スコアセル
            score_items = [
                Paragraph(f"総合スコア: {final_score:.1f} pt", horse_name_style),
                Spacer(1, 1 * mm),
                Paragraph("総合", score_label_style),
                build_score_bar(final_score, max_width_pt=110),
                Spacer(1, 1 * mm),
                Paragraph("類似度", score_label_style),
                build_score_bar(sim_score, max_width_pt=110),
                Spacer(1, 1 * mm),
                Paragraph("差分スコア", score_label_style),
                build_score_bar(diff_score, max_width_pt=110),
                Spacer(1, 1 * mm),
                Paragraph(
                    f"類似度 {sim_score:.1f}  /  差分 {diff_score:.1f}  /  総合 {final_score:.1f}",
                    score_label_style
                ),
            ]

            # カードの行データ: [ランク, 画像, 馬名+スコア]
            card_inner = Table(
                [[rank_cell, img, score_items]],
                colWidths=[16 * mm, 18 * mm, None],
                rowHeights=[None],
            )
            card_inner.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))

            # 馬名ヘッダー + カード
            horse_header = Table(
                [[Paragraph(horse_name, horse_name_style)]],
                colWidths=["100%"],
            )
            horse_header.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f5f5")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))

            # 外枠カード
            card = Table(
                [[horse_header], [card_inner]],
                colWidths=["100%"],
            )
            card.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.8,
                 colors.HexColor("#FFD700") if rank == 1
                 else colors.HexColor("#C0C0C0") if rank == 2
                 else colors.HexColor("#CD7F32") if rank == 3
                 else colors.HexColor("#dddddd")),
                ("ROUNDEDCORNERS", [4]),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))

            story.append(card)
            story.append(Spacer(1, 3 * mm))

    # ─── フッター ───
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 2 * mm))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    story.append(Paragraph(
        f"生成日時: {now_str}  /  競馬顔面予想システム",
        footer_style,
    ))

    doc.build(story)
    pdf_bytes = buf.getvalue()

    if output_path:
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

    return pdf_bytes


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_exporter.py 'レース名' [/path/to/output.pdf]", file=sys.stderr)
        sys.exit(1)

    race_name = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) >= 3 else None

    pdf_bytes = generate_pdf(race_name, output_path)

    if output_path:
        print(f"PDF を保存しました: {output_path}", file=sys.stderr)
    else:
        # Java から呼ばれる場合は stdout にバイナリ出力
        sys.stdout.buffer.write(pdf_bytes)
