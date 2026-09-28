#!/usr/bin/env bash
# ============================================================
# enable_https.sh — 独自ドメインなしで HTTPS 化する（無料）
#
#     cd /opt/faceprediction && git pull && sudo bash deploy/enable_https.sh
#
# ・ホスト名は <IPのドットをハイフンに>.sslip.io（例: 160-251-251-73.sslip.io）。
#   sslip.io は名前に含まれる IP をそのまま返す無料の DNS サービスで、登録は不要。
# ・Caddy が Let's Encrypt の証明書を自動で取得・更新する（80番と443番が外から届く必要あり）。
# ・既存の http://<IP>:8081 はこのスクリプトでは閉じない（HTTPS の動作を確認してから別途閉じる）。
# ・80番を Caddy 以外が使っている場合は、何も変更せずに中止する。
# ・元の Caddyfile は /etc/caddy/Caddyfile.bak.<日時> に退避する。
# ============================================================
set -u
cd "$(dirname "$0")/.." || exit 1

hr() { echo "=============================================="; }
IP=$(curl -s -4 --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
HOST="${IP//./-}.sslip.io"
hr; echo "公開IP: $IP → ホスト名: $HOST"

# ── 1. 80/443 番の使用状況 ──────────────────────────
hr; echo "80/443番ポートの使用状況"
ss -ltnp 2>/dev/null | grep -E ':(80|443)\s' || echo "  （待ち受けなし）"
if ss -ltnp 2>/dev/null | grep -E ':(80|443)\s' | grep -vq caddy; then
    echo "❌ 80/443番を Caddy 以外が使っています。上の表示を送ってください（何も変更していません）"
    exit 1
fi
# 80番をアプリへ転送する設定（iptables）があると、証明書取得の通信が横取りされる
if iptables -t nat -S 2>/dev/null | grep -E -- '--dport (80|443)\b' | grep -vq DOCKER; then
    echo "❌ 80/443番の転送設定（iptables）があります。次の表示を送ってください（何も変更していません）:"
    iptables -t nat -S | grep -E -- '--dport (80|443)\b'
    exit 1
fi

# ── 2. Caddy のインストール ─────────────────────────
if ! command -v caddy >/dev/null 2>&1; then
    hr; echo "Caddy をインストール"
    apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https curl gnupg >/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q >/dev/null && apt-get install -y -q caddy >/dev/null || { echo "❌ Caddy のインストールに失敗"; exit 1; }
fi
echo "  Caddy: $(caddy version | head -1)"

# ── 3. Caddyfile ────────────────────────────────────
hr; echo "Caddyfile を設定"
[ -f /etc/caddy/Caddyfile ] && cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%Y%m%d%H%M%S)"
cat > /etc/caddy/Caddyfile <<EOF
# faceprediction: deploy/enable_https.sh が生成（手で編集した場合は再実行で上書きされる）
$HOST {
    encode gzip
    reverse_proxy localhost:8081
    header {
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }
}

# IP 直打ちの http は HTTPS のホスト名へ転送
http://$IP {
    redir https://$HOST{uri} permanent
}
EOF
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
    || { echo "❌ Caddyfile の検証に失敗（元に戻すには .bak をコピー）"; caddy validate --config /etc/caddy/Caddyfile; exit 1; }

# ── 4. ファイアウォール ─────────────────────────────
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
    echo "  ufw: 80/443 を許可"
fi

# ── 5. 起動と証明書取得 ─────────────────────────────
hr; echo "Caddy を起動（証明書の取得に最大2分）"
systemctl enable caddy >/dev/null 2>&1
systemctl restart caddy
ok=0
for i in $(seq 1 24); do
    if curl -sf --max-time 5 -o /dev/null "https://$HOST/actuator/health"; then ok=1; break; fi
    sleep 5
done
if [ "$ok" != "1" ]; then
    echo "❌ https://$HOST に接続できません。Caddy のログ:"
    journalctl -u caddy -n 25 --no-pager | tail -25
    echo "（ConoHa のセキュリティグループで 443番が閉じている可能性があります）"
    exit 1
fi
echo "  ✅ https://$HOST で動作しています（証明書: Let's Encrypt）"

# ── 6. 通知・X投稿案の URL を HTTPS に ──────────────
hr; echo "通知・X投稿案の URL を HTTPS に切り替え"
if grep -q '^APP_PUBLIC_URL=' .env; then
    sed -i "s|^APP_PUBLIC_URL=.*|APP_PUBLIC_URL=https://$HOST|" .env
else
    echo "APP_PUBLIC_URL=https://$HOST" >> .env
fi
docker compose up -d python app >/dev/null 2>&1 && echo "  ✅ APP_PUBLIC_URL=https://$HOST"

hr
echo "完了。これからはこのURLを使ってください:"
echo "  https://$HOST/predict-v2"
echo "（http://$IP:8081 もまだ使えます。HTTPS で問題が無いのを確認したら閉じる手順をご案内します）"
