#!/usr/bin/env python3
"""
馬の写真（本番の uploads）を、VPS の外（この Mac）へ写す。増えた分・大きさの変わった分だけを取りに行く。

  python3 tools/backup_pull.py            # 既定の保存先へ
  python3 tools/backup_pull.py --dry-run  # 何件・何MB取るかだけ表示
  python3 tools/backup_pull.py --dest <フォルダ> --base <URL>

本番DBは Supabase（クラウド）にあり、VPS に日次のダンプもあるので2か所にある。1か所にしか無いのは写真
（VPS の Docker volume）で、消えると取り直しに netkeiba への大量アクセスが要る。写真は /uploads/** で
公開済みなので、パスワードなしで読める。自分のサーバーへ負荷をかけないよう、1枚ごとに少し待つ。
消えた写真は手元からは消さない（バックアップなので）。
"""
import argparse
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = 'https://160-251-251-73.sslip.io'
DEST = os.path.expanduser('~/舞鬼法師/競馬/バックアップ/写真')
UA = {'User-Agent': 'kigan-backup/1.0'}


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def read_index(base):
    """[(バイト数, 相対パス)]。相対パスは uploads からの位置（例 candidates/2022100994.jpg）"""
    rows = []
    for line in get(base + '/uploads/_index.txt').decode('utf-8').splitlines():
        size, _, rel = line.partition('\t')
        rel = rel.strip()
        # 一覧の外へ書き出さない（.. や絶対パスは受け付けない）
        if not size.isdigit() or not rel or rel.startswith('/') or '..' in rel.split('/'):
            continue
        rows.append((int(size), rel))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=BASE)
    ap.add_argument('--dest', default=DEST)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--wait', type=float, default=0.15, help='1枚ごとの待ち時間（秒）')
    a = ap.parse_args()

    rows = read_index(a.base)
    if not rows:
        print('一覧が空です（本番にまだ反映されていない・写真フォルダが違う可能性）')
        sys.exit(1)
    todo = [(s, rel) for s, rel in rows
            if not (os.path.isfile(os.path.join(a.dest, rel)) and os.path.getsize(os.path.join(a.dest, rel)) == s)]
    total = sum(s for s, _ in rows)
    need = sum(s for s, _ in todo)
    print(f'本番の写真 {len(rows)}枚（{total / 1e6:.0f}MB）／これから取る {len(todo)}枚（{need / 1e6:.0f}MB）→ {a.dest}')
    if a.dry_run or not todo:
        return
    done = failed = 0
    for size, rel in todo:
        path = os.path.join(a.dest, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            data = get(a.base + '/uploads/' + urllib.parse.quote(rel))
            if len(data) != size:
                raise IOError(f'大きさが一覧と違います（{len(data)} / {size}）')
            tmp = path + '.part'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, path)
            done += 1
        except Exception as e:
            failed += 1
            print(f'  取れませんでした: {rel}（{e}）')
        if done and done % 200 == 0:
            print(f'  {done}/{len(todo)}枚')
        time.sleep(a.wait)
    print(f'完了: {done}枚を保存' + (f'・{failed}枚は失敗（次回また試します）' if failed else ''))
    if failed and failed > len(todo) * 0.1:
        sys.exit(1)


if __name__ == '__main__':
    main()
