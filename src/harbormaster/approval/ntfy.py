from __future__ import annotations
import asyncio
import json
import httpx
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult


class NtfyGateway(ApprovalGateway):
    """
    Sends approval requests as push notifications via ntfy.sh (or self-hosted).
    Since ntfy has no interactive response mechanism via the publish API,
    wait_for_response polls for a response message on the same topic with the
    request_id. Falls back to DENY after response_timeout seconds.
    """

    def __init__(
        self,
        topic: str,
        server: str = "https://ntfy.sh",
        transport=None,
        response_timeout: float = 0,
    ) -> None:
        self._topic = topic
        self._server = server.rstrip("/")
        self._transport = transport
        self._response_timeout = response_timeout  # 0 = use global approval_timeout

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=10)

    async def send_request(self, request: ApprovalRequest) -> None:
        body = (
            f"Action: {request.action.upper()} on :{request.port}\n"
            f"Process: {request.process_name or 'unknown'} (PID {request.pid or '?'})\n"
            f"ID: {request.request_id[:8]}"
        )
        async with self._make_client() as client:
            await client.post(
                f"{self._server}/{self._topic}",
                content=body.encode(),
                headers={
                    "Title": f"Harbormaster: {request.action} :{request.port}?",
                    "Priority": "high",
                    "Tags": "lock,warning",
                    "Actions": (
                        f"http, Allow, {self._server}/{self._topic}-allow, "
                        f"body=allow&id={request.request_id}; "
                        f"http, Deny, {self._server}/{self._topic}-deny, "
                        f"body=deny&id={request.request_id}"
                    ),
                },
            )

    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        timeout = self._response_timeout if self._response_timeout > 0 else 300
        deadline = asyncio.get_event_loop().time() + timeout
        response_topic = f"{self._topic}-allow"
        async with self._make_client() as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    r = await client.get(
                        f"{self._server}/{response_topic}/json",
                        params={"poll": 1, "since": "1m"},
                        timeout=5,
                    )
                    if r.status_code == 200:
                        for line in r.text.strip().splitlines():
                            try:
                                msg = json.loads(line)
                                if request.request_id in msg.get("message", ""):
                                    return ApprovalResult.ALLOW
                            except Exception:
                                pass
                except Exception:
                    pass
                await asyncio.sleep(2)
        return ApprovalResult.DENY

    async def cancel(self, request_id: str) -> None:
        pass
