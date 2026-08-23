#!/usr/bin/env bash
# ============================================================
# ssh_fix.sh — sshd "Missing privilege separation directory: /run/sshd" の修正
#
#     cd /opt/faceprediction && git pull && bash deploy/ssh_fix.sh
#
# 原因: /run は tmpfs のため再起動で消える。/run/sshd が無いと
#       sshd は接続を受けた瞬間に子プロセスが fatal で死に、
#       バナーを返さないまま切断される（ポートはLISTENしたまま）。
#
# 対処: (1) /run/sshd を作成
#       (2) /etc/tmpfiles.d/sshd.conf で再起動後も自動生成させる
#       (3) 構文チェックしてから sshd を再起動
#
# ★VNCコンソールから実行すること。失敗してもVNCは失われない。
# ============================================================
set -u
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
hr() { echo "=============================================="; }

hr; echo "[1] /run/sshd を作成"
$SUDO mkdir -p /run/sshd
$SUDO chmod 0755 /run/sshd
$SUDO chown root:root /run/sshd
$SUDO ls -ld /run/sshd

hr; echo "[2] 再発防止: /etc/tmpfiles.d/sshd.conf"
echo 'd /run/sshd 0755 root root -' | $SUDO tee /etc/tmpfiles.d/sshd.conf
$SUDO systemd-tmpfiles --create /etc/tmpfiles.d/sshd.conf 2>&1 | head -5
echo "  → 再起動時も systemd が自動で作り直す"

hr; echo "[3] 参考: ssh.service の RuntimeDirectory 設定"
$SUDO systemctl cat ssh.service 2>/dev/null | grep -Ei 'RuntimeDirectory|ExecStart' | head -6 \
  || echo "  (取得不可)"

hr; echo "[4] 構文チェック（NGならここで中断）"
if ! $SUDO sshd -t; then
    echo "❌ sshd_config に問題あり。再起動を中止しました。"
    exit 1
fi
echo "  ✅ 構文OK"

hr; echo "[5] sshd を再起動"
$SUDO systemctl restart ssh 2>/dev/null || $SUDO systemctl restart sshd 2>/dev/null
sleep 2
$SUDO systemctl is-active ssh 2>/dev/null || $SUDO systemctl is-active sshd 2>/dev/null
$SUDO systemctl restart ssh.socket 2>/dev/null && echo "  (ssh.socket も再起動)" || true

hr; echo "[6] 確認: ループバックでバナーが返るか"
BANNER=$( ( sleep 3 ) | timeout 6 nc 127.0.0.1 22 2>/dev/null | head -c 60 )
if [ -n "$BANNER" ]; then
    echo "  ✅ バナー受信: $BANNER"
    echo "  → 修復成功。外部から ssh を試せます。"
else
    echo "  ❌ まだバナーが返りません。直近ログ:"
    $SUDO journalctl -u ssh -n 15 --no-pager 2>/dev/null | tail -15
fi

hr; echo "完了。"
