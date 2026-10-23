"""In-memory sliding-window rate limiter.

For each client key we keep a deque of request timestamps. On every hit we
drop timestamps older than the window and allow the request only if fewer
than `limit` remain. Memory per client is O(limit).

This is per-process: running several workers behind a load balancer would
need a shared store such as Redis instead.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Callable


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest hit in the window expires."""
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            return max(1, int(self.window - (self._clock() - hits[0]) + 0.999))
