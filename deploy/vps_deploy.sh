#!/usr/bin/env bash
# ============================================================
# vps_deploy.sh — VPS本番へのアプリ再デプロイ（appコンテナのみ）
#
# 【使い方】ConoHa VNCコンソールは1回の送信が約130文字までのため、
#   下の1行だけ打てば済むようにこのスクリプトに手順をまとめてある。
#
#     cd /opt/faceprediction && git pull && bash deploy/vps_deploy.sh
#
# python コンテナ（cron実行環境）は触らない。Pythonスクリプトは
# ./python がボリュームマウントなので git pull だけで反映される。
# ============================================================
set -euo pipefail

cd /opt/faceprediction

echo "── 現在のコミット ──"
git log --oneline -1

echo "── app イメージをビルド ──"
docker compose build app

echo "── app コンテナを入れ替え ──"
docker compose up -d app

echo "── 起動待ち（最大120秒）──"
for i in $(seq 1 24); do
    code=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 5 \
           http://localhost:8081/actuator/health 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then
        echo "✅ 起動完了（${i}回目のチェックでUP）"
        exit 0
    fi
    sleep 5
done

echo "❌ 120秒以内に health が UP になりませんでした。ログを確認してください:"
echo "   docker compose logs --tail=80 app"
exit 1
