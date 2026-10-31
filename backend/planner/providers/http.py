"""Shared HTTP plumbing for upstream APIs: one pooled session, retries, and typed errors."""

from __future__ import annotations

import threading

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class UpstreamError(Exception):
    """An upstream service failed or returned something unusable."""

    status_code = 502

    def __init__(self, service: str, message: str):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.message = message


class UpstreamRateLimited(UpstreamError):
    status_code = 503


class NoRouteFound(UpstreamError):
    status_code = 422


_local = threading.local()


def session() -> requests.Session:
    """Per-thread pooled session (``requests.Session`` is not guaranteed thread-safe)."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=1,
            backoff_factor=0.5,
            status_forcelist=(502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers["User-Agent"] = settings.PLANNER["USER_AGENT"]
        _local.session = s
    return s


def timeout() -> float:
    return settings.PLANNER["HTTP_TIMEOUT_S"]
