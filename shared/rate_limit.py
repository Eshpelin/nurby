"""Sliding-window rate limiting for unauthenticated endpoints.

The API runs as a single uvicorn process (see services/api/Dockerfile),
so an in-process window is authoritative for login throttling — no shared
store needed. Pure logic, no I/O: routes own the policy knobs
(shared.config settings), tests can pin the clock via ``_clock``.
"""

import time
from collections import deque


class SlidingWindowLimiter:
    """Counts timestamped failures per key inside a sliding window.

    ``retry_after_s`` is read-only (it never records); routes call it
    before doing work, ``record_failure`` after a rejected attempt, and
    ``record_success`` to clear a key (e.g. a correct password resets the
    per-email bucket while the per-source bucket just ages out).
    """

    def __init__(self, max_attempts: int, window_s: float):
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._attempts: dict[str, deque[float]] = {}
        self._clock = time.monotonic

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._attempts.get(key)
        if bucket is None:
            return deque()
        cutoff = now - self.window_s
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket:
            self._attempts.pop(key, None)
            return deque()
        return bucket

    def retry_after_s(self, key: str) -> float:
        """0.0 when the key may attempt again; otherwise the seconds
        until enough old failures have aged out of the window."""
        now = self._clock()
        bucket = self._prune(key, now)
        if len(bucket) < self.max_attempts:
            return 0.0
        # Room opens when the (len - max + 1)-th oldest failure expires.
        kth_oldest = sorted(bucket)[len(bucket) - self.max_attempts]
        return max(0.0, kth_oldest + self.window_s - now)

    def record_failure(self, key: str) -> None:
        now = self._clock()
        bucket = self._prune(key, now)
        bucket.append(now)
        self._attempts[key] = bucket

    def record_success(self, key: str) -> None:
        self._attempts.pop(key, None)

    def clear(self) -> None:
        self._attempts.clear()
