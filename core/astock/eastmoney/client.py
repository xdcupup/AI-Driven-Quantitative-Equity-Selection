"""Rate-limited East Money client for non-market A-share datasets."""

from __future__ import annotations

import random
import threading
import time
from typing import Any

import requests


DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}


class EastMoneyDataClient:
    """Small East Money wrapper reserved for datasets without better sources."""

    def __init__(
        self,
        session: requests.Session | None = None,
        min_interval_sec: float = 1.0,
        jitter_range: tuple[float, float] = (0.1, 0.5),
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.min_interval_sec = float(min_interval_sec)
        self.jitter_range = jitter_range
        self._last_call = 0.0
        self._lock = threading.Lock()

    def em_get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 15,
        **kwargs: Any,
    ) -> requests.Response:
        """GET through the shared East Money throttle."""
        with self._lock:
            elapsed = time.time() - self._last_call
            wait_for = self.min_interval_sec - elapsed
            if wait_for > 0:
                time.sleep(wait_for + random.uniform(*self.jitter_range))
            try:
                return self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                    **kwargs,
                )
            finally:
                self._last_call = time.time()

    def datacenter(
        self,
        report_name: str,
        columns: str = "ALL",
        filter_str: str = "",
        page_size: int = 50,
        sort_columns: str = "",
        sort_types: str = "-1",
    ) -> list[dict[str, Any]]:
        """Query East Money datacenter reports and return the raw row list."""
        params = {
            "reportName": report_name,
            "columns": columns,
            "filter": filter_str,
            "pageNumber": "1",
            "pageSize": str(page_size),
            "sortColumns": sort_columns,
            "sortTypes": sort_types,
            "source": "WEB",
            "client": "WEB",
        }
        response = self.em_get(DATACENTER_URL, params=params, timeout=15)
        try:
            payload = response.json()
        except ValueError:
            return []
        if not isinstance(payload, dict):
            return []
        result = payload.get("result")
        if not isinstance(result, dict):
            return []
        data = result.get("data")
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]
