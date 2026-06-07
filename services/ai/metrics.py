import time
import threading
from dataclasses import dataclass


@dataclass
class ProviderMetrics:
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0
    last_latency_ms: float = 0
    last_error: str = ""
    last_called_at: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return round(self.total_latency_ms / self.total_calls, 1)

    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "successes": self.successes,
            "failures": self.failures,
            "avg_latency_ms": self.avg_latency_ms,
            "last_latency_ms": round(self.last_latency_ms, 1),
            "last_error": self.last_error,
        }


class MetricsCollector:
    def __init__(self):
        self._providers: dict[str, ProviderMetrics] = {}
        self._lock = threading.Lock()

    def record(self, provider: str, success: bool, latency_ms: float, error: str = ""):
        with self._lock:
            if provider not in self._providers:
                self._providers[provider] = ProviderMetrics()
            m = self._providers[provider]
            m.total_calls += 1
            m.total_latency_ms += latency_ms
            m.last_latency_ms = latency_ms
            m.last_called_at = time.time()
            if success:
                m.successes += 1
            else:
                m.failures += 1
                if error:
                    m.last_error = error

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {k: v.to_dict() for k, v in sorted(self._providers.items())}


metrics = MetricsCollector()
