"""
night_columns.py — 木曜・金曜・土曜の夜（20時）にコラムを作って公開する

  python3 python/night_columns.py [--mode thu|fri|sat] [--dry-run]
  --mode を省くと実行した曜日で決める（木=thu、金=fri、土=sat。それ以外の曜日は何もしない）

  木曜の夜 … 週末（土・日）の重賞の週中コラム（木曜版）
  金曜の夜 … 土曜の重賞の鬼眼コラム（展開図つき）＋ 日曜の重賞の週中コラム（金曜版）
  土曜の夜 … 日曜の重賞の鬼眼コラム（展開図つき）

手順（レースごと）:
  1. 出馬表と同期する（entry_fetcher --sync。1レース1ページ。回避馬を外し、頭数・枠を最新に）
  2. 週中コラムの材料（近走の事実）が無ければ統計予想を再評価して保存する
  3. コラムを書く。AI の文章は 機械的な検査 と AI の校閲 の両方に通るまで書き直し、通らなければテンプレート文章
  4. Discord に公開したコラムの一覧と検査の結果を送る
夜に公開した鬼眼コラムは、レース当日の朝には書き直さない（X に載せた画像と食い違わないように。
weekly_pipeline 側でも、鬼眼コラムのある重賞は直前再評価・コラムの書き直しをしない）。
出走取消で出走馬が変わったときだけは、予想の作り直しと一緒にコラムも書き直される（predict_by_race_id）。
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

import column_audit
from weekly_pipeline import (fetch_upcoming_grade_races, get_conn, has_recent_facts, log, run_script,
                             send_discord)

GRADE = {1: 'G1', 2: 'G2', 3: 'G3'}


def weekend(today):
    """その週の土曜・日曜の日付"""
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    return sat, sat + timedelta(days=1)


def column_status(conn, race_id, table, edition=None):
    """公開したコラムの状態（文章の作り手・更新時刻）。無ければ None"""
    cur = conn.cursor()
    try:
        if table == 'week_column':
            cur.execute("SELECT generator, updated_at FROM week_column WHERE race_id = %s AND edition = %s",
                        (race_id, edition))
        else:
            cur.execute("SELECT generator, updated_at FROM race_column WHERE race_id = %s", (race_id,))
        return cur.fetchone()
    except Exception:
        conn.rollback()
        return None
    finally:
        cur.close()


def main():
    dry = '--dry-run' in sys.argv
    today = datetime.now().date()
    mode = sys.argv[sys.argv.index('--mode') + 1] if '--mode' in sys.argv else \
        {3: 'thu', 4: 'fri', 5: 'sat'}.get(today.weekday())
    if mode not in ('thu', 'fri', 'sat'):
        print("夜のコラムは木・金・土だけ（--mode で指定可）")
        print('RESULT:{"success": true, "skipped": "not_night"}')
        return
    sat, sun = weekend(today)
    weekend_races = [r for r in fetch_upcoming_grade_races(days=(sun - today).days) if r['race_date'] in (sat, sun)]
    races = [r for r in weekend_races if r.get('grade_no') in GRADE]
    log(f"夜のコラム（{mode}）: 対象の重賞 {len(races)}件 — "
        + '、'.join(f"{r['race_date'].month}/{r['race_date'].day} {r['race_name']}" for r in races))
    if not weekend_races and not dry:
        # 週末の重賞・OP・リステッドが1件も読めないのは「重賞が無い週」ではなく、レース一覧の取得失敗とみなす
        # （中央競馬の開催週には必ずオープン以上のレースがある）。成功扱いにして見逃さない
        send_discord("⚠️ **夜のコラム**: 週末のレース一覧が読めませんでした（取得の失敗か、ページの形の変化）。"
                     "コラムは作っていません。/jobs のログを確認してください。")
        print('RESULT:{"success": false, "reason": "race_list_empty"}')
        sys.exit(1)
    if dry or not races:
        print(f'RESULT:{{"success": true, "races": {len(races)}}}')
        return

    # 1. 出馬表と同期（今日から日曜まで）。回避馬を外し、変わったレースは予想を作り直す
    synced, _ = run_script('entry_fetcher.py', ['--sync', '--days', str((sun - today).days)], '出馬表 同期')
    if not synced and mode != 'thu':
        # 金・土の夜は出走馬（取消・頭数・枠）が確定している前提でコラムを書くので、同期に失敗したら書かない。
        # 公開済みのコラムはそのまま残す（古い出走表で書き直さない）。木曜の週中コラムは登録馬で書くので続ける
        send_discord("⛔ **夜のコラム**: 出馬表の同期に失敗したため、今夜のコラムは作っていません"
                     "（公開済みのコラムはそのまま）。/jobs のログを確認し、直ったら夜のコラムを手動で実行してください。")
        print('RESULT:{"success": false, "reason": "sync_failed"}')
        sys.exit(1)
    if not synced:
        log("  ⚠️ 出馬表の同期に失敗（木曜は登録馬で週中コラムを書くので続行）")

    conn = get_conn()
    report, fails = [], 0
    for r in races:
        rid, name, grade = r['race_id'], r['race_name'], GRADE[r['grade_no']]
        if mode == 'thu' or (mode == 'fri' and r['race_date'] == sun):
            edition = 'thu' if mode == 'thu' else 'fri'
            if not has_recent_facts(conn, rid):
                run_script('stats_predictor.py', [rid, '--update'], f'{name} 統計予想（近走の事実を保存）')
            args = [rid, '--grade', grade, '--edition', edition, '--force']
            ok, _ = run_script('week_column.py', args, f'{name} 週中コラム（{edition}）')
            passed, problems = column_audit.enforce(conn, rid, edition,
                                                     lambda: run_script('week_column.py', args, f'{name} 週中コラム（書き直し）'), log)
            st = column_status(conn, rid, 'week_column', edition) if passed else None
            kind = f"週中コラム（{'木曜版' if edition == 'thu' else '金曜版'}）"
        elif (mode == 'fri' and r['race_date'] == sat) or (mode == 'sat' and r['race_date'] == sun):
            args = [rid, '--grade', grade, '--force']
            ok, _ = run_script('column_writer.py', args, f'{name} 鬼眼コラム')
            passed, problems = column_audit.enforce(conn, rid, None,
                                                     lambda: run_script('column_writer.py', args, f'{name} 鬼眼コラム（書き直し）'), log)
            st = column_status(conn, rid, 'race_column') if passed else None
            kind = '鬼眼コラム（展開図つき）'
        else:
            continue
        fails += 0 if (ok and st) else 1
        how = (('AIの文章' if st[0] != 'template' else 'テンプレートの文章') + '・ページ監査に合格') if st \
            else ('⛔ 監査に通らず公開を取り下げ: ' + ' / '.join(problems) if problems else '公開できず')
        report.append(f"・{name}（{grade}）{kind}: {how}")
    conn.close()

    send_discord("🌙 **夜のコラムを公開しました**\n" + '\n'.join(report)
                 + "\n21時ごろ、Mac の Claude が最終確認をして X の下書きを作ります。")
    print(f'RESULT:{{"success": {"true" if fails == 0 else "false"}, "published": {len(report) - fails}, "fails": {fails}}}')
    if fails:
        sys.exit(1)


if __name__ == '__main__':
    main()
