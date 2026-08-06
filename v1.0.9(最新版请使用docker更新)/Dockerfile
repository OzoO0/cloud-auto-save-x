# ---------- frontend build ----------
FROM node:22-alpine AS frontend-builder
WORKDIR /fe
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml /fe/
RUN pnpm install --frozen-lockfile
COPY frontend/ /fe/
RUN pnpm build

# ---------- backend deps ----------
FROM python:3.13-alpine AS backend-builder
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apk add --no-cache build-base libffi-dev openssl-dev
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/

# ---------- runtime (nginx + uvicorn) ----------
FROM python:3.13-alpine
ARG BUILD_SHA
ARG BUILD_TAG
ENV BUILD_SHA=$BUILD_SHA \
    BUILD_TAG=$BUILD_TAG \
    TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apk add --no-cache nginx supervisor tzdata ca-certificates libffi openssl \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && mkdir -p /run/nginx /var/log/supervisor /app/backend/data

COPY --from=backend-builder /usr/local /usr/local
COPY --from=backend-builder /app/backend /app/backend
COPY --from=frontend-builder /fe/dist /usr/share/nginx/html

COPY default /etc/nginx/http.d/default.conf

RUN printf '%s\n' \
    '[unix_http_server]' \
    'file=/run/supervisor.sock' \
    'chmod=0700' \
    '' \
    '[rpcinterface:supervisor]' \
    'supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface' \
    '' \
    '[supervisord]' \
    'nodaemon=true' \
    '' \
    '[program:uvicorn]' \
    'directory=/app/backend' \
    'command=python -m uvicorn app.main:app --host 0.0.0.0 --port 8000' \
    'autostart=true' \
    'autorestart=true' \
    'stdout_logfile=/dev/fd/1' \
    'stdout_logfile_maxbytes=0' \
    'stderr_logfile=/dev/fd/2' \
    'stderr_logfile_maxbytes=0' \
    '' \
    '[program:nginx]' \
    'command=/usr/sbin/nginx -g "daemon off;"' \
    'autostart=true' \
    'autorestart=true' \
    'stdout_logfile=/dev/fd/1' \
    'stdout_logfile_maxbytes=0' \
    'stderr_logfile=/dev/fd/2' \
    'stderr_logfile_maxbytes=0' \
    '' \
    '[supervisorctl]' \
    'serverurl=unix:///run/supervisor.sock' \
    > /etc/supervisord.conf

EXPOSE 5115
CMD ["/usr/bin/supervisord","-c","/etc/supervisord.conf"]
