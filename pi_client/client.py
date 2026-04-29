"""RPyC client wrapper with reconnect-with-backoff.

The robot must keep moving even if the VM link flaps. ``authenticate()``
returns ``None`` when the VM is unreachable; the state machine treats that as
"don't know, keep wandering, blink amber" — never as a fatal error.
"""

from __future__ import annotations

import json
import logging
import socket
import time
from typing import Optional

import rpyc

from protocol import AuthResult

log = logging.getLogger(__name__)


class VisionClient:
    def __init__(self, host: str, port: int, timeout: float = 10.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._conn: Optional[rpyc.Connection] = None
        self._backoff = 0.5

    def _ensure(self) -> Optional[rpyc.Connection]:
        if self._conn is not None:
            try:
                self._conn.ping(timeout=1.0)
                return self._conn
            except Exception:
                log.warning("RPyC ping failed; will reconnect")
                self._close()

        try:
            self._conn = rpyc.connect(
                self.host, self.port,
                config={"sync_request_timeout": self.timeout},
            )
            self._backoff = 0.5
            log.info("RPyC connected to %s:%d", self.host, self.port)
            return self._conn
        except (ConnectionRefusedError, socket.error, OSError) as e:
            log.warning("RPyC connect failed: %s (backoff %.1fs)", e, self._backoff)
            time.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, 10.0)
            return None

    def _close(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def authenticate(self, jpeg_bytes: bytes) -> Optional[AuthResult]:
        conn = self._ensure()
        if conn is None:
            return None
        try:
            payload = conn.root.authenticate(jpeg_bytes)
            return AuthResult.from_dict(json.loads(str(payload)))
        except Exception as e:
            log.warning("authenticate RPC failed: %s", e)
            self._close()
            return None

    def ping(self) -> bool:
        conn = self._ensure()
        if conn is None:
            return False
        try:
            return str(conn.root.ping()) == "ok"
        except Exception:
            self._close()
            return False

    def close(self) -> None:
        self._close()
