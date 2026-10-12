"""
night_columns.py — 木曜・金曜・土曜（祝日の月曜開催があれば日曜も）の夜にコラムを作って公開する

  python3 python/night_columns.py --prep            # 18時「データ確定」（出馬表の同期・統計の再計算で今夜の印と材料を確定）
  python3 python/night_columns.py                   # 20時「執筆」（確定したデータで書いて監査）
  python3 python/night_columns.py --retry [--final] # 21時・22時の自動再実行（公開済みは飛ばし、出ていないコラムだけ書く）
  共通: [--mode thu|fri|sat|sun] [--dry-run]
  --mode を省くと実行した曜日で決める（木=thu、金=fri、土=sat、日=sun。それ以外の曜日は何もしない）

  木曜の夜 … 週末（土・日。祝日の月曜開催があれば月も）の重賞の週中コラム（木曜版）
  金曜の夜 … 土曜の重賞の鬼眼コラム（展開図つき）＋ 日曜・月曜の重賞の週中コラム（金曜版）
  土曜の夜 … 日曜の重賞の鬼眼コラム（展開図つき）
  日曜の夜 … 月曜（祝日の3日間開催）の重賞の鬼眼コラム。月曜に開催が無ければ何もしない

手順:
  18時 データ確定 … 出馬表と同期（失敗したレースだけ止める）し、鬼眼コラムのレースは確定した枠順で統計を再計算して
                     印を確定する。結果は night_prep に記録。20時以降はその夜のうちに同期・再計算をしない（印が動かない）
  20時 執筆       … 確定した材料で書く。AI の文章は機械的な検査と AI の校閲に通るまで書き直し、だめならテンプレート文章。
                     書いたらページ監査。週中コラムが通らなければ「傾向だけ」で書き直す
  21時・22時       … 出ていないコラムだけ自動でやり直す（データ確定の失敗もここでやり直す）。22時でもだめなら Discord で知らせる
  Mac の Claude が 21〜23時に投稿セットを用意し、翌朝8時にリマインダーで知らせる（投稿は本人が朝に）
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
    """その週末の開催日の候補（土・日・月）。日曜に実行したときは前日を土曜とする。
    月曜は祝日の3日間開催のときだけレースがある（レース一覧に載っているかで判断する）"""
    if today.weekday() == 6:
        sat = today - timedelta(days=1)
    else:
        sat = today + timedelta(days=(5 - today.weekday()) % 7)
    return sat, sat + timedelta(days=1), sat + timedelta(days=2)


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


PREP_TABLE = """
    CREATE TABLE IF NOT EXISTS night_prep (
        night_date  DATE NOT NULL,
        race_id     VARCHAR(20) NOT NULL,
        race_name   TEXT,
        grade       VARCHAR(4),
        race_date   DATE,
        kind        VARCHAR(8) NOT NULL,      -- week（週中コラム）/ kigan（鬼眼コラム）
        edition     VARCHAR(4),               -- 週中コラムの版 thu / fri
        ok          BOOLEAN NOT NULL,         -- データ確定に成功したか（同期・統計の再計算）
        note        TEXT,
        prepared_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'Asia/Tokyo'),
        PRIMARY KEY (night_date, race_id)
    )
