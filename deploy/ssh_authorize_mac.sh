#!/usr/bin/env bash
# ============================================================
# ssh_authorize_mac.sh — 開発用Macの公開鍵を root の authorized_keys に登録
#
#     cd /opt/faceprediction && git pull && bash deploy/ssh_authorize_mac.sh
#
# 登録するのは公開鍵のみ（秘密鍵はMacから出ない）。
# 冪等: 既に登録済みなら何もしない。
#
# 取り消したいときは authorized_keys から該当行を消すだけ:
#     sed -i '/y937633@gmail.com/d' /root/.ssh/authorized_keys
# ============================================================
set -u
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDV46nM0+YgUfoPerQsjm0nxlNNnHfriBA5u8Xz3Fcy0 y937633@gmail.com'
AK=/root/.ssh/authorized_keys

mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch "$AK" && chmod 600 "$AK"

if grep -qF "${KEY%% *} $(echo "$KEY" | awk '{print $2}')" "$AK" 2>/dev/null; then
    echo "✅ 既に登録済み（変更なし）"
else
    echo "$KEY" >> "$AK"
    echo "✅ 登録しました"
fi

echo "--- authorized_keys の中身（コメント欄のみ表示）---"
awk '{print NR": "$1" ..."$NF}' "$AK"
ls -l "$AK"
echo "完了。外部から ssh を試せます。"
