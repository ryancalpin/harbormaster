from __future__ import annotations
import asyncio
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult
from harbormaster.approval.manager import ApprovalManager
from harbormaster.notification.event import NotificationEvent


class TuiGateway(ApprovalGateway):
    """
    Real TUI gateway. Stores requests in ApprovalManager; the TUI polls
    GET /approvals and responds via POST /approvals/{id}/respond.
    Falls back to denying if timeout is set and no response arrives in time.
    """

    def __init__(self, manager: ApprovalManager, timeout: int = 0) -> None:
        self._manager = manager
        self._timeout = timeout  # 0 = wait forever

    async def send_request(self, request: ApprovalRequest) -> None:
        self._manager.register(request)

    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        future = self._manager.register(request)
        try:
            if self._timeout > 0:
                return await asyncio.wait_for(asyncio.shield(future), timeout=self._timeout)
            return await future
        except asyncio.TimeoutError:
            self._manager.cancel(request.request_id)
            return ApprovalResult.DENY
        except asyncio.CancelledError:
            return ApprovalResult.DENY

    async def cancel(self, request_id: str) -> None:
        self._manager.cancel(request_id)

    async def notify(self, event: NotificationEvent) -> None:
        pass
