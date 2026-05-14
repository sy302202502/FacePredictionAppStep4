#!/usr/bin/env bash
# ============================================================
# setup_oci_vm.sh
# Oracle Cloud Ampere A1 (Ubuntu 22.04 ARM64) 初期セットアップ
#
# 使い方（VM上で実行）:
#   curl -fsSL https://raw.githubusercontent.com/[user]/[repo]/master/deploy/setup_oci_vm.sh | bash
#   または: bash deploy/setup_oci_vm.sh
# ============================================================
set -euo pipefail

echo "======================================================"
echo "  FacePrediction OCI VM セットアップ"
echo "  OS: $(lsb_release -ds 2>/dev/null || echo 'unknown')"
echo "  Arch: $(uname -m)"
echo "======================================================"

# ── 1. 基本パッケージ ─────────────────────────────────────────
echo ""
echo "[1/7] システム更新 + 基本パッケージ..."
sudo apt-get update -q
sudo apt-get install -y -q \
  curl wget git unzip \
  ca-certificates gnupg \
  python3 python3-pip python3-venv \
  libpq-dev \
  ufw fail2ban \
  cron

# ── 2. Docker インストール ────────────────────────────────────
echo ""
echo "[2/7] Docker インストール..."
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  echo "  → Docker インストール完了 (再ログインで有効)"
else
  echo "  → Docker 既にインストール済み: $(docker --version)"
fi

# docker compose plugin
if ! docker compose version &>/dev/null; then
  sudo apt-get install -y -q docker-compose-plugin
fi
echo "  → docker compose: $(docker compose version)"

# ── 3. Caddy インストール（HTTPS リバースプロキシ） ────────────
echo ""
echo "[3/7] Caddy インストール..."
if ! command -v caddy &>/dev/null; then
  sudo apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -q && sudo apt-get install -y -q caddy
fi
echo "  → Caddy: $(caddy version)"

# ── 4. ファイアウォール設定 ────────────────────────────────────
echo ""
echo "[4/7] ファイアウォール設定..."
sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp    # HTTP (Caddy が HTTPS にリダイレクト)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw --force enable
echo "  → UFW 設定完了"

# ── 5. アプリディレクトリ作成 ─────────────────────────────────
echo ""
echo "[5/7] アプリディレクトリ作成..."
sudo mkdir -p /opt/faceprediction/uploads
sudo chown -R "$USER:$USER" /opt/faceprediction
echo "  → /opt/faceprediction 作成完了"

# ── 6. fail2ban（SSH ブルートフォース対策） ───────────────────
echo ""
echo "[6/7] fail2ban 設定..."
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
echo "  → fail2ban 起動完了"

# ── 7. cron（Python スクリプト定期実行） ─────────────────────
echo ""
echo "[7/7] cron スケジュール設定..."
CRON_FILE="/etc/cron.d/faceprediction"
sudo tee "$CRON_FILE" > /dev/null <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin

# オッズ取得: 土日 9:00〜15:00 に30分おき
*/30 9-15 * * 6,0 ubuntu cd /opt/faceprediction && docker compose run --rm python python python/odds_fetcher.py >> /opt/faceprediction/logs/odds.log 2>&1

# 週次パイプライン: 毎週月曜 6:00（レース翌日に結果記録）
0 6 * * 1 ubuntu cd /opt/faceprediction && docker compose run --rm python python python/result_auto_fetcher.py >> /opt/faceprediction/logs/result.log 2>&1

# DBバックアップ: 毎日 3:00
0 3 * * * ubuntu bash /opt/faceprediction/deploy/backup.sh >> /opt/faceprediction/logs/backup.log 2>&1
CRON
sudo chmod 644 "$CRON_FILE"
mkdir -p /opt/faceprediction/logs
echo "  → cron 設定完了"

echo ""
echo "======================================================"
echo "  セットアップ完了！"
echo ""
echo "  次のステップ:"
echo "  1. /opt/faceprediction にリポジトリを clone"
echo "     git clone https://github.com/[user]/[repo].git /opt/faceprediction"
echo ""
echo "  2. .env ファイルを作成"
echo "     cp .env.example .env && vi .env"
echo ""
echo "  3. Caddyfile を設定（deploy/Caddyfile をコピー）"
echo "     sudo cp deploy/Caddyfile /etc/caddy/Caddyfile"
echo "     sudo systemctl reload caddy"
echo ""
echo "  4. アプリを起動"
echo "     docker compose up -d app"
echo ""
echo "  ※ 再ログインしてから docker コマンドを使用してください"
echo "======================================================"
