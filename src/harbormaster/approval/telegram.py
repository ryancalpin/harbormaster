from __future__ import annotations
import asyncio
import time
import httpx
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult
from harbormaster.notification.event import NotificationEvent

TELEGRAM_API = "https://api.telegram.org"


class TelegramGateway(ApprovalGateway):
    """
    Sends approval requests as Telegram bot messages with inline buttons.
    Polls getUpdates to detect the user's callback response.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        transport=None,
        response_timeout: float = 0,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._transport = transport
        self._response_timeout = response_timeout
        self._last_update_id: int = 0

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{TELEGRAM_API}/bot{self._token}",
            transport=self._transport,
            timeout=15,
        )

    async def send_request(self, request: ApprovalRequest) -> None:
        text = (
            f"⚓ *Harbormaster Approval*\n"
            f"Action: `{request.action.upper()}`\n"
            f"Port: `:{request.port}`\n"
            f"Process: `{request.process_name or 'unknown'}` (PID {request.pid or '?'})"
        )
        if request.requester:
            text += f"\n⚠️ {request.requester}"
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Allow", "callback_data": f"allow:{request.request_id}"},
                {"text": "❌ Deny", "callback_data": f"deny:{request.request_id}"},
            ]]
        }
        async with self._make_client() as client:
            await client.post("/sendMessage", json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": keyboard,
            })

    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        timeout = self._response_timeout if self._response_timeout > 0 else 300
        deadline = time.monotonic() + timeout
        async with self._make_client() as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get("/getUpdates", params={
                        "offset": self._last_update_id + 1,
                        "timeout": min(5, int(deadline - time.monotonic())),
                        "allowed_updates": ["callback_query"],
                    })
                    if r.status_code == 200:
                        for update in r.json().get("result", []):
                            self._last_update_id = max(self._last_update_id, update["update_id"])
                            cb = update.get("callback_query", {})
                            data = cb.get("data", "")
                            if f":{request.request_id}" in data:
                                action = data.split(":")[0]
                                await client.post("/answerCallbackQuery", json={
                                    "callback_query_id": cb["id"],
                                    "text": "Responded.",
                                })
                                return ApprovalResult.ALLOW if action == "allow" else ApprovalResult.DENY
                except Exception:
                    await asyncio.sleep(2)
        return ApprovalResult.DENY

    async def cancel(self, request_id: str) -> None:
        pass

    async def notify(self, event: NotificationEvent) -> None:
        text = (
            f"⚓ *Harbormaster Notification*\n"
            f"Event: `{event.event_type}`\n"
            f"Port: `:{event.port}`\n"
            f"{event.detail}"
        )
        async with self._make_client() as client:
            await client.post("/sendMessage", json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })
