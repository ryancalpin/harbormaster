from __future__ import annotations
import psutil
from harbormaster.models import LivePort, PortRecord, PortState
from harbormaster.state import StateDB


class PortScanner:
    def __init__(self, db: StateDB, watch_range: tuple[int, int] = (1024, 49151)):
        self._db = db
        self._watch_range = watch_range

    async def scan(self) -> list[LivePort]:
        """Return live snapshot of ports within watch_range from psutil."""
        lo, hi = self._watch_range
        result: list[LivePort] = []
        try:
            conns = psutil.net_connections(kind="inet")
        except psutil.AccessDenied:
            return result
        for conn in conns:
            if not conn.laddr or conn.pid is None:
                continue
            port = conn.laddr.port
            if not (lo <= port <= hi):
                continue
            try:
                proc = psutil.Process(conn.pid)
                name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                name = "unknown"
            result.append(LivePort(
                port=port,
                pid=conn.pid,
                process_name=name,
                is_listen=conn.status == "LISTEN",
                interface=conn.laddr.ip,
            ))
        return result

    async def reconcile(self, live_ports: list[LivePort]) -> None:
        """
        Auto-register any in-use port not yet tracked as claimed.
        Skips ports already in a managed state (claimed, locked, reserved).
        """
        for lp in live_ports:
            existing = await self._db.get_port(lp.port)
            if existing is not None:
                continue  # already tracked — watcher handles updates
            record = PortRecord(
                port=lp.port,
                state=PortState.CLAIMED,
                pid=lp.pid,
                process_name=lp.process_name,
            )
            await self._db.set_port(record)
