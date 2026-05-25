# syntax=docker/dockerfile:1.4
# 构建阶段：pnpm 依赖目录挂载宿主机 .build-cache/pnpm-store（由 install_linux.sh 预创建）
FROM node:22-alpine3.21 AS builder

RUN npm config set registry https://registry.npmmirror.com/

RUN npm install -g pnpm@9.0.4 && \
    pnpm config set registry https://registry.npmmirror.com/ && \
    pnpm config set network-timeout 600000 && \
    pnpm config set fetch-retries 5 && \
    pnpm config set fetch-retry-mintimeout 20000 && \
    pnpm config set fetch-retry-maxtimeout 120000

WORKDIR /app
RUN mkdir -p /tmp/web-build-logs /pnpm/store

COPY package.json ./
COPY pnpm-lock.yaml* ./

# 复用宿主机 pnpm store + BuildKit 临时缓存（不依赖镜像层缓存）
RUN --mount=type=bind,source=.build-cache/pnpm-store,target=/pnpm/store \
    --mount=type=cache,target=/root/.local/share/pnpm/cache,id=web-pnpm-cache \
    pnpm config set store-dir /pnpm/store && \
    if [ -f pnpm-lock.yaml ]; then \
        pnpm install --frozen-lockfile 2>&1 | tee /tmp/web-build-logs/pnpm-install.log; \
    else \
        pnpm install 2>&1 | tee /tmp/web-build-logs/pnpm-install.log; \
    fi

COPY . .

RUN set -e && \
    pnpm build > /tmp/web-build-logs/pnpm-build.log 2>&1 || \
    (echo "=== pnpm build failed, log: ===" && cat /tmp/web-build-logs/pnpm-build.log && exit 1)
RUN test -d dist || (echo "=== dist missing after build ===" && cat /tmp/web-build-logs/pnpm-build.log && exit 1)

FROM nginx:1.29.2-alpine

RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

LABEL org.opencontainers.image.authors="basiclab"

WORKDIR /usr/share/nginx/html

RUN mkdir -p /usr/share/nginx/html /app/logs /opt/web-build-logs

COPY ./conf/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html
COPY --from=builder /tmp/web-build-logs /opt/web-build-logs

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

CMD ["sh", "-c", "mkdir -p /app/logs && cp -af /opt/web-build-logs/. /app/logs/ && echo \"[$(date '+%Y-%m-%d %H:%M:%S')] web-service container started\" >> /app/logs/runtime.log && nginx -g 'daemon off;'"]
