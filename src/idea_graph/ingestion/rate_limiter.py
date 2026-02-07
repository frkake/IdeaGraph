"""サービスごとのレート制限管理モジュール"""

import threading
import time


class ServiceRateLimiter:
    """セマフォ（同時接続数）+ タイムスタンプ（最小間隔）によるレート制限"""

    def __init__(
        self,
        name: str,
        max_concurrent: int = 1,
        min_interval_seconds: float = 0.0,
    ):
        self.name = name
        self._semaphore = threading.Semaphore(max_concurrent)
        self._interval_lock = threading.Lock()
        self._min_interval = min_interval_seconds
        self._last_request_time: float = 0.0

    def acquire(self) -> None:
        """セマフォを取得し、最小間隔を保証する"""
        self._semaphore.acquire()
        if self._min_interval > 0:
            with self._interval_lock:
                elapsed = time.monotonic() - self._last_request_time
                if elapsed < self._min_interval:
                    time.sleep(self._min_interval - elapsed)
                self._last_request_time = time.monotonic()

    def release(self) -> None:
        """セマフォを解放する"""
        self._semaphore.release()

    def __enter__(self) -> "ServiceRateLimiter":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
