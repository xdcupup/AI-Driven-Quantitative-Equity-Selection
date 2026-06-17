import random
import threading
import time


class EastMoneyLimiter:
    """Serial limiter for East Money endpoints."""

    def __init__(
        self,
        min_interval_sec: float = 1.0,
        jitter_range: tuple[float, float] = (0.1, 0.5),
    ):
        self.min_interval_sec = float(min_interval_sec)
        self.jitter_range = jitter_range
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last_call
            wait_for = self.min_interval_sec - elapsed
            if wait_for > 0:
                jitter = random.uniform(*self.jitter_range)
                time.sleep(wait_for + jitter)
            self._last_call = time.time()