"""


def targets_for(mode, races, sat, sun, mon):
    """その夜に書くコラム → [(race, kind, edition)]"""
    out = []
    for r in races:
        d = r['race_date']
        if mode == 'thu':
            out.append((r, 'week', 'thu'))
        elif mode == 'fri' and d == sat:
            out.append((r, 'kigan', None))
        elif mode == 'fri' and d in (sun, mon):
            out.append((r, 'week', 'fri'))
        elif (mode == 'sat' and d == sun) or (mode == 'sun' and d == mon):
            out.append((r, 'kigan', None))
    return out


def parse_failed(synced, out):
    """entry_fetcher --sync の結果 → 同期に失敗した race_id の集合。同期そのものが落ちた（一覧が読めない）ときは None"""
    if synced:
        return set()
    for line in out or []:
        if line.startswith('FAILED_RACE_IDS:'):
            return {x.strip() for x in line.split(':', 1)[1].split(',') if x.strip()}
    return None


def prep(mode, today, dry, notify=True):
    """18時「データ確定」: 出馬表の同期と統計の再計算をして、今夜のコラムの材料と印を確定する。
    ここで確定した印は、出走取消以外ではその夜のうちに動かさない（20時以降は同期・再計算をしない）。
    何度実行しても安全: 対象を先に「準備中」で全部登録し、確定に成功したレースは二度と再計算しない"""
    sat, sun, mon = weekend(today)
    failed_dates = set()
    weekend_races = [r for r in fetch_upcoming_grade_races(days=max(0, (mon - today).days), failed_dates=failed_dates)
                     if r['race_date'] in (sat, sun, mon)]
    # 今夜の対象日の一覧が1日でも読めなかったら「部分的」。読めた分は進め、読めなかった日は次の回でもう一度見る
    need = {'thu': (sat, sun, mon), 'fri': (sat, sun, mon), 'sat': (sun,), 'sun': (mon,)}[mode]
    partial = bool(failed_dates & set(need))
    if partial and not weekend_races and not dry:
        # 「月曜開催なし」より先に見る（一覧が読めないのを開催なしと取り違えない）
        notify and send_discord("⚠️ **夜のコラム（データ確定）**: 週末のレース一覧が読めませんでした（取得の失敗か、ページの形の変化）。"
                     "このあと自動でやり直します。")
        return 'race_list_empty'
    if mode == 'sun' and not partial and not any(r['race_date'] == mon for r in weekend_races):
        print("月曜の開催が無いので、日曜の夜は何もしない")
        return 'no_monday'
    races = [r for r in weekend_races if r.get('grade_no') in GRADE
             and (mode != 'sun' or r['race_date'] == mon)]
    targets = targets_for(mode, races, sat, sun, mon)
    log(f"データ確定（{mode}）: 今夜のコラム {len(targets)}本 — "
        + '、'.join(f"{r['race_date'].month}/{r['race_date'].day} {r['race_name']}" for r, _, _ in targets))
    if partial and not dry and notify:
        send_discord("⚠️ **夜のコラム（データ確定）**: 週末のレース一覧の一部（"
                     + '・'.join(f"{d.month}/{d.day}" for d in sorted(failed_dates & set(need)))
                     + "）が読めませんでした。読めた分は進め、残りは次の回でもう一度見ます。")
    if not targets:
        return 'race_list_partial' if partial else 'no_targets'   # 本当に今夜書く重賞が無いときだけ静かに終わる
    if dry:
        return 'ok'

    # 1. 対象を全部「準備中」で登録する（途中で落ちても、20時以降に未確定のレースとして拾える）。確定済みの行は残す
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(PREP_TABLE)
    for r, kind, edition in targets:
        cur.execute("""INSERT INTO night_prep (night_date, race_id, race_name, grade, race_date, kind, edition, ok, note)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,FALSE,'準備中') ON CONFLICT (night_date, race_id) DO NOTHING""",
                    (today, r['race_id'], r['race_name'], GRADE[r['grade_no']], r['race_date'], kind, edition))
    conn.commit()
    cur.execute("SELECT race_id FROM night_prep WHERE night_date = %s AND ok", (today,))
    done = {x[0] for x in cur.fetchall()}
    cur.close()
    todo = [t for t in targets if t[0]['race_id'] not in done]
    if not todo:
        conn.close()
        return 'race_list_partial' if partial else 'ok'

    # 2. 出馬表の同期（失敗したレースだけを止める）
    last = max(r['race_date'] for r, _, _ in todo)
    # 今夜書くレースだけを同期する（取得ページを最小に。関係のないレースの失敗で止まらない）
    synced, out = run_script('entry_fetcher.py', ['--sync', '--days', str(max(0, (last - today).days)),
                                                  '--race-ids', ','.join(r['race_id'] for r, _, _ in todo)],
                             '出馬表 同期（今夜の対象だけ）')
    failed_ids = parse_failed(synced, out)

    # 3. レースごとに確定（1レースの例外で残りを止めない）
    lines = []
    for r, kind, edition in todo:
        rid, name = r['race_id'], r['race_name']
        try:
            if failed_ids is None or rid in failed_ids:
                ok, note = False, '出馬表の同期に失敗'
            elif kind == 'kigan' or not has_recent_facts(conn, rid):
                # 鬼眼コラムは確定した枠順で印を確定。週中コラムは近走の事実がそろっていれば再計算しない
                okp, _ = run_script('stats_predictor.py', [rid, '--update'], f'{name} 統計予想（データ確定）')
                ok, note = okp, (None if okp else '統計予想の再計算に失敗')
            else:
                ok, note = True, None
        except Exception as e:
            conn.rollback()
            ok, note = False, f'データ確定でエラー: {e}'[:200]
        try:
            c2 = conn.cursor()
            c2.execute("UPDATE night_prep SET ok = %s, note = %s, prepared_at = NOW() AT TIME ZONE 'Asia/Tokyo' "
                       "WHERE night_date = %s AND race_id = %s", (ok, note, today, rid))
            conn.commit()
            c2.close()
        except Exception:
            conn.rollback()
            conn.close()
            conn = get_conn()
        lines.append(f"・{name}: {'✅' if ok else '⛔ ' + note}")
    conn.close()
    if any('⛔' in l for l in lines) and notify:
        send_discord("🗂 **夜のコラム（データ確定）**\n" + '\n'.join(lines)
                     + "\n⛔ のレースは20時以降も自動でやり直します（22時でもだめなら手動）。")
    return 'race_list_partial' if partial else 'ok'


def published_since(conn, rid, kind, edition, since):
    """since（日本時間の naive datetime）以降に更新されたコラムの (generator, updated_at)。無ければ None"""
    st = column_status(conn, rid, 'week_column' if kind == 'week' else 'race_column', edition)
    return st if st and st[1] and st[1] >= since else None


def published_tonight(conn, rid, kind, edition, today):
    """今夜（今日の17時以降。updated_at は日本時間の naive timestamp）に公開済みで、ページ監査にも通っているか"""
    if not published_since(conn, rid, kind, edition, datetime(today.year, today.month, today.day, 17)):
        return False
    return not column_audit.audit(rid, edition if kind == 'week' else None)


def load_prep(conn, today):
    cur = conn.cursor()
    cur.execute(PREP_TABLE)
    conn.commit()
    cur.execute("""SELECT race_id, race_name, grade, kind, edition, ok, note FROM night_prep
                   WHERE night_date = %s ORDER BY race_date, race_id""", (today,))
    rows = cur.fetchall()
    cur.close()
    return rows


def write_one(conn, rid, name, grade, kind, edition, label):
    """1本書いて監査する → (公開できたか, 結果の文)"""
    started = datetime.now()   # 執筆前の時刻。これより後に更新されていなければ「今回は公開できていない」
    if kind == 'week':
        args = [rid, '--grade', grade, '--edition', edition, '--force']
        okw, _ = run_script('week_column.py', args, f'{name} {label}')
        rewrite = lambda: run_script('week_column.py', args + ['--trends-only'], f'{name} 週中コラム（傾向だけで書き直し）')
    else:
        args = [rid, '--grade', grade, '--force']
        okw, _ = run_script('column_writer.py', args, f'{name} 鬼眼コラム')
        rewrite = lambda: run_script('column_writer.py', args, f'{name} 鬼眼コラム（書き直し）')
    # 監査に通らなければ書き直し（週中コラムは「傾向だけ」）。それでもだめなら取り下げ
    passed, problems = column_audit.enforce(conn, rid, edition if kind == 'week' else None, rewrite, log)
    st = published_since(conn, rid, kind, edition, started) if passed else None
    if st:
        return True, f"・{name}（{grade}）{label}: " + ('AIの文章' if st[0] != 'template' else 'テンプレートの文章') + '・ページ監査に合格'
    why = ' / '.join(problems) if problems else ('執筆に失敗' if not okw else '今回の更新が見当たらない')
    return False, f"・{name}（{grade}）{label}: ⛔ {why}"


def write(mode, today, retry, final):
    """20時の執筆・21時/22時の自動再実行。確定済みの材料で書くだけ（同期・印の再計算はしない）。
    公開済みで監査に通っているコラムは飛ばすので、何度実行しても同じコラムを二重に書かない"""
    # 毎回まずデータ確定を通す（何度実行しても安全。確定済みのレースは何もしない。18時に一覧が読めなかった・
    # 途中で落ちた・あとから一覧に出たレースもここで拾う）
    st = prep(mode, today, False, notify=final)   # 途中の回は個別に知らせず、最後のまとめ（Discord）で知らせる
    if st in ('no_monday', 'no_targets'):
        print(f'RESULT:{{"success": true, "skipped": "{st}"}}')
        return 0
    conn = get_conn()
    rows = load_prep(conn, today)
    if not rows:
        conn.close()
        if final:
            send_discord("⛔ **夜のコラム**: 今夜のデータ確定ができず、コラムを作れませんでした。"
                         "/jobs のログを確認し、手動で夜のコラムを実行してください。")
            return 1
        print(f'RESULT:{{"success": false, "prep": "{st}"}}')
        return 1 if st == 'race_list_empty' else 0

    report, missing = [], []
    if st == 'race_list_partial' and final:
        missing.append("・⚠️ 週末のレース一覧の一部が読めず、重賞を取りこぼしている可能性があります")
    for rid, name, grade, kind, edition, ok, note in rows:
        label = f"週中コラム（{'木曜版' if edition == 'thu' else '金曜版'}）" if kind == 'week' else '鬼眼コラム（展開図つき）'
        try:
            if published_tonight(conn, rid, kind, edition, today):
                continue
            if not ok:
                missing.append(f"・{name}（{grade}）{label}: ⛔ {note}")
                continue
            done, line = write_one(conn, rid, name, grade, kind, edition, label)
            (report if done else missing).append(line)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                conn = get_conn()
            missing.append(f"・{name}（{grade}）{label}: ⛔ エラー: {e}"[:300])
    conn.close()

    when = '22時の最終やり直し' if final else ('21時のやり直し' if retry else '20時')
    if report or (missing and (final or not retry)):
        msg = f"🌙 **夜のコラム（{when}）**\n" + '\n'.join(report + missing)
        if missing and not final:
            msg += "\n⛔ のコラムは、このあと自動でやり直します。"
        elif missing:
            msg += "\n⛔ のコラムは自動では作れませんでした。/jobs のログを確認し、手動で夜のコラムを実行してください。"
        else:
            msg += "\nMac の Claude が最終確認をして投稿セットを用意し、翌朝8時にリマインダーで知らせます。"
        send_discord(msg)
    print(f'RESULT:{{"success": {"true" if not missing else "false"}, "published": {len(report)}, "missing": {len(missing)}}}')
    return 1 if (missing and final) else 0


def single_run():
    """同じコンテナで夜のコラムが同時に2つ動かないようにする（20時の執筆が長引いて21時のやり直しと重なる、など）。
    取れなければ None（前の実行が続いている）"""
    import fcntl
    f = open('/tmp/night_columns.lock', 'w')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def main():
    dry = '--dry-run' in sys.argv
    lock = None if dry else single_run()
    if not dry and lock is None and '--final' in sys.argv:
        # 22時の最終やり直しは、前の回が終わるのを最大45分待つ（ここで飛ばすと「作れなかった」通知が出ない）
        import time
        for _ in range(90):   # 最大45分（job_runner の上限3時間の範囲内）
            time.sleep(30)
            lock = single_run()
            if lock:
                break
        if lock is None:
            send_discord("⛔ **夜のコラム（22時の最終やり直し）**: 前の回の実行が45分以上続いていて、最終確認ができませんでした。"
                         "/jobs のログを確認し、終わったら手動で夜のコラムを実行してください。")
            print('RESULT:{"success": false, "reason": "previous_run_still_running"}')
            sys.exit(1)
    if not dry and lock is None:
        print("前の夜のコラムの実行がまだ続いているので、今回は何もしない（次の回で拾う）")
        print('RESULT:{"success": true, "skipped": "running"}')
        return
    today = datetime.now().date()
    mode = sys.argv[sys.argv.index('--mode') + 1] if '--mode' in sys.argv else \
        {3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}.get(today.weekday())
    if mode not in ('thu', 'fri', 'sat', 'sun'):
        print("夜のコラムは木・金・土・日だけ（--mode で指定可）")
        print('RESULT:{"success": true, "skipped": "not_night"}')
        return
    if '--prep' in sys.argv or dry:
        st = prep(mode, today, dry)
        print(f'RESULT:{{"success": {"true" if st in ("ok", "no_monday", "no_targets") else "false"}, "prep": "{st}"}}')
        if st not in ('ok', 'no_monday', 'no_targets'):
            sys.exit(1)
        return
    rc = write(mode, today, '--retry' in sys.argv, '--final' in sys.argv)
    if rc:
        sys.exit(rc)


if __name__ == '__main__':
    main()
