"""Per-username throttling for failed login attempts.

State is keyed only on the normalized submitted username: proxy headers are not
trusted, so one client cannot influence another user's bucket. The table is
bounded; when it is full, active lockouts are never evicted.
"""

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config

log = logging.getLogger(__name__)

MAX_BUCKETS = 1024
OVERFLOW_RETRY_AFTER = 30
MAX_USERNAME_LENGTH = 128
USER_KEY_PREFIX = "user:"
OVERFLOW_KEY = "overflow"

_now = time.monotonic


def normalize_username(username: str) -> str:
    """Normalize the submitted username without changing its identity."""
    return (username or "").strip()[:MAX_USERNAME_LENGTH]


def _user_key(username: str) -> str:
    return USER_KEY_PREFIX + normalize_username(username)


def _settings() -> tuple[int, float, float, float]:
    """Read tunables lazily so config changes at runtime take effect."""
    max_failures = max(1, config.LOGIN_MAX_FAILURES)
    window = float(max(1, config.LOGIN_FAILURE_WINDOW_SECONDS))
    lockout = float(max(1, config.LOGIN_LOCKOUT_SECONDS))
    max_lockout = max(lockout, float(config.LOGIN_MAX_LOCKOUT_SECONDS))
    return max_failures, window, lockout, max_lockout


@dataclass
class _Bucket:
    failures: List[float] = field(default_factory=list)
    strikes: int = 0
    locked_until: float = 0.0
    last_failure: float = 0.0


def _locked_seconds(bucket: _Bucket, now: float) -> int:
    return max(1, math.ceil(bucket.locked_until - now))


class LoginThrottle:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: Dict[str, _Bucket] = {}

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def retry_after(self, username: str) -> int:
        """Seconds the caller must wait before this username may try again."""
        if not config.LOGIN_THROTTLE_ENABLED:
            return 0
        now = _now()
        key = _user_key(username)
        with self._lock:
            self._prune(now)
            bucket = self._buckets.get(key)
            if bucket is not None:
                return _locked_seconds(bucket, now) if bucket.locked_until > now else 0
            overflow = self._buckets.get(OVERFLOW_KEY)
            if len(self._buckets) >= MAX_BUCKETS and overflow is not None and overflow.locked_until > now:
                return _locked_seconds(overflow, now)
            return 0

    def record_failure(self, username: str) -> int:
        """Count a failed attempt; return lockout seconds if now locked out."""
        if not config.LOGIN_THROTTLE_ENABLED:
            return 0
        max_failures, window, lockout, max_lockout = _settings()
        now = _now()
        key = _user_key(username)
        with self._lock:
            bucket = self._get_or_create(key, now)
            if bucket is None:
                # No evictable bucket: fall back to one shared throttle so the
                # spray cannot unlock anything that is already locked out.
                overflow = self._buckets.get(OVERFLOW_KEY)
                if overflow is None:
                    overflow = _Bucket()
                    self._buckets[OVERFLOW_KEY] = overflow
                overflow.failures = [stamp for stamp in overflow.failures if stamp > now - window]
                overflow.failures.append(now)
                overflow.last_failure = now
                overflow.locked_until = max(overflow.locked_until, now + OVERFLOW_RETRY_AFTER)
                return OVERFLOW_RETRY_AFTER
            return self._register_failure(bucket, now, window, max_failures, lockout, max_lockout)

    def record_success(self, username: str) -> None:
        key = _user_key(username)
        with self._lock:
            self._buckets.pop(key, None)

    def _register_failure(
        self,
        bucket: _Bucket,
        now: float,
        window: float,
        max_failures: int,
        lockout_seconds: float,
        max_lockout_seconds: float,
    ) -> int:
        bucket.failures = [stamp for stamp in bucket.failures if stamp > now - window]
        bucket.failures.append(now)
        bucket.last_failure = now
        if len(bucket.failures) < max_failures:
            return 0
        bucket.strikes += 1
        lockout = min(lockout_seconds * 2 ** (bucket.strikes - 1), max_lockout_seconds)
        bucket.locked_until = now + lockout
        bucket.failures.clear()
        return _locked_seconds(bucket, now)

    def _get_or_create(self, key: str, now: float) -> Optional[_Bucket]:
        bucket = self._buckets.get(key)
        if bucket is not None:
            return bucket
        if len(self._buckets) >= MAX_BUCKETS:
            self._prune(now)
        if len(self._buckets) >= MAX_BUCKETS and not self._evict_one(now):
            return None
        bucket = _Bucket()
        self._buckets[key] = bucket
        return bucket

    def _prune(self, now: float) -> None:
        _, window, _, _ = _settings()
        stale = [key for key, bucket in self._buckets.items() if self._is_stale(bucket, now, window)]
        for key in stale:
            del self._buckets[key]

    def _is_stale(self, bucket: _Bucket, now: float, window: float) -> bool:
        if bucket.locked_until > now:
            return False
        if any(stamp > now - window for stamp in bucket.failures):
            return False
        # keep strike history within the window so a repeat offender escalates
        return bucket.strikes == 0 or bucket.last_failure <= now - window

    def _evict_one(self, now: float) -> bool:
        candidates = [(bucket.last_failure, key) for key, bucket in self._buckets.items() if bucket.locked_until <= now]
        if not candidates:
            return False
        _, key = min(candidates)
        del self._buckets[key]
        return True


limiter = LoginThrottle()
# A second, independent bucket table for TOTP/recovery-code guesses. Sharing
# `limiter` would let a spray of wrong TOTP codes lock the password login out
# (and vice versa), which is a denial-of-service lever, not a defence.
mfa_limiter = LoginThrottle()
