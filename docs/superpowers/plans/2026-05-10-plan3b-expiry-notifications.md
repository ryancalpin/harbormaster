# Harbormaster Plan 3b — Port Expiry Notifications

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notify the user via the configured gateway when a reserved port is approaching expiry or a claimed port's process has died.

**Architecture:** A `NotificationEvent` dataclass and `notify()` abstract method are added to the existing gateway hierarchy. A new `ExpiryNotifier` class checks upcoming reservation expirations on each background loop tick and fires fire-and-forget notifications. `ProcessWatcher` is updated to notify before silently removing dead-process records. `parse_ttl` is moved to a shared `utils.py` so config loading can parse the new `notification.lead_time` setting.

**Tech Stack:** Python 3.11+, asyncio, httpx, psutil, existing gateway classes (NtfyGateway, TelegramGateway, WebhookGateway, SlackGateway, DiscordGateway, TuiGateway, TuiStubGateway)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/harbormaster/utils.py` | Create | `parse_ttl` (moved from cli.py) |
| `src/harbormaster/cli.py` | Modify | Re-export `parse_ttl` from utils |
| `src/harbormaster/notification/__init__.py` | Create | Empty package marker |
| `src/harbormaster/notification/event.py` | Create | `NotificationEvent` dataclass |
| `src/harbormaster/notification/expiry_notifier.py` | Create | `ExpiryNotifier` class |
| `src/harbormaster/approval/base.py` | Modify | Add abstract `notify()` method |
| `src/harbormaster/approval/ntfy.py` | Modify | Implement `notify()` |
| `src/harbormaster/approval/telegram.py` | Modify | Implement `notify()` |
| `src/harbormaster/approval/webhook.py` | Modify | Implement `notify()` |
| `src/harbormaster/approval/slack.py` | Modify | Implement `notify()` |
| `src/harbormaster/approval/discord.py` | Modify | Implement `notify()` |
| `src/harbormaster/approval/tui_gateway.py` | Modify | Implement `notify()` (no-op) |
| `src/harbormaster/approval/tui_stub.py` | Modify | Implement `notify()` (no-op) |
| `src/harbormaster/watcher.py` | Modify | Accept `gateway`, call `notify()` before remove |
| `src/harbormaster/config.py` | Modify | Add `notification_lead_time`, parse `[notification]` section |
| `src/harbormaster/daemon.py` | Modify | Create `ExpiryNotifier`, wire watcher gateway, call in loop |
| `tests/test_utils.py` | Create | Tests for `parse_ttl` |
| `tests/test_notification.py` | Create | Tests for `ExpiryNotifier` |
| `tests/test_watcher.py` | Modify | Add notification test |
| `tests/test_gateways.py` | Modify | Add `notify()` tests for each gateway |
| `tests/test_config.py` | Modify | Add `notification_lead_time` config test |

---

### Task 1: Move parse_ttl to utils.py

**Files:**
- Create: `src/harbormaster/utils.py`
- Modify: `src/harbormaster/cli.py`
- Create: `tests/test_utils.py`

`parse_ttl` currently lives in `cli.py`. Config loading needs it too, so move it to a shared module.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_utils.py
import pytest
from harbormaster.utils import parse_ttl


def test_parse_ttl_hours():
    assert parse_ttl("2h") == 7200


def test_parse_ttl_days():
    assert parse_ttl("1d") == 86400


def test_parse_ttl_minutes():
    assert parse_ttl("30m") == 1800


def test_parse_ttl_seconds():
    assert parse_ttl("90s") == 90


def test_parse_ttl_invalid():
    with pytest.raises(ValueError):
        parse_ttl("forever")


def test_parse_ttl_empty():
    with pytest.raises(ValueError):
        parse_ttl("")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_utils.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harbormaster.utils'`

- [ ] **Step 3: Create utils.py with parse_ttl**

```python
# src/harbormaster/utils.py
from __future__ import annotations


def parse_ttl(value: str) -> int:
    """Parse '2h', '1d', '30m', '90s' → seconds. Raises ValueError on bad input."""
    units = {"h": 3600, "d": 86400, "m": 60, "s": 1}
    if value and value[-1] in units:
        try:
            return int(value[:-1]) * units[value[-1]]
        except ValueError:
            pass
    raise ValueError(f"Invalid TTL format: {value!r}. Use e.g. 1h, 8h, 24h, 30m.")
```

- [ ] **Step 4: Update cli.py to import from utils**

