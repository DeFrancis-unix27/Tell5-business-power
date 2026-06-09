import time
import threading
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._failures: dict[str, int] = {}
        self._state: dict[str, CircuitState] = {}
        self._last_failure_time: dict[str, float] = {}
        self._lock = threading.Lock()

    def _get_state(self, provider: str) -> CircuitState:
        state = self._state.get(provider, CircuitState.CLOSED)
        if state == CircuitState.OPEN:
            last_fail = self._last_failure_time.get(provider, 0)
            if time.time() - last_fail > self.reset_timeout:
                self._state[provider] = CircuitState.HALF_OPEN
                return CircuitState.HALF_OPEN
        return state

    def is_open(self, provider: str) -> bool:
        with self._lock:
            return self._get_state(provider) == CircuitState.OPEN

    def record_success(self, provider: str):
        with self._lock:
            self._failures[provider] = 0
            self._state[provider] = CircuitState.CLOSED

    def record_failure(self, provider: str):
        with self._lock:
            current_state = self._state.get(provider, CircuitState.CLOSED)
            if current_state == CircuitState.HALF_OPEN:
                self._state[provider] = CircuitState.OPEN
                self._last_failure_time[provider] = time.time()
                return
            self._failures[provider] = self._failures.get(provider, 0) + 1
            self._last_failure_time[provider] = time.time()
            if self._failures[provider] >= self.failure_threshold:
                self._state[provider] = CircuitState.OPEN


circuit_breaker = CircuitBreaker()
