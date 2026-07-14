# ── Stage 1: ビルド ──────────────────────────────────────────────
# digest固定: 再ビルドで中身が勝手に変わらないようにする。
# 更新手順: hub.docker.com で新しい digest を確認して差し替え → 再ビルド
FROM maven:3.9-eclipse-temurin-17@sha256:1ed5d1f54416b706707b4f3238f63a20bb06aab27c6d240090a2bb9ad895ed45 AS builder
WORKDIR /app
COPY pom.xml .
# 依存キャッシュ（ソース変更時に再ダウンロード不要）
RUN mvn dependency:go-offline -q
COPY src ./src
RUN mvn package -DskipTests -q

# ── Stage 2: 実行 ────────────────────────────────────────────────
FROM eclipse-temurin:17-jre-alpine@sha256:02320dd4ce20e243dfb915c686089cf9315c763084fafbb12d5c9993aee18b57
WORKDIR /app

# タイムゾーン（JST）
RUN apk add --no-cache tzdata && \
    cp /usr/share/zoneinfo/Asia/Tokyo /etc/localtime && \
    echo "Asia/Tokyo" > /etc/timezone

COPY --from=builder /app/target/*.jar app.jar

# アップロードディレクトリ
RUN mkdir -p /data/uploads
VOLUME ["/data/uploads"]

EXPOSE 8081

ENV JAVA_OPTS="-Xms256m -Xmx512m"

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