In `src/harbormaster/cli.py`, replace the `parse_ttl` function body with a re-export:

```python
from harbormaster.utils import parse_ttl  # re-exported for backwards compatibility
```

Remove the old `parse_ttl` function definition from `cli.py` entirely (the function body starting with `def parse_ttl(value: str) -> int:` through the `raise ValueError` line).

- [ ] **Step 5: Run all tests to verify nothing broke**

```bash
pytest -x -q
```

Expected: all existing tests pass (including the ones in `test_cli.py` that import `parse_ttl` from `harbormaster.cli`).

- [ ] **Step 6: Commit**

```bash
git add src/harbormaster/utils.py src/harbormaster/cli.py tests/test_utils.py
git commit -m "refactor: move parse_ttl to harbormaster.utils, re-export from cli"
```

---

### Task 2: NotificationEvent and notify() abstract method

**Files:**
- Create: `src/harbormaster/notification/__init__.py`
- Create: `src/harbormaster/notification/event.py`
- Modify: `src/harbormaster/approval/base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notification.py
import pytest
from harbormaster.notification.event import NotificationEvent


def test_notification_event_fields():
    event = NotificationEvent(
        event_type="reservation_expiring",
        port=3001,
        detail="expires in 30 minutes",
    )
    assert event.event_type == "reservation_expiring"
    assert event.port == 3001
    assert event.detail == "expires in 30 minutes"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_notification.py::test_notification_event_fields -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create notification package and event**

```python
# src/harbormaster/notification/__init__.py
# (empty)
```

```python
# src/harbormaster/notification/event.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class NotificationEvent:
    event_type: str   # "reservation_expiring" | "process_died"
    port: int
    detail: str       # human-readable context
```

- [ ] **Step 4: Add notify() to ApprovalGateway**

In `src/harbormaster/approval/base.py`, add the import and abstract method. The full updated file:

```python
from __future__ import annotations
import abc
import uuid
from dataclasses import dataclass, field
from enum import Enum

from harbormaster.notification.event import NotificationEvent


class ApprovalResult(Enum):
    ALLOW = "allow"
    DENY = "deny"
    TIMEOUT = "timeout"


@dataclass
class ApprovalRequest:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action: str = ""
    port: int = 0
    pid: int | None = None
    process_name: str | None = None
    requester: str = "unknown"


