from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import time
import httpx
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult


class WebhookGateway(ApprovalGateway):
    """
    POSTs approval request to a configured URL (HMAC-signed).
    The endpoint must respond with body 'allow' or 'deny' to the same POST.
    """

    def __init__(
        self,
        url: str,
        secret: str,
        transport=None,
        response_timeout: float = 0,
    ) -> None:
        self._url = url
        self._secret = secret
        self._transport = transport
        self._response_timeout = response_timeout
        self._responses: dict[str, ApprovalResult] = {}

    def _sign(self, body: bytes) -> str:
        return hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()

    async def send_request(self, request: ApprovalRequest) -> None:
        payload = json.dumps({
            "request_id": request.request_id,
            "action": request.action,
            "port": request.port,
            "pid": request.pid,
            "process_name": request.process_name,
            "requester": request.requester,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self._secret:
            headers["X-Harbormaster-Signature"] = self._sign(payload)
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
            r = await client.post(self._url, content=payload, headers=headers)
            body = r.text.strip().lower()
            if body in ("allow", "deny"):
                self._responses[request.request_id] = (
                    ApprovalResult.ALLOW if body == "allow" else ApprovalResult.DENY
                )

    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        timeout = self._response_timeout if self._response_timeout > 0 else 300
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if request.request_id in self._responses:
                return self._responses.pop(request.request_id)
            await asyncio.sleep(0.1)
        return ApprovalResult.DENY

    async def cancel(self, request_id: str) -> None:
        self._responses.pop(request_id, None)
