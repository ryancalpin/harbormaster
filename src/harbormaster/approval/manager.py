from __future__ import annotations
import asyncio
from harbormaster.approval.base import ApprovalRequest, ApprovalResult


class ApprovalManager:
    """
    In-memory store for pending approval requests.
    Each request is backed by an asyncio.Future so the gateway can await it.
    """

    def __init__(self) -> None:
        self._pending: dict[str, tuple[ApprovalRequest, asyncio.Future[ApprovalResult]]] = {}

    def register(self, request: ApprovalRequest) -> asyncio.Future[ApprovalResult]:
        """Store a pending request and return a Future that resolves when responded."""
        if request.request_id in self._pending:
            return self._pending[request.request_id][1]
        loop = asyncio.get_event_loop()
        future: asyncio.Future[ApprovalResult] = loop.create_future()
        self._pending[request.request_id] = (request, future)
        return future

    def respond(self, request_id: str, result: ApprovalResult) -> bool:
        """Resolve a pending future. Returns False if request_id is unknown."""
        if request_id not in self._pending:
            return False
        _, future = self._pending.pop(request_id)
        if not future.done():
            try:
                future.set_result(result)
            except asyncio.InvalidStateError:
                pass
        return True

    def cancel(self, request_id: str) -> None:
        """Cancel a pending future and remove it."""
        if request_id in self._pending:
            _, future = self._pending.pop(request_id)
            if not future.done():
                future.cancel()

    def list_pending(self) -> list[ApprovalRequest]:
        return [req for req, _ in self._pending.values()]
