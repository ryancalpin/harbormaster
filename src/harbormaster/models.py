from __future__ import annotations
import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class PortState(enum.Enum):
    OPEN = "open"
    RESERVED = "reserved"
    IN_USE = "in-use"
    CLAIMED = "claimed"
    LOCKED = "locked"


@dataclass
class PortRecord:
    port: int
    state: PortState
    pid: int | None = None
    process_name: str | None = None
    reserved_until: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "state": self.state.value,
            "pid": self.pid,
            "process_name": self.process_name,
            "reserved_until": self.reserved_until.isoformat() if self.reserved_until else None,
        }


@dataclass
class LivePort:
    port: int
    pid: int
    process_name: str
    is_listen: bool          # True = LISTEN (incoming), False = ESTABLISHED (outgoing)
    interface: str           # bound IP address, e.g. "127.0.0.1" or "100.x.x.x"
