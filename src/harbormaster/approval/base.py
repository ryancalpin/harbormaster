from __future__ import annotations
import abc
import uuid
from dataclasses import dataclass, field
from enum import Enum


class ApprovalResult(Enum):
    ALLOW = "allow"
    DENY = "deny"
    TIMEOUT = "timeout"


@dataclass
class ApprovalRequest:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action: str = ""         # "lock" or "evict"
    port: int = 0
    pid: int | None = None
    process_name: str | None = None
    requester: str = "unknown"


class ApprovalGateway(abc.ABC):
    @abc.abstractmethod
    async def send_request(self, request: ApprovalRequest) -> None:
        """Deliver the approval prompt to the user."""

    @abc.abstractmethod
    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        """Block until user responds. Return ALLOW, DENY, or TIMEOUT."""

    @abc.abstractmethod
    async def cancel(self, request_id: str) -> None:
        """Called when the requesting agent disconnects before responding."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """Convenience: send + wait."""
        await self.send_request(request)
        return await self.wait_for_response(request)
