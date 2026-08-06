from __future__ import annotations

import logging
import time
import uuid

from app.core.metrics import metrics_store


class TimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        access_logger = logging.getLogger("app.access")

        start = time.perf_counter()
        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        key = f"{method} {path}"
        query_string = scope.get("query_string") or b""
        query = query_string.decode("latin-1") if query_string else "-"
        headers = list(scope.get("headers") or [])

        rid: str | None = None
        xff: str | None = None
        for k, v in headers:
            lk = (k or b"").lower()
            if rid is None and lk == b"x-request-id":
                rid = (v or b"").decode("latin-1").strip()[:128]
            if xff is None and lk == b"x-forwarded-for":
                xff = (v or b"").decode("latin-1").strip()[:512]
            if rid is not None and xff is not None:
                break

        if not rid:
            rid = uuid.uuid4().hex[:12]

        client_ip = ""
        if xff:
            client_ip = xff.split(",", 1)[0].strip()
        if not client_ip:
            client = scope.get("client")
            if isinstance(client, (list, tuple)) and client:
                client_ip = str(client[0] or "")

        status_code = 0

        async def send_wrapper(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 0)
                ttfb_ms = (time.perf_counter() - start) * 1000.0
                out_headers = list(message.get("headers") or [])
                out_headers = [
                    (k, v)
                    for (k, v) in out_headers
                    if (k or b"").lower() not in {b"x-response-time-ms", b"x-request-id"}
                ]
                out_headers.append((b"x-response-time-ms", f"{ttfb_ms:.2f}".encode("ascii")))
                out_headers.append((b"x-request-id", rid.encode("ascii", "ignore") or b"-"))
                message["headers"] = out_headers
            if message.get("type") == "http.response.body" and not message.get("more_body", False):
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                metrics_store.record(key, elapsed_ms)
                access_logger.info(
                    "rid=%s method=%s path=%s query=%s status=%s cost_ms=%.2f client_ip=%s",
                    rid,
                    method,
                    path,
                    query,
                    status_code,
                    elapsed_ms,
                    client_ip,
                )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            access_logger.exception(
                "rid=%s method=%s path=%s query=%s status=500 cost_ms=%.2f client_ip=%s",
                rid,
                method,
                path,
                query,
                elapsed_ms,
                client_ip,
            )
            raise
