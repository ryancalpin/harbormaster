from __future__ import annotations
import logging
import psutil
from harbormaster.approval.base import ApprovalGateway
from harbormaster.models import PortRecord, PortState
from harbormaster.notification.event import NotificationEvent
from harbormaster.state import StateDB

logger = logging.getLogger("harbormaster")


class ProcessWatcher:
    """Monitors registered PIDs and cleans up state when processes exit."""

    def __init__(self, db: StateDB, gateway: ApprovalGateway | None = None) -> None:
        self._db = db
        self._gateway = gateway

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
            if self._gateway is not None:
                detail = f"PID {record.pid} ({record.process_name or 'unknown'}) is gone"
                event = NotificationEvent("process_died", record.port, detail)
                try:
                    await self._gateway.notify(event)
                except Exception as exc:
                    logger.warning("Notification failed for port %d: %s", record.port, exc)
            await self._db.remove_port(record.port)
            return
        try:
            proc = psutil.Process(record.pid)
            current_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            if self._gateway is not None:
                detail = f"PID {record.pid} ({record.process_name or 'unknown'}) is gone"
                event = NotificationEvent("process_died", record.port, detail)
                try:
                    await self._gateway.notify(event)
                except Exception as exc:
                    logger.warning("Notification failed for port %d: %s", record.port, exc)
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
