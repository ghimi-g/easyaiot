# syntax=docker/dockerfile:1.4
# Maven 本地仓库挂载宿主机 .build-cache/m2/repository（由 install_linux.sh 预创建）
FROM maven:3.9.11-eclipse-temurin-21-alpine AS builder

RUN mkdir -p /m2/repository && \
    cat > /m2/settings.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 http://maven.apache.org/xsd/settings-1.0.0.xsd">
  <mirrors>
    <mirror>
      <id>aliyun</id>
      <mirrorOf>central</mirrorOf>
      <name>Aliyun Maven</name>
      <url>https://maven.aliyun.com/nexus/content/groups/public/</url>
    </mirror>
  </mirrors>
  <localRepository>/m2/repository</localRepository>
  <interactiveMode>false</interactiveMode>
</settings>
EOF

ENV MAVEN_CONFIG=/m2/settings.xml

WORKDIR /app

COPY pom.xml .
COPY lombok.config .
COPY iot-parent/pom.xml ./iot-parent/
COPY iot-common/pom.xml ./iot-common/
COPY iot-dataset/pom.xml ./iot-dataset/
COPY iot-device/pom.xml ./iot-device/
COPY iot-file/pom.xml ./iot-file/
COPY iot-gateway/pom.xml ./iot-gateway/
COPY iot-infra/pom.xml ./iot-infra/
COPY iot-message/pom.xml ./iot-message/
COPY iot-sink/pom.xml ./iot-sink/
COPY iot-system/pom.xml ./iot-system/
COPY iot-tdengine/pom.xml ./iot-tdengine/
COPY iot-gb28181/pom.xml ./iot-gb28181/

COPY . .

# 预下载依赖到宿主机挂载的 .m2（二次构建复用，无需重复从中央库拉取）
RUN --mount=type=bind,source=.build-cache/m2/repository,target=/m2/repository \
    mvn process-resources -B -Drevision=1.0.0 && \
    (mvn dependency:go-offline -B -Drevision=1.0.0 || echo "dependency:go-offline 部分模块跳过，继续打包")

RUN --mount=type=bind,source=.build-cache/m2/repository,target=/m2/repository \
    mvn clean package -DskipTests -Dmaven.test.skip=true -Drevision=1.0.0

FROM bellsoft/liberica-openjdk-rocky:21.0.8-cds AS runtime-base
RUN groupadd -r appgroup -g 1001 && useradd -r -u 1001 -g appgroup appuser

RUN mkdir -p /app/{logs,config,data,cache,temp,backup,message-queue} && chown -R appuser:appgroup /app
WORKDIR /app

ENV TZ=Asia/Shanghai
ENV LANG=C.UTF-8
ENV JAVA_OPTS="-Xms512m -Xmx512m -Djava.security.egd=file:/dev/./urandom"
ENV SPRING_PROFILES_ACTIVE="prod"

FROM runtime-base AS iot-gateway
COPY --from=builder /app/iot-gateway/target/iot-gateway.jar app.jar
ENV SERVER_PORT=48080
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48080
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-infra
COPY --from=builder /app/iot-infra/iot-infra-biz/target/iot-infra-biz.jar app.jar
ENV SERVER_PORT=48082
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48082
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-device
COPY --from=builder /app/iot-device/iot-device-biz/target/iot-device-biz.jar app.jar
ENV SERVER_PORT=48083
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48083
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-dataset
COPY --from=builder /app/iot-dataset/iot-dataset-biz/target/iot-dataset-biz.jar app.jar
ENV SERVER_PORT=48087
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48087
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-file
COPY --from=builder /app/iot-file/iot-file-biz/target/iot-file-biz.jar app.jar
ENV SERVER_PORT=48090
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48090
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-tdengine
COPY --from=builder /app/iot-tdengine/iot-tdengine-biz/target/iot-tdengine-biz.jar app.jar
ENV SERVER_PORT=48091
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48091
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-sink
COPY --from=builder /app/iot-sink/iot-sink-biz/target/iot-sink-biz.jar app.jar
ENV SERVER_PORT=48092
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48092
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-message
COPY --from=builder /app/iot-message/iot-message-biz/target/iot-message-biz.jar app.jar
ENV SERVER_PORT=48093
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48093
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-system
COPY --from=builder /app/iot-system/iot-system-biz/target/iot-system-biz.jar app.jar
ENV SERVER_PORT=48099
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48099
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]

FROM runtime-base AS iot-gb28181
COPY --from=builder /app/iot-gb28181/iot-gb28181-biz/target/iot-gb28181-biz.jar app.jar
ENV SERVER_PORT=48088
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT}/actuator/health || exit 1
USER appuser
EXPOSE 48088
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
