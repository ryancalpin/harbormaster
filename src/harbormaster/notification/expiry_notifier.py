from __future__ import annotations
import logging
from datetime import datetime, timezone

from harbormaster.approval.base import ApprovalGateway
from harbormaster.models import PortState
from harbormaster.notification.event import NotificationEvent
from harbormaster.state import StateDB

logger = logging.getLogger("harbormaster")


class ExpiryNotifier:
    def __init__(self, lead_time_seconds: int) -> None:
        self._lead_time = lead_time_seconds
        self._notified: set[int] = set()

    async def check(self, db: StateDB, gateway: ApprovalGateway) -> None:
        now = datetime.now(timezone.utc)
        records = await db.list_ports()
        active_reserved = {r.port for r in records if r.state == PortState.RESERVED}

        # Clear notified entries for ports no longer reserved
        self._notified &= active_reserved

        for record in records:
            if record.state != PortState.RESERVED:
                continue
            if record.reserved_until is None:
                continue  # permanent reservation — no expiry to warn about
            if record.port in self._notified:
                continue
            delta = (record.reserved_until - now).total_seconds()
            if 0 < delta <= self._lead_time:
                minutes = max(1, int(delta / 60))
                detail = f"expires in {minutes} minute{'s' if minutes != 1 else ''}"
                event = NotificationEvent("reservation_expiring", record.port, detail)
                try:
                    await gateway.notify(event)
                except Exception as exc:
                    logger.warning("Notification failed for port %d: %s", record.port, exc)
                self._notified.add(record.port)
