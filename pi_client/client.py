"""HTTP client for the VM vision service (FastAPI + Cloudflare Quick Tunnel).

Talks to a public ``https://*.trycloudflare.com`` URL that fronts the VM's
FastAPI server. Bearer-token auth is the only access control on that URL.

Resilience contract: the robot must keep moving even if the VM link flaps.
``authenticate()`` returns ``None`` on any failure; the state machine treats
that as "don't know, keep wandering, blink amber" — never as a fatal error.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from protocol import AuthResult

log = logging.getLogger(__name__)


class VisionClient:
    def __init__(self, url: str, token: str, timeout: float = 10.0) -> None:
        self.base_url = url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    def _post_bytes(self, path: str, body: bytes) -> Optional[dict]:
        try:
            r = self._session.post(
                f"{self.base_url}{path}",
                data=body,
                headers={"Content-Type": "application/octet-stream"},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log.warning("POST %s failed: %s", path, e)
            return None

    def authenticate(self, jpeg_bytes: bytes) -> Optional[AuthResult]:
        data = self._post_bytes("/authenticate", jpeg_bytes)
        if data is None:
            return None
        try:
            return AuthResult.from_dict(data)
        except (KeyError, ValueError, TypeError) as e:
            log.warning("authenticate response malformed: %s body=%r", e, data)
            return None

    def ping(self) -> bool:
        try:
            r = self._session.get(f"{self.base_url}/ping", timeout=self.timeout)
            r.raise_for_status()
            return bool(r.json().get("ok"))
        except requests.RequestException as e:
            log.warning("ping failed: %s", e)
            return False

    def close(self) -> None:
        self._session.close()
