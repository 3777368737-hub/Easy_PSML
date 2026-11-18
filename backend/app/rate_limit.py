from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from app.config import get_settings
from app.errors import AppError


class ModelRateLimiter:
    def __init__(self) -> None:
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, owner_id: str) -> None:
        settings = get_settings()
        limit = settings.model_calls_per_window
        window = settings.model_rate_window_seconds
        now = time.monotonic()

        with self._lock:
            if len(self._events) > 10000:
                stale_keys = [
                    key
                    for key, queued in self._events.items()
                    if not queued or queued[-1] <= now - window
                ]
                for key in stale_keys:
                    self._events.pop(key, None)
            events = self._events[owner_id]
            while events and events[0] <= now - window:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(window - (now - events[0])))
                raise AppError(
                    f"Too many model requests. Retry after {retry_after} seconds.",
                    status_code=429,
                    code="rate_limited",
                )
            events.append(now)


model_rate_limiter = ModelRateLimiter()
