import math
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class AttemptState:
    failures: int
    blocked_until: float
    last_seen: float


class LoginAttemptLimiter:
    def __init__(
        self,
        *,
        threshold: int = 3,
        max_delay_seconds: int = 60,
        idle_ttl_seconds: int = 15 * 60,
        max_entries: int = 2048,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.threshold = threshold
        self.max_delay_seconds = max_delay_seconds
        self.idle_ttl_seconds = idle_ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._states: dict[str, AttemptState] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(source: str, username: str) -> tuple[str, str]:
        normalized_source = (source or "unknown").strip().lower()[:256] or "unknown"
        normalized_username = (username or "").strip().casefold()[:256]
        return f"source:{normalized_source}", f"identity:{normalized_source}:{normalized_username}"

    def retry_after(self, source: str, username: str) -> int:
        now = self.clock()
        with self._lock:
            self._prune(now)
            retry = 0.0
            for key in self._keys(source, username):
                state = self._states.get(key)
                if not state:
                    continue
                state.last_seen = now
                retry = max(retry, state.blocked_until - now)
            return max(0, math.ceil(retry))

    def record_failure(self, source: str, username: str) -> int:
        now = self.clock()
        with self._lock:
            self._prune(now)
            delay = 0
            for key in self._keys(source, username):
                state = self._states.get(key)
                if state is None:
                    self._make_room()
                    state = AttemptState(failures=0, blocked_until=0, last_seen=now)
                    self._states[key] = state
                state.failures += 1
                state.last_seen = now
                if state.failures >= self.threshold:
                    exponent = state.failures - self.threshold
                    key_delay = min(2**exponent, self.max_delay_seconds)
                    state.blocked_until = now + key_delay
                    delay = max(delay, key_delay)
            return delay

    def record_success(self, source: str, username: str) -> None:
        with self._lock:
            for key in self._keys(source, username):
                self._states.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._states.clear()

    def entry_count(self) -> int:
        with self._lock:
            return len(self._states)

    def _prune(self, now: float) -> None:
        stale = [
            key
            for key, state in self._states.items()
            if now - state.last_seen >= self.idle_ttl_seconds
        ]
        for key in stale:
            self._states.pop(key, None)

    def _make_room(self) -> None:
        if len(self._states) < self.max_entries:
            return
        oldest = min(self._states, key=lambda key: self._states[key].last_seen)
        self._states.pop(oldest, None)
