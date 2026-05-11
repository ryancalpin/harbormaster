from __future__ import annotations
from dataclasses import dataclass


@dataclass
class NotificationEvent:
    event_type: str   # "reservation_expiring" | "process_died"
    port: int
    detail: str       # human-readable context
