#!/usr/bin/env bash
# ============================================================
# ssh_diag2.sh — sshdがバナーを返さない原因の特定（読み取り専用）
#
#     cd /opt/faceprediction && git pull && bash deploy/ssh_diag2.sh
#
# 判明済み: TCP接続は成立するがSSHバナーが返らない。
#           fail2banのbanは0件、ufwは22/tcp許可、sshdはLISTEN中。
# → sshdが接続を受けた直後に子プロセスが死んでいる疑い。
#
# ★このスクリプトは何も変更しない。調査だけ。
# ============================================================
set -u
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
hr() { echo "=============================================="; }

hr; echo "[A] sshd 設定の妥当性（ここが最重要）"
echo "--- sshd -t (構文チェック) ---"
$SUDO sshd -t 2>&1 | head -20 || true
echo "  exit=$?"
echo "--- sshd -T | 主要値 ---"
$SUDO sshd -T 2>&1 | grep -Ei 'maxstartups|hostkey|port|listenaddress|permitrootlogin|usepam' | head -20

hr; echo "[B] ホスト鍵"
$SUDO ls -la /etc/ssh/ 2>&1 | grep -Ei 'host_key|sshd_config' | head -20

hr; echo "[C] 特権分離ディレクトリ /run/sshd"
$SUDO ls -ld /run/sshd 2>&1 | head -3

hr; echo "[D] sshd のログ（直近60行）"
$SUDO journalctl -u ssh -n 60 --no-pager 2>/dev/null \
  || $SUDO journalctl -u sshd -n 60 --no-pager 2>/dev/null \
  || echo "  journalctl 取得不可"

hr; echo "[E] サーバー内から自分自身へ接続してバナーが返るか"
echo "--- 127.0.0.1:22 ---"
( sleep 3 ) | timeout 6 nc 127.0.0.1 22 2>/dev/null | head -c 120 || echo "  (バナーなし)"
echo ""
echo "--- 160.251.251.73:22 (自分の外向きIP) ---"
( sleep 3 ) | timeout 6 nc 160.251.251.73 22 2>/dev/null | head -c 120 || echo "  (バナーなし)"
echo ""

hr; echo "[F] sshd_config の実効行（コメント除く）"
$SUDO grep -vE '^\s*(#|$)' /etc/ssh/sshd_config 2>/dev/null | head -40
echo "--- sshd_config.d/ ---"
$SUDO grep -rvE '^\s*(#|$)' /etc/ssh/sshd_config.d/ 2>/dev/null | head -20 || echo "  (なし)"

hr; echo "完了。[A][D][E] を中心に共有してください。"
