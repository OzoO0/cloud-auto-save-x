from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class Metric:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    min_ms: float = 0.0
    samples: deque[float] | None = None


class MetricsStore:
    def __init__(self, sample_size: int = 512):
        self._sample_size = sample_size
        self._by_key: dict[str, Metric] = defaultdict(lambda: Metric(samples=deque(maxlen=sample_size)))

    def record(self, key: str, elapsed_ms: float) -> None:
        m = self._by_key[key]
        m.count += 1
        m.total_ms += elapsed_ms
        m.max_ms = max(m.max_ms, elapsed_ms)
        m.min_ms = elapsed_ms if m.min_ms == 0.0 else min(m.min_ms, elapsed_ms)
        if m.samples is not None:
            m.samples.append(elapsed_ms)

    def snapshot(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for key, m in self._by_key.items():
            avg = (m.total_ms / m.count) if m.count else 0.0
            p95 = 0.0
            if m.samples:
                s = sorted(m.samples)
                idx = int(round(0.95 * (len(s) - 1)))
                p95 = float(s[idx])
            out[key] = {
                "count": float(m.count),
                "avg_ms": float(avg),
                "p95_ms": float(p95),
                "max_ms": float(m.max_ms),
                "min_ms": float(m.min_ms),
            }
        return out


metrics_store = MetricsStore()
