# Harbormaster Plan 3b Design — Port Expiry Notifications

**Date:** 2026-05-10
**Status:** Approved

---

## Scope

Add a notification-only (no approval) code path to the daemon that fires when:

1. A reserved port is approaching its expiry time (configurable lead time, default 1 hour)
2. A claimed port's process has died (notify then remove — existing silent-remove behavior, with a notification prepended)

Notifications go through the same gateway already configured for approvals. No separate notification gateway config.

---

## Architecture

### NotificationEvent

A new dataclass in `src/harbormaster/notification/event.py`:

```python
@dataclass
class NotificationEvent:
    event_type: str          # "reservation_expiring" | "process_died"
    port: int
    detail: str              # human-readable context (e.g. "expires in 45 minutes", "PID 1234 (node) is gone")
```

### NotificationGateway interface

`ApprovalGateway` (in `src/harbormaster/approval/base.py`) gains one new abstract method:

```python
@abc.abstractmethod
async def notify(self, event: NotificationEvent) -> None:
    ...
```

Every existing gateway subclass (`NtfyGateway`, `TelegramGateway`, `WebhookGateway`, `SlackGateway`, `DiscordGateway`, `TuiGateway`, `TuiStubGateway`) gets a `notify` implementation. Notification is fire-and-forget — no `wait_for_response`, no `ApprovalManager` involvement.

### ExpiryNotifier

New class in `src/harbormaster/notification/expiry_notifier.py`:

```python
class ExpiryNotifier:
    def __init__(self, lead_time_seconds: int):
        self._lead_time = lead_time_seconds
        self._notified: set[int] = set()   # ports already warned; cleared when reservation gone

    async def check(self, db: StateDB, gateway: ApprovalGateway) -> None:
        ...
```

On each call:
1. Query all `reserved` ports from `db.list_ports()`
2. For each port where `reserved_until` is within `now + lead_time_seconds` (and not already expired):
   - Skip if `port` is already in `self._notified`
   - Call `gateway.notify(NotificationEvent("reservation_expiring", port, detail))`
   - Add `port` to `self._notified`
3. Remove ports from `self._notified` whose reservation no longer exists in the DB (expired or unreserved)

### ProcessWatcher changes

`ProcessWatcher._check_record` currently calls `db.remove_port(record.port)` when a process is gone. It gains an optional `gateway: ApprovalGateway | None` parameter. If provided, it calls `gateway.notify(NotificationEvent("process_died", port, detail))` immediately before removing the record.

### Daemon integration

`HarbormasterDaemon.__init__` creates an `ExpiryNotifier(lead_time_seconds=cfg.notification_lead_time)`.

`_background_loop` gains one new call:

```python
await self.notifier.check(self.db, self.gateway)
```

`ProcessWatcher` is instantiated with `gateway=self.gateway` so it can notify on process death.

---

## Configuration

New section in `config.toml` (and `HarbormasterConfig`):

```toml
[notification]
lead_time = "1h"    # how far ahead to warn about expiring reservations; parsed as TTL (e.g. 30m, 2h, 1d)
```

`HarbormasterConfig` gains:
- `notification_lead_time: int = 3600`  (seconds, default 1 hour)

`load_config` and `save_config` updated to read/write `[notification].lead_time`.

`lead_time` is parsed with the existing `parse_ttl` function from `cli.py` (or a shared utility — see note below).

---

## Gateway Implementations

### ntfy

POST to `{server}/{topic}` with:
- `Title: Harbormaster — {event_type}`
- Body: `detail`

### Telegram

`sendMessage` to `chat_id` with text: `"[Harbormaster] {event_type}: port {port} — {detail}"`

### Webhook

POST JSON to configured URL:
```json
{"event": "reservation_expiring", "port": 3001, "detail": "expires in 45 minutes"}
```

No HMAC signing on notifications (signing is a future hardening item).

### Slack / Discord

POST to webhook URL with `{"text": "[Harbormaster] {event_type}: port {port} — {detail}"}`.

### TUI gateway

No-op (`pass`). The TUI already shows live port state with `reserved_until` timestamps; a separate notification is redundant and the gateway may not be active.

### TuiStubGateway

No-op (`pass`).

---

## parse_ttl placement

`parse_ttl` currently lives in `src/harbormaster/cli.py`. Config loading (`config.py`) needs it to parse `lead_time`. Move `parse_ttl` to `src/harbormaster/utils.py` and import it in both `cli.py` and `config.py`.

---

## Error Handling

If `gateway.notify()` raises an exception (e.g. network failure sending to ntfy), log the error at `WARNING` level and continue. A failed notification must never crash the daemon or interrupt the background loop.

---

## Testing Strategy

- Unit tests for `ExpiryNotifier.check`: mock `StateDB` and `ApprovalGateway`, assert `notify` called with correct event when reservation within lead time, not called for far-future reservations, not called twice for the same port.
- Unit test for `ProcessWatcher._check_record` with gateway: assert `notify` called before `remove_port` when process is gone.
- Unit tests for each gateway's `notify` method: mock HTTP calls, assert correct payload sent.
- No integration tests for notifications (covered by the existing integration fixture in Plan 3a).

---

## Out of Scope

- Separate `notification_gateway` config key (same gateway as approval)
- TUI banner/toast for notifications (TUI shows live state already)
- HMAC signing on webhook notifications (future hardening)
- Notification deduplication across daemon restarts (in-memory only; fine for the use case)
