# ── Stage 1: ビルド ──────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-17 AS builder
WORKDIR /app
COPY pom.xml .
# 依存キャッシュ（ソース変更時に再ダウンロード不要）
RUN mvn dependency:go-offline -q
COPY src ./src
RUN mvn package -DskipTests -q

# ── Stage 2: 実行 ────────────────────────────────────────────────
FROM eclipse-temurin:17-jre-alpine
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