class ApprovalGateway(abc.ABC):
    @abc.abstractmethod
    async def send_request(self, request: ApprovalRequest) -> None:
        """Deliver the approval prompt to the user."""

    @abc.abstractmethod
    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        """Block until user responds. Return ALLOW, DENY, or TIMEOUT."""

    @abc.abstractmethod
    async def cancel(self, request_id: str) -> None:
        """Called when the requesting agent disconnects before responding."""

    @abc.abstractmethod
    async def notify(self, event: NotificationEvent) -> None:
        """Fire-and-forget notification. No response expected."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """Convenience: send + wait."""
        await self.send_request(request)
        return await self.wait_for_response(request)
```

- [ ] **Step 5: Run tests**

```bash
pytest -x -q
```

Expected: FAIL — all 7 gateway classes are now missing the abstract `notify()` method and can't be instantiated. (This is expected; the next task fixes them all.)

- [ ] **Step 6: Commit event + base (before gateway fixes)**

```bash
git add src/harbormaster/notification/ src/harbormaster/approval/base.py tests/test_notification.py
git commit -m "feat: add NotificationEvent and notify() abstract method to ApprovalGateway"
```

---

### Task 3: Implement notify() in all gateways

**Files:**
- Modify: `src/harbormaster/approval/ntfy.py`
- Modify: `src/harbormaster/approval/telegram.py`
- Modify: `src/harbormaster/approval/webhook.py`
- Modify: `src/harbormaster/approval/slack.py`
- Modify: `src/harbormaster/approval/discord.py`
- Modify: `src/harbormaster/approval/tui_gateway.py`
- Modify: `src/harbormaster/approval/tui_stub.py`
- Modify: `tests/test_gateways.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gateways.py`:

```python
from harbormaster.notification.event import NotificationEvent


async def test_ntfy_notify():
    from harbormaster.approval.ntfy import NtfyGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)
    transport = httpx.MockTransport(handler)
    gw = NtfyGateway(topic="test-topic", server="https://ntfy.sh", transport=transport)
    event = NotificationEvent("reservation_expiring", 3001, "expires in 30 minutes")
    await gw.notify(event)
    assert len(sent) == 1
    assert "test-topic" in str(sent[0].url)


async def test_slack_notify():
    from harbormaster.approval.slack import SlackGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, text="ok")
    transport = httpx.MockTransport(handler)
    gw = SlackGateway(webhook_url="https://hooks.slack.com/test", transport=transport)
    event = NotificationEvent("process_died", 3001, "PID 1234 (node) is gone")
    await gw.notify(event)
    assert len(sent) == 1
    assert "3001" in sent[0]["text"]


async def test_discord_notify():
    from harbormaster.approval.discord import DiscordGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(204)
    transport = httpx.MockTransport(handler)
    gw = DiscordGateway(webhook_url="https://discord.com/api/webhooks/test", transport=transport)
    event = NotificationEvent("reservation_expiring", 8080, "expires in 10 minutes")
    await gw.notify(event)
    assert len(sent) == 1
    assert "embeds" in sent[0]


async def test_webhook_notify():
    from harbormaster.approval.webhook import WebhookGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200)
    transport = httpx.MockTransport(handler)
    gw = WebhookGateway(url="https://example.com/hook", secret="", transport=transport)
    event = NotificationEvent("process_died", 4000, "PID 5678 (python) is gone")
    await gw.notify(event)
    assert len(sent) == 1
    assert sent[0]["event"] == "process_died"
    assert sent[0]["port"] == 4000


async def test_telegram_notify():
    from harbormaster.approval.telegram import TelegramGateway
    sent = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})
    transport = httpx.MockTransport(handler)
    gw = TelegramGateway(bot_token="tok", chat_id="123", transport=transport)
    event = NotificationEvent("reservation_expiring", 3002, "expires in 20 minutes")
    await gw.notify(event)
    assert any("sendMessage" in str(r.url) for r in [])  # verified via sent payloads
    assert len(sent) == 1
    assert "3002" in sent[0]["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_gateways.py -v
```

Expected: FAIL — `TypeError: Can't instantiate abstract class ... with abstract method notify`

- [ ] **Step 3: Add notify() to NtfyGateway**

In `src/harbormaster/approval/ntfy.py`, add the import and method at the end of the class:

```python
from harbormaster.notification.event import NotificationEvent

# inside NtfyGateway class:
async def notify(self, event: NotificationEvent) -> None:
    async with self._make_client() as client:
        await client.post(
            f"{self._server}/{self._topic}",
            content=event.detail.encode(),
            headers={
                "Title": f"Harbormaster: {event.event_type.replace('_', ' ')} :{event.port}",
                "Tags": "harbormaster",
            },
        )
```

- [ ] **Step 4: Add notify() to TelegramGateway**

In `src/harbormaster/approval/telegram.py`, add the import and method:

```python
from harbormaster.notification.event import NotificationEvent

# inside TelegramGateway class:
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
```

- [ ] **Step 5: Add notify() to WebhookGateway**

In `src/harbormaster/approval/webhook.py`, add the import and method:

```python
from harbormaster.notification.event import NotificationEvent

# inside WebhookGateway class:
async def notify(self, event: NotificationEvent) -> None:
    payload = json.dumps({
        "event": event.event_type,
        "port": event.port,
        "detail": event.detail,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if self._secret:
        headers["X-Harbormaster-Signature"] = self._sign(payload)
    async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
        await client.post(self._url, content=payload, headers=headers)
```

- [ ] **Step 6: Add notify() to SlackGateway**

In `src/harbormaster/approval/slack.py`, add the import and method:

```python
from harbormaster.notification.event import NotificationEvent

# inside SlackGateway class:
async def notify(self, event: NotificationEvent) -> None:
    text = f"⚓ Harbormaster `{event.event_type}`: port `:{event.port}` — {event.detail}"
    async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
        await client.post(self._url, json={"text": text})
```

- [ ] **Step 7: Add notify() to DiscordGateway**

In `src/harbormaster/approval/discord.py`, add the import and method:

```python
from harbormaster.notification.event import NotificationEvent

# inside DiscordGateway class:
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
```

- [ ] **Step 8: Add notify() to TuiGateway and TuiStubGateway (no-op)**

In `src/harbormaster/approval/tui_gateway.py`, add import and no-op:

```python
from harbormaster.notification.event import NotificationEvent

# inside TuiGateway class:
async def notify(self, event: NotificationEvent) -> None:
    pass
```

In `src/harbormaster/approval/tui_stub.py`, add import and no-op:

```python
from harbormaster.notification.event import NotificationEvent

# inside TuiStubGateway class:
async def notify(self, event: NotificationEvent) -> None:
    pass
```

- [ ] **Step 9: Run all tests**

```bash
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add src/harbormaster/approval/ tests/test_gateways.py
git commit -m "feat: implement notify() on all approval gateways for fire-and-forget notifications"
```

---

### Task 4: ExpiryNotifier

**Files:**
- Create: `src/harbormaster/notification/expiry_notifier.py`
- Modify: `tests/test_notification.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_notification.py`:

```python
import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta
from harbormaster.notification.expiry_notifier import ExpiryNotifier
from harbormaster.notification.event import NotificationEvent
from harbormaster.models import PortRecord, PortState


@pytest.mark.asyncio
async def test_notifies_when_expiry_within_lead_time():
    db = AsyncMock()
    gateway = AsyncMock()
    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=soon)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)

    gateway.notify.assert_called_once()
    event = gateway.notify.call_args[0][0]
    assert event.event_type == "reservation_expiring"
    assert event.port == 3001


@pytest.mark.asyncio
async def test_does_not_notify_beyond_lead_time():
    db = AsyncMock()
    gateway = AsyncMock()
    far = datetime.now(timezone.utc) + timedelta(hours=5)
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=far)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)

    gateway.notify.assert_not_called()


@pytest.mark.asyncio
async def test_does_not_notify_twice_for_same_port():
    db = AsyncMock()
    gateway = AsyncMock()
    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=soon)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)
    await notifier.check(db, gateway)

    gateway.notify.assert_called_once()


@pytest.mark.asyncio
async def test_skips_permanent_reservations():
    db = AsyncMock()
    gateway = AsyncMock()
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=None)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)

    gateway.notify.assert_not_called()


@pytest.mark.asyncio
async def test_clears_notified_set_when_reservation_gone():
    db = AsyncMock()
    gateway = AsyncMock()
    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    record = PortRecord(port=3001, state=PortState.RESERVED, reserved_until=soon)
    db.list_ports.return_value = [record]

    notifier = ExpiryNotifier(lead_time_seconds=3600)
    await notifier.check(db, gateway)
    assert gateway.notify.call_count == 1

    # Reservation is gone (expired or unreserved)
    db.list_ports.return_value = []
    await notifier.check(db, gateway)

    # Port 3001 no longer in _notified, so if it comes back it would notify again
    assert 3001 not in notifier._notified
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_notification.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harbormaster.notification.expiry_notifier'`

- [ ] **Step 3: Implement ExpiryNotifier**

```python
# src/harbormaster/notification/expiry_notifier.py
from __future__ import annotations
import logging
from datetime import datetime, timezone

from harbormaster.approval.base import ApprovalGateway
from harbormaster.models import PortState
from harbormaster.notification.event import NotificationEvent
from harbormaster.state import StateDB

logger = logging.getLogger("harbormaster")


class ExpiryNotifier:
    def __init__(self, lead_time_seconds: int) -> None:
        self._lead_time = lead_time_seconds
        self._notified: set[int] = set()

    async def check(self, db: StateDB, gateway: ApprovalGateway) -> None:
        now = datetime.now(timezone.utc)
        records = await db.list_ports()
        active_reserved = {r.port for r in records if r.state == PortState.RESERVED}

        # Clear notified entries for ports no longer reserved
        self._notified &= active_reserved

        for record in records:
            if record.state != PortState.RESERVED:
                continue
            if record.reserved_until is None:
                continue  # permanent reservation — no expiry to warn about
            if record.port in self._notified:
                continue
            delta = (record.reserved_until - now).total_seconds()
            if 0 < delta <= self._lead_time:
                minutes = max(1, int(delta / 60))
                detail = f"expires in {minutes} minute{'s' if minutes != 1 else ''}"
                event = NotificationEvent("reservation_expiring", record.port, detail)
                try:
                    await gateway.notify(event)
                except Exception as exc:
                    logger.warning("Notification failed for port %d: %s", record.port, exc)
                self._notified.add(record.port)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_notification.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/notification/expiry_notifier.py tests/test_notification.py
git commit -m "feat: add ExpiryNotifier for reservation expiry warnings"
```

---

### Task 5: ProcessWatcher notification

**Files:**
- Modify: `src/harbormaster/watcher.py`
- Modify: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_watcher.py`. First read the current contents to understand existing test structure, then add:

```python
import pytest
from unittest.mock import AsyncMock, patch
from harbormaster.models import PortRecord, PortState
from harbormaster.watcher import ProcessWatcher
from harbormaster.notification.event import NotificationEvent


@pytest.mark.asyncio
async def test_notifies_before_removing_dead_process():
    db = AsyncMock()
    gateway = AsyncMock()
    record = PortRecord(port=3001, state=PortState.CLAIMED, pid=99999, process_name="dead-process")

    with patch("psutil.pid_exists", return_value=False):
        watcher = ProcessWatcher(db, gateway=gateway)
        await watcher._check_record(record)

    gateway.notify.assert_called_once()
    event = gateway.notify.call_args[0][0]
    assert event.event_type == "process_died"
    assert event.port == 3001
    assert "dead-process" in event.detail
    db.remove_port.assert_called_once_with(3001)


@pytest.mark.asyncio
async def test_no_notification_without_gateway():
    db = AsyncMock()
    record = PortRecord(port=3001, state=PortState.CLAIMED, pid=99999, process_name="dead-process")

    with patch("psutil.pid_exists", return_value=False):
        watcher = ProcessWatcher(db, gateway=None)
        await watcher._check_record(record)

    db.remove_port.assert_called_once_with(3001)  # still removes
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_watcher.py::test_notifies_before_removing_dead_process tests/test_watcher.py::test_no_notification_without_gateway -v
```

Expected: FAIL — `ProcessWatcher.__init__` does not accept `gateway` parameter.

- [ ] **Step 3: Update ProcessWatcher**

Replace the full content of `src/harbormaster/watcher.py`:

```python
from __future__ import annotations
import logging
import psutil
from harbormaster.approval.base import ApprovalGateway
from harbormaster.models import PortRecord, PortState
from harbormaster.notification.event import NotificationEvent
from harbormaster.state import StateDB

logger = logging.getLogger("harbormaster")


class ProcessWatcher:
    """Monitors registered PIDs and cleans up state when processes exit."""

    def __init__(self, db: StateDB, gateway: ApprovalGateway | None = None) -> None:
        self._db = db
        self._gateway = gateway

    async def check_all(self) -> None:
        records = await self._db.list_ports()
        for record in records:
            if record.state == PortState.LOCKED:
                continue
            if record.pid is None:
                continue
            await self._check_record(record)

    async def _check_record(self, record: PortRecord) -> None:
        if not psutil.pid_exists(record.pid):
            if self._gateway is not None:
                detail = f"PID {record.pid} ({record.process_name or 'unknown'}) is gone"
                event = NotificationEvent("process_died", record.port, detail)
                try:
                    await self._gateway.notify(event)
                except Exception as exc:
                    logger.warning("Notification failed for port %d: %s", record.port, exc)
            await self._db.remove_port(record.port)
            return
        try:
            proc = psutil.Process(record.pid)
            current_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            if self._gateway is not None:
                detail = f"PID {record.pid} ({record.process_name or 'unknown'}) is gone"
                event = NotificationEvent("process_died", record.port, detail)
                try:
                    await self._gateway.notify(event)
                except Exception as exc:
                    logger.warning("Notification failed for port %d: %s", record.port, exc)
            await self._db.remove_port(record.port)
            return
        if current_name != record.process_name:
            updated = PortRecord(
                port=record.port,
                state=record.state,
                pid=record.pid,
                process_name=current_name,
            )
            await self._db.set_port(updated)
```

- [ ] **Step 4: Run all tests**

```bash
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/watcher.py tests/test_watcher.py
git commit -m "feat: notify gateway before removing dead-process port records"
```

---

### Task 6: Config — notification_lead_time

**Files:**
- Modify: `src/harbormaster/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_notification_lead_time_default(tmp_path):
    from harbormaster.config import load_config
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.notification_lead_time == 3600  # default 1 hour


def test_notification_lead_time_from_toml(tmp_path):
    import tomli_w
    from harbormaster.config import load_config
    config_file = tmp_path / "config.toml"
    data = {"notification": {"lead_time": "30m"}}
    with open(config_file, "wb") as f:
        tomli_w.dump(data, f)
    cfg = load_config(config_file)
    assert cfg.notification_lead_time == 1800


def test_notification_lead_time_integer_toml(tmp_path):
    import tomli_w
    from harbormaster.config import load_config
    config_file = tmp_path / "config.toml"
    data = {"notification": {"lead_time": 7200}}
    with open(config_file, "wb") as f:
        tomli_w.dump(data, f)
    cfg = load_config(config_file)
    assert cfg.notification_lead_time == 7200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: FAIL — `HarbormasterConfig` has no `notification_lead_time` attribute.

- [ ] **Step 3: Update config.py**

In `src/harbormaster/config.py`:

Add `from harbormaster.utils import parse_ttl` at the top of imports.

Add `notification_lead_time: int = 3600` to `HarbormasterConfig`:

```python
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
    approval_timeout: int = 0
    notification_lead_time: int = 3600
    telegram: GatewayTelegramConfig = field(default_factory=GatewayTelegramConfig)
    ntfy: GatewayNtfyConfig = field(default_factory=GatewayNtfyConfig)
    webhook: GatewayWebhookConfig = field(default_factory=GatewayWebhookConfig)
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""
```

In `load_config`, add after the `approval` section parsing:

```python
notif = data.get("notification", {})
lead_time_raw = notif.get("lead_time", 3600)
if isinstance(lead_time_raw, str):
    cfg.notification_lead_time = parse_ttl(lead_time_raw)
else:
    cfg.notification_lead_time = int(lead_time_raw)
```

In `save_config`, add `"notification"` key to the data dict:

```python
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
    "notification": {
        "lead_time": cfg.notification_lead_time,
    },
    "gateways": {
        "telegram": {"bot_token": cfg.telegram.bot_token, "chat_id": cfg.telegram.chat_id},
        "ntfy": {"topic": cfg.ntfy.topic, "server": cfg.ntfy.server},
        "webhook": {"url": cfg.webhook.url, "secret": cfg.webhook.secret},
        "discord": {"webhook_url": cfg.discord_webhook_url},
        "slack": {"webhook_url": cfg.slack_webhook_url},
    },
}
```

- [ ] **Step 4: Run all tests**

```bash
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/config.py tests/test_config.py
git commit -m "feat: add notification_lead_time config option (default 1h)"
```

---

### Task 7: Daemon wiring

**Files:**
- Modify: `src/harbormaster/daemon.py`

Wire `ExpiryNotifier` into the daemon's `__init__` and `_background_loop`, and pass `gateway` to `ProcessWatcher`.

- [ ] **Step 1: Update daemon.py imports**

At the top of `src/harbormaster/daemon.py`, add:

```python
from harbormaster.notification.expiry_notifier import ExpiryNotifier
```

- [ ] **Step 2: Update HarbormasterDaemon.__init__**

In `__init__`, replace:

```python
self.watcher = ProcessWatcher(self.db)
```

with:

```python
self.watcher = ProcessWatcher(self.db, gateway=self.gateway)
```

And add after `self.watcher`:

```python
self.notifier = ExpiryNotifier(lead_time_seconds=self.cfg.notification_lead_time)
```

- [ ] **Step 3: Update _background_loop**

In `_background_loop`, add the notifier call after `self.watcher.check_all()`:

```python
async def _background_loop(self) -> None:
    tailscale_tick = 0
    while True:
        await asyncio.sleep(2)
        try:
            live = await self.scanner.scan()
            await self.scanner.reconcile(live)
            await self.watcher.check_all()
            await self.notifier.check(self.db, self.gateway)
            self.holds.expire_stale()
            tailscale_tick += 1
            if tailscale_tick >= 15:
                tailscale_tick = 0
                await self.tailscale.detect()
        except Exception as e:
            logger.exception(f"Background loop error: {e}")
```

- [ ] **Step 4: Run all tests**

```bash
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/daemon.py
git commit -m "feat: wire ExpiryNotifier and gateway-aware ProcessWatcher into daemon loop"
```

---

## Self-Review Checklist

- [ ] All spec sections have a corresponding task
- [ ] No TBD/TODO/placeholder in any step
- [ ] `parse_ttl` moved to `utils.py` before `config.py` tries to import it (Task 1 before Task 6)
- [ ] `notify()` added to base before implementing in subclasses (Task 2 before Task 3)
- [ ] `ProcessWatcher(db, gateway=self.gateway)` in daemon matches updated signature (Task 5 before Task 7)
- [ ] `ExpiryNotifier` imported and instantiated in daemon after being defined (Task 4 before Task 7)
- [ ] `_notified &= active_reserved` correctly prunes the notified set (not `-=`)
- [ ] Error handling in both `ExpiryNotifier.check` and `ProcessWatcher._check_record`: exceptions logged as WARNING, never re-raised
