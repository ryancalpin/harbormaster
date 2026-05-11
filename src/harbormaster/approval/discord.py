from __future__ import annotations
import httpx
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult
from harbormaster.approval.tui_stub import TuiStubGateway
from harbormaster.notification.event import NotificationEvent


class DiscordGateway(ApprovalGateway):
    """
    Sends approval requests to a Discord webhook.
    Like SlackGateway, interactive responses require a Discord bot setup,
    so wait_for_response falls back to the TUI stub.
    """

    def __init__(self, webhook_url: str, transport=None, timeout: int = 0) -> None:
        self._url = webhook_url
        self._transport = transport
        self._fallback = TuiStubGateway(timeout=timeout)

    async def send_request(self, request: ApprovalRequest) -> None:
        embed = {
            "title": "⚓ Harbormaster Approval Required",
            "color": 0xF0883E,
            "fields": [
                {"name": "Action", "value": f"`{request.action.upper()}`", "inline": True},
                {"name": "Port", "value": f"`:{request.port}`", "inline": True},
                {"name": "Process", "value": f"`{request.process_name or 'unknown'}` PID {request.pid or '?'}", "inline": False},
            ],
            "footer": {"text": "Respond in the terminal where harbormasterd is running"},
        }
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
            await client.post(self._url, json={"embeds": [embed]})

    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        return await self._fallback.wait_for_response(request)

    async def cancel(self, request_id: str) -> None:
        await self._fallback.cancel(request_id)

    async def notify(self, event: NotificationEvent) -> None:
        embed = {
            "title": f"⚓ Harbormaster: {event.event_type.replace('_', ' ')}",
            "color": 0xF0883E,
            "fields": [
                {"name": "Port", "value": f"`:{event.port}`", "inline": True},
                {"name": "Detail", "value": event.detail, "inline": False},
            ],
        }
        async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
            await client.post(self._url, json={"embeds": [embed]})
