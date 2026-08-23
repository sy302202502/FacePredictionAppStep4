#!/usr/bin/env bash
# ============================================================
# image_status.sh — 稼働中イメージの鮮度確認（読み取り専用）
#
#     cd /opt/faceprediction && git pull && bash deploy/image_status.sh
#
# 重要: python サービスは ./python のバインドマウントを持たず、
#       コードは Dockerfile.python の COPY でイメージに焼き込まれる。
#       つまり git pull だけでは cron の実行コードは更新されない。
#       (app サービスも同様にビルドが必要)
# ============================================================
set -u
cd /opt/faceprediction
hr() { echo "=============================================="; }

hr; echo "リポジトリの現在地"
git log --oneline -1

for svc in app python; do
    img="faceprediction-$svc"
    hr; echo "[$svc] イメージ: $img"
    created=$(docker image inspect "$img" --format '{{.Created}}' 2>/dev/null)
    if [ -z "$created" ]; then
        echo "  (イメージなし)"; continue
    fi
    echo "  ビルド日時: $created"
    echo "  経過      : $(docker image inspect "$img" --format '{{.Created}}' \
                        | xargs -I{} date -d {} '+%Y-%m-%d %H:%M' 2>/dev/null)"

    echo "  --- このビルド以降に入った $svc 関連コミット ---"
    if [ "$svc" = "python" ]; then paths="python/"; else paths="src/ pom.xml"; fi
    n=$(git log --since="$created" --oneline -- $paths | wc -l)
    git log --since="$created" --oneline -- $paths | head -20
    [ "$n" -eq 0 ] && echo "    (なし = 最新)" || echo "    → 未反映コミット ${n}件"
done

hr; echo "稼働中コンテナが使っているイメージID"
docker compose ps --format '{{.Service}}\t{{.Image}}\t{{.Status}}' 2>/dev/null \
  || docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'

hr; echo "完了（何も変更していません）"
