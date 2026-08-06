from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import Any

import httpx


async def fetch(client: httpx.AsyncClient, path: str) -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        response = await client.get(path)
        ok = response.status_code < 400
    except Exception:
        ok = False
    elapsed_ms = (time.perf_counter() - start) * 1000
    return ok, elapsed_ms


async def main(base_url: str, path: str, concurrency: int) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        results = await asyncio.gather(*[fetch(client, path) for _ in range(concurrency)])

    oks = [item[0] for item in results]
    times = [item[1] for item in results]
    success_rate = sum(1 for item in oks if item) / len(oks) * 100
    p95 = sorted(times)[int(0.95 * (len(times) - 1))]

    print(
        {
            "path": path,
            "concurrency": concurrency,
            "success_rate_percent": round(success_rate, 2),
            "avg_ms": round(statistics.mean(times), 2),
            "p95_ms": round(p95, 2),
            "max_ms": round(max(times), 2),
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--path", default="/health")
    parser.add_argument("--concurrency", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(main(args.base_url, args.path, args.concurrency))
