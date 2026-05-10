from __future__ import annotations
import logging
from harbormaster.approval.base import ApprovalGateway
from harbormaster.approval.manager import ApprovalManager
from harbormaster.config import HarbormasterConfig


def build_gateway(cfg: HarbormasterConfig, manager: ApprovalManager) -> ApprovalGateway:
    """Instantiate the correct gateway from config."""
    name = cfg.approval_gateway
    timeout = cfg.approval_timeout

    if name == "tui":
        from harbormaster.approval.tui_gateway import TuiGateway
        return TuiGateway(manager, timeout=timeout)

    if name == "ntfy":
        from harbormaster.approval.ntfy import NtfyGateway
        return NtfyGateway(
            topic=cfg.ntfy.topic,
            server=cfg.ntfy.server,
            response_timeout=timeout,
        )

    if name == "telegram":
        if not cfg.telegram.bot_token or not cfg.telegram.chat_id:
            raise ValueError("Telegram gateway requires [gateways.telegram] bot_token and chat_id in config.")
        from harbormaster.approval.telegram import TelegramGateway
        return TelegramGateway(
            bot_token=cfg.telegram.bot_token,
            chat_id=cfg.telegram.chat_id,
            response_timeout=timeout,
        )

    if name == "webhook":
        if not cfg.webhook.url:
            raise ValueError("Webhook gateway requires [gateways.webhook] url in config.")
        from harbormaster.approval.webhook import WebhookGateway
        return WebhookGateway(
            url=cfg.webhook.url,
            secret=cfg.webhook.secret,
            response_timeout=timeout,
        )

    if name == "slack":
        if not cfg.slack_webhook_url:
            raise ValueError("Slack gateway requires [gateways.slack] webhook_url in config.")
        from harbormaster.approval.slack import SlackGateway
        return SlackGateway(webhook_url=cfg.slack_webhook_url, timeout=timeout)

    if name == "discord":
        if not cfg.discord_webhook_url:
            raise ValueError("Discord gateway requires [gateways.discord] webhook_url in config.")
        from harbormaster.approval.discord import DiscordGateway
        return DiscordGateway(webhook_url=cfg.discord_webhook_url, timeout=timeout)

    logging.getLogger("harbormaster").warning(
        f"Unknown approval gateway {name!r} — falling back to TUI stub"
    )
    from harbormaster.approval.tui_stub import TuiStubGateway
    return TuiStubGateway(timeout=timeout)
