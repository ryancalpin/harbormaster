from __future__ import annotations
import httpx
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult
from harbormaster.approval.tui_stub import TuiStubGateway
from harbormaster.notification.event import NotificationEvent


class SlackGateway(ApprovalGateway):
    """
    Sends approval requests to a Slack incoming webhook (Block Kit message).
    Since Slack interactive components require an app server, wait_for_response
    falls back to the TUI stub (stdin) after delivering the notification.
    Configure a Slack app with interactivity for full async response support.
    """

    def __init__(self, webhook_url: str, transport=None, timeout: int = 0) -> None:
        self._url = webhook_url
        self._transport = transport
        self._fallback = TuiStubGateway(timeout=timeout)

    async def send_request(self, request: ApprovalRequest) -> None:
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "⚓ Harbormaster Approval"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": (
                f"*Action:* `{request.action.upper()}`\n"
                f"*Port:* `:{request.port}`\n"
                f"*Process:* `{request.process_name or 'unknown'}` (PID {request.pid or '?'})"
            )}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "_Respond Allow/Deny in the terminal where harbormasterd is running._"}},
        ]
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
            await client.post(self._url, json={"blocks": blocks})

    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        return await self._fallback.wait_for_response(request)

    async def cancel(self, request_id: str) -> None:
        await self._fallback.cancel(request_id)

    async def notify(self, event: NotificationEvent) -> None:
        text = f"⚓ Harbormaster `{event.event_type}`: port `:{event.port}` — {event.detail}"
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
            await client.post(self._url, json={"text": text})
