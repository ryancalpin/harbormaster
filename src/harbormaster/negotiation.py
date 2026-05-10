from __future__ import annotations
from datetime import datetime, timedelta


class NegotiationHolds:
    """
    In-memory short-lived port holds issued during /request negotiation.
    Not persisted. Prevents two simultaneous /request calls from returning
    the same port before either caller has had a chance to bind.
    """

    def __init__(self):
        self._holds: dict[int, datetime] = {}

    def add(self, port: int, ttl_seconds: int = 10) -> None:
        self._holds[port] = datetime.utcnow() + timedelta(seconds=ttl_seconds)

    def release(self, port: int) -> None:
        self._holds.pop(port, None)

    def is_held(self, port: int) -> bool:
        expiry = self._holds.get(port)
        if expiry is None:
            return False
        if datetime.utcnow() >= expiry:
            del self._holds[port]
            return False
        return True

    def expire_stale(self) -> None:
        now = datetime.utcnow()
        expired = [p for p, exp in self._holds.items() if now >= exp]
        for p in expired:
            del self._holds[p]

    def next_available(
        self,
        preferred: int,
        max_port: int,
        unavailable: set[int],
    ) -> int | None:
        """
        Return the first port >= preferred that is not held and not in unavailable.
        Returns None if no port found up to max_port.
        """
        for port in range(preferred, max_port + 1):
            if port not in unavailable and not self.is_held(port):
                return port
        return None
