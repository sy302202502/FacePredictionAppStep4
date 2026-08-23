#!/usr/bin/env bash
# ============================================================
# ssh_unban.sh — SSH接続不可の原因切り分け＋指定IPのban解除
#
# 【使い方】VNCコンソールで下の1行（IPは解除したい接続元）
#     cd /opt/faceprediction && git pull && bash deploy/ssh_unban.sh 58.85.64.83
#
# 症状: ポート22はopenなのに、SSHのバージョン交換前に
#       "Connection reset by peer" で切断される。
# 原因候補: (1)fail2ban ban (2)hosts.deny (3)sshd未起動/設定
#           (4)sshdの同時接続数制限
#
# 引数のIPだけを対象に解除する。他のbanされたIP（攻撃者）は触らない。
# ============================================================
set -u

TARGET="${1:-}"
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

hr() { echo "=============================================="; }

hr; echo "[1] sshd プロセス"
$SUDO systemctl is-active ssh 2>/dev/null || $SUDO systemctl is-active sshd 2>/dev/null || echo "  (systemctl判定不可)"
$SUDO ss -lntp 2>/dev/null | grep -E ':22\s' || echo "  ⚠ ポート22でLISTENしているプロセスが見つからない"

hr; echo "[2] fail2ban"
if command -v fail2ban-client >/dev/null 2>&1; then
    $SUDO systemctl is-active fail2ban 2>/dev/null || true
    $SUDO fail2ban-client status 2>/dev/null || echo "  (status取得不可)"
    echo "--- sshd jail ---"
    $SUDO fail2ban-client status sshd 2>/dev/null || echo "  (sshd jail なし)"
else
    echo "  fail2ban 未インストール → 原因はfail2banではない"
fi

hr; echo "[3] hosts.deny / hosts.allow"
grep -vE '^\s*(#|$)' /etc/hosts.deny 2>/dev/null || echo "  hosts.deny: 実質空"
grep -vE '^\s*(#|$)' /etc/hosts.allow 2>/dev/null || echo "  hosts.allow: 実質空"

hr; echo "[4] sshd の接続数制限"
$SUDO sshd -T 2>/dev/null | grep -E '^(maxstartups|maxsessions|persourcemaxstartups)' \
    || grep -iE '^\s*MaxStartups' /etc/ssh/sshd_config 2>/dev/null \
    || echo "  (既定値のまま)"

hr; echo "[5] ufw"
$SUDO ufw status 2>/dev/null | head -12 || echo "  (ufw情報なし)"

if [ -n "$TARGET" ]; then
    hr; echo "[6] $TARGET の直近ログ"
    $SUDO grep -h "$TARGET" /var/log/auth.log /var/log/auth.log.1 2>/dev/null | tail -8 \
        || echo "  auth.log に該当なし"

    hr; echo "[7] $TARGET を解除"
    if command -v fail2ban-client >/dev/null 2>&1; then
        for jail in $($SUDO fail2ban-client status 2>/dev/null \
                      | sed -n 's/.*Jail list:\s*//p' | tr ',' ' '); do
            out=$($SUDO fail2ban-client set "$jail" unbanip "$TARGET" 2>&1)
            echo "  [$jail] $out"
        done
    fi
    # iptables/nftables に残った直接ルールも確認（残骸対策）
    echo "--- iptables に $TARGET のルールが残っていないか ---"
    $SUDO iptables -S 2>/dev/null | grep "$TARGET" || echo "  iptables: 残存ルールなし"
fi

hr; echo "完了。この画面の内容をそのまま共有してください。"
