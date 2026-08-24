#!/usr/bin/env bash
# ============================================================
# full_update.sh — app と python の両イメージを更新して本番へ反映
#
#     cd /opt/faceprediction && git pull && bash deploy/full_update.sh
#
# なぜ python も要るのか:
#   python サービスは ./python のバインドマウントを持たず、コードは
#   Dockerfile.python の COPY でイメージに焼き込まれる。git pull だけでは
#   cron が実行するPythonコードは一切更新されない。
#
# 安全策:
#   - 実行前に現行イメージを :prev タグで退避（ロールバック用）
#   - 何が新しく入るのかを先に一覧表示
#   - cron実行時刻の直前なら警告
#   - health が UP になるまで確認
#
# ロールバック:
#   docker tag faceprediction-python:prev faceprediction-python:latest
#   docker tag faceprediction-app:prev    faceprediction-app:latest
#   docker compose up -d app python
# ============================================================
set -uo pipefail
cd /opt/faceprediction
hr() { echo "=============================================="; }

hr; echo "現在のコミット"; git log --oneline -1

# ── cron衝突の警告 ──────────────────────────────────
MIN=$(date +%-M)
if [ "$MIN" -ge 55 ] || [ "$MIN" -le 3 ]; then
    echo ""
    echo "⚠️  現在 $(date '+%H:%M')。cronは毎時00分に動きます。"
    echo "    コンテナ入れ替え中にジョブが中断される恐れがあります。"
    echo "    毎時10〜50分の間に実行し直すことを推奨します。"
    read -r -p "    それでも続行しますか? [y/N] " ans
    [ "$ans" = "y" ] || { echo "中止しました。"; exit 0; }
fi

# ── これから入る変更の一覧 ───────────────────────────
for svc in app python; do
    img="faceprediction-$svc"
    created=$(docker image inspect "$img" --format '{{.Created}}' 2>/dev/null) || continue
    [ -z "$created" ] && continue
    [ "$svc" = "python" ] && paths="python/" || paths="src/ pom.xml"
    hr; echo "[$svc] 現行イメージ: $created"
    n=$(git log --since="$created" --oneline -- $paths | wc -l | tr -d ' ')
    echo "  これから反映される $svc 関連コミット: ${n}件"
    git log --since="$created" --oneline -- $paths | head -15
done

# ── ロールバック用に現行イメージを退避 ─────────────────
hr; echo "現行イメージを :prev で退避（ロールバック用）"
for svc in app python; do
    docker tag "faceprediction-$svc:latest" "faceprediction-$svc:prev" 2>/dev/null \
        && echo "  faceprediction-$svc:prev を作成" \
        || echo "  faceprediction-$svc: 退避スキップ（イメージなし）"
done

# ── ビルド ───────────────────────────────────────
hr; echo "イメージをビルド（app と python）"
docker compose build app python || { echo "❌ ビルド失敗。コンテナは入れ替えていません。"; exit 1; }

hr; echo "コンテナを入れ替え"
docker compose up -d app python

# ── 起動確認 ─────────────────────────────────────
hr; echo "起動待ち（最大120秒）"
up=0
for i in $(seq 1 24); do
    code=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 5 \
           http://localhost:8081/actuator/health 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then echo "  ✅ app 起動完了（${i}回目）"; up=1; break; fi
    sleep 5
done
[ "$up" = "1" ] || { echo "  ❌ health が UP になりません: docker compose logs --tail=80 app"; exit 1; }

# ── 反映後の動作確認 ──────────────────────────────
hr; echo "netkeibaプレミアムログインの確認（追い切りタイム加点）"
docker compose exec -T python python3 python/check_netkeiba_login.py 2>&1 | tail -12

hr; echo "馬場判定・展開予想モジュールの読み込み確認"
docker compose exec -T python python3 -c "
import sys; sys.path.insert(0,'python')
from race_condition import resolve_condition, place_from_race_id
from pace_analyzer import running_style, predict_pace, pace_adjustment
print('  ✅ race_condition / pace_analyzer 読み込みOK')
print('  馬場解決テスト:', resolve_condition('202602011010','2026-07-12')['condition'])
" 2>&1 | tail -5

hr; echo "完了。問題があればロールバック手順はこのファイル冒頭のコメント参照。"
