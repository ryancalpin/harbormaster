from __future__ import annotations
import psutil
from harbormaster.models import PortRecord, PortState
from harbormaster.state import StateDB


class ProcessWatcher:
    """Monitors registered PIDs and cleans up state when processes exit."""

    def __init__(self, db: StateDB):
        self._db = db

    async def check_all(self) -> None:
        records = await self._db.list_ports()
        for record in records:
            if record.state == PortState.LOCKED:
                # Daemon holds the socket — keep the record regardless of process state
                continue
            if record.pid is None:
                continue
            await self._check_record(record)

    async def _check_record(self, record: PortRecord) -> None:
        if not psutil.pid_exists(record.pid):
            await self._db.remove_port(record.port)
            return
        try:
            proc = psutil.Process(record.pid)
            current_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            await self._db.remove_port(record.port)
            return
        if current_name != record.process_name:
            # PID recycled — update registration to new process
            updated = PortRecord(
                port=record.port,
                state=record.state,
                pid=record.pid,
                process_name=current_name,
            )
            await self._db.set_port(updated)
