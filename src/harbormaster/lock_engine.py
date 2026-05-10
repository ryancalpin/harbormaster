from __future__ import annotations
import socket
import asyncio


class PrivilegedPortError(Exception):
    """Raised when attempting to lock a port below 1024."""


class LockEngine:
    def __init__(self):
        self._sockets: dict[int, socket.socket] = {}
        self._lock = asyncio.Lock()

    async def lock(self, port: int) -> bool:
        """
        Lock a port by binding a socket to it.
        Returns True on success, False if port is already in use by another process.
        Raises PrivilegedPortError for ports < 1024.
        Idempotent: locking an already-held port returns True.
        """
        if port < 1024:
            raise PrivilegedPortError(
                f"Port {port} requires elevated privileges to lock. "
                "Harbormaster can track and claim it but cannot enforce hard locks."
            )
        async with self._lock:
            if port in self._sockets:
                return True  # already held by us
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", port))
                self._sockets[port] = sock
                return True
            except OSError:
                sock.close()
                return False

    async def unlock(self, port: int) -> bool:
        """Release a held socket. Returns False if port was not locked by us."""
        async with self._lock:
            sock = self._sockets.pop(port, None)
            if sock is None:
                return False
            try:
                sock.close()
            except OSError:
                pass
            return True

    def is_locked(self, port: int) -> bool:
        return port in self._sockets

    def locked_ports(self) -> list[int]:
        return list(self._sockets.keys())

    async def shutdown(self) -> None:
        async with self._lock:
            for sock in self._sockets.values():
                try:
                    sock.close()
                except OSError:
                    pass
            self._sockets.clear()
