import pytest
import asyncio
import json
import httpx
from harbormaster.approval.base import ApprovalRequest, ApprovalResult


def make_ntfy_transport(response_body: str, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=response_body)
    return httpx.MockTransport(handler)


async def test_ntfy_send_request():
    from harbormaster.approval.ntfy import NtfyGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)
    transport = httpx.MockTransport(handler)
    gw = NtfyGateway(topic="test-topic", server="https://ntfy.sh", transport=transport)
    req = ApprovalRequest(action="lock", port=3000, process_name="node", pid=1234)
    await gw.send_request(req)
    assert len(sent) == 1
    assert "test-topic" in str(sent[0].url)


async def test_ntfy_wait_for_response_times_out():
    from harbormaster.approval.ntfy import NtfyGateway
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    gw = NtfyGateway(topic="test", server="https://ntfy.sh", transport=transport, response_timeout=0.1)
    req = ApprovalRequest(action="lock", port=3000)
    await gw.send_request(req)
    result = await gw.wait_for_response(req)
    assert result == ApprovalResult.DENY


async def test_webhook_send_and_deny():
    from harbormaster.approval.webhook import WebhookGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, text="deny")
    transport = httpx.MockTransport(handler)
    gw = WebhookGateway(url="https://example.com/hook", secret="", transport=transport, response_timeout=0.5)
    req = ApprovalRequest(action="lock", port=3000)
    await gw.send_request(req)
    result = await gw.wait_for_response(req)
    assert result == ApprovalResult.DENY
    assert sent[0]["action"] == "lock"


async def test_slack_send():
    from harbormaster.approval.slack import SlackGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, text="ok")
    transport = httpx.MockTransport(handler)
    gw = SlackGateway(webhook_url="https://hooks.slack.com/test", transport=transport)
    req = ApprovalRequest(action="evict", port=8080, process_name="python3", pid=999)
    await gw.send_request(req)
    assert len(sent) == 1


async def test_discord_send():
    from harbormaster.approval.discord import DiscordGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(204)
    transport = httpx.MockTransport(handler)
    gw = DiscordGateway(webhook_url="https://discord.com/api/webhooks/test", transport=transport)
    req = ApprovalRequest(action="lock", port=5000)
    await gw.send_request(req)
    assert len(sent) == 1
