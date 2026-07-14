#!/bin/bash
# FacePredictionApp 起動スクリプト
# launchd から呼ばれる想定

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export JAVA_HOME="/opt/homebrew/opt/java11/libexec/openjdk.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"

APP_DIR="$HOME/git/FacePredictionAppStep4"
LOG_DIR="$APP_DIR/logs"
mkdir -p "$LOG_DIR"

# PostgreSQL が起動するまで最大30秒待機
echo "[$(date '+%Y-%m-%d %H:%M:%S')] PostgreSQL 起動待機中..." >> "$LOG_DIR/startup.log"
for i in $(seq 1 30); do
    if /opt/homebrew/opt/postgresql@14/bin/pg_isready -q 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] PostgreSQL 起動確認 OK" >> "$LOG_DIR/startup.log"
        break
    fi
    sleep 1
done

# ログの簡易ローテーション（logback設定を迂回した直接追記のため、ここで肥大を防ぐ。
# 10MB超なら1世代だけ退避。過去に109MBまで肥大した実績あり）
for f in springboot.log startup.log; do
    if [ -f "$LOG_DIR/$f" ] && [ "$(stat -f%z "$LOG_DIR/$f" 2>/dev/null || echo 0)" -gt 10485760 ]; then
        mv "$LOG_DIR/$f" "$LOG_DIR/$f.1"
    fi
done

# Spring Boot 起動（JVMヒープ上限512MBに固定）
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Spring Boot 起動開始..." >> "$LOG_DIR/startup.log"
cd "$APP_DIR"
exec /opt/homebrew/bin/mvn spring-boot:run \
    -Dspring-boot.run.jvmArguments="-Xms128m -Xmx512m" \
    >> "$LOG_DIR/springboot.log" 2>&1
