from __future__ import annotations
import os
import secrets
import tomllib
import tomli_w
from dataclasses import dataclass, field
from pathlib import Path


def _default_secret() -> str:
    return secrets.token_hex(32)


@dataclass
class GatewayTelegramConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class GatewayNtfyConfig:
    topic: str = "harbormaster"
    server: str = "https://ntfy.sh"


@dataclass
class GatewayWebhookConfig:
    url: str = ""
    secret: str = ""


@dataclass
class HarbormasterConfig:
    api_port: int = 19191
    secret: str = field(default_factory=_default_secret)
    watch_range: tuple[int, int] = (1024, 49151)
    display_priority_ranges: list[str] = field(
        default_factory=lambda: ["3000-3999", "4000-4999", "5000-5999", "8000-8999", "9000-9999"]
    )
    approval_gateway: str = "tui"
    approval_fallback: str = "tui"
    approval_timeout: int = 0  # 0 = wait indefinitely
    telegram: GatewayTelegramConfig = field(default_factory=GatewayTelegramConfig)
    ntfy: GatewayNtfyConfig = field(default_factory=GatewayNtfyConfig)
    webhook: GatewayWebhookConfig = field(default_factory=GatewayWebhookConfig)
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""


def _default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(xdg) / "harbormaster" / "config.toml"


def _default_db_path() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return Path(xdg) / "harbormaster" / "state.db"


def load_config(path: Path | None = None) -> HarbormasterConfig:
    if path is None:
        path = _default_config_path()
    if not path.exists():
        cfg = HarbormasterConfig()
        save_config(cfg, path)
        return cfg
    with open(path, "rb") as f:
        data = tomllib.load(f)
    cfg = HarbormasterConfig()
    cfg.api_port = data.get("daemon", {}).get("api_port", cfg.api_port)
    cfg.secret = data.get("daemon", {}).get("secret", cfg.secret)
    cfg.approval_gateway = data.get("approval", {}).get("gateway", cfg.approval_gateway)
    cfg.approval_fallback = data.get("approval", {}).get("fallback", cfg.approval_fallback)
    cfg.approval_timeout = data.get("approval", {}).get("timeout", cfg.approval_timeout)
    ports = data.get("ports", {})
    if "watch_range" in ports:
        cfg.watch_range = tuple(ports["watch_range"])
    if "display_priority" in ports:
        cfg.display_priority_ranges = ports["display_priority"]
    tg = data.get("gateways", {}).get("telegram", {})
    cfg.telegram = GatewayTelegramConfig(
        bot_token=tg.get("bot_token", ""),
        chat_id=tg.get("chat_id", ""),
    )
    ntfy = data.get("gateways", {}).get("ntfy", {})
    cfg.ntfy = GatewayNtfyConfig(
        topic=ntfy.get("topic", "harbormaster"),
        server=ntfy.get("server", "https://ntfy.sh"),
    )
    wh = data.get("gateways", {}).get("webhook", {})
    cfg.webhook = GatewayWebhookConfig(
        url=wh.get("url", ""),
        secret=wh.get("secret", ""),
    )
    cfg.discord_webhook_url = data.get("gateways", {}).get("discord", {}).get("webhook_url", "")
    cfg.slack_webhook_url = data.get("gateways", {}).get("slack", {}).get("webhook_url", "")
    return cfg


def save_config(cfg: HarbormasterConfig, path: Path | None = None) -> None:
    if path is None:
        path = _default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "daemon": {"api_port": cfg.api_port, "secret": cfg.secret},
        "ports": {
            "watch_range": list(cfg.watch_range),
            "display_priority": cfg.display_priority_ranges,
        },
        "approval": {
            "gateway": cfg.approval_gateway,
            "fallback": cfg.approval_fallback,
            "timeout": cfg.approval_timeout,
        },
        "gateways": {
            "telegram": {"bot_token": cfg.telegram.bot_token, "chat_id": cfg.telegram.chat_id},
            "ntfy": {"topic": cfg.ntfy.topic, "server": cfg.ntfy.server},
            "webhook": {"url": cfg.webhook.url, "secret": cfg.webhook.secret},
            "discord": {"webhook_url": cfg.discord_webhook_url},
            "slack": {"webhook_url": cfg.slack_webhook_url},
        },
    }
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
