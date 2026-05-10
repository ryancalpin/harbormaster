# Harbormaster Daemon — Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `harbormasterd` — a systemd user daemon that holds socket locks on ports, persists state in SQLite, exposes a Starlette HTTP API with shared-secret auth, auto-registers in-use ports, watches for process death, detects Tailscale, and routes approval requests through a pluggable gateway.

**Architecture:** Single async Python process. `LockEngine` holds raw sockets. `StateDB` persists to SQLite. `PortScanner` reconciles live psutil state with DB every 2-3s. `ProcessWatcher` checks registered PIDs for exit. `NegotiationHolds` tracks in-memory short-lived port holds. `Starlette` serves the HTTP API on `127.0.0.1:19191`. All components wired together in `HarbormasterDaemon`.

**Tech Stack:** Python 3.11+, Starlette, uvicorn, psutil, aiosqlite, pytest, pytest-asyncio, httpx (test client)

---

## File Structure

```
harbormaster/
├── pyproject.toml
├── systemd/
│   └── harbormaster.service
├── src/
│   └── harbormaster/
│       ├── __init__.py
│       ├── config.py          # load/save config.toml, generate secret
│       ├── models.py          # PortRecord, PortState enum, LivePort
│       ├── state.py           # SQLite CRUD via aiosqlite
│       ├── lock_engine.py     # socket holding (lock/unlock/re-acquire)
│       ├── scanner.py         # psutil scan + auto-registration reconciliation
│       ├── watcher.py         # process death + PID recycle detection
│       ├── negotiation.py     # in-memory holds with TTL
│       ├── tailscale.py       # tailscale status --json parsing + reconnect
│       ├── approval/
│       │   ├── __init__.py
│       │   ├── base.py        # ApprovalGateway ABC
│       │   └── tui_stub.py    # TUI gateway stub (blocks, logs; real TUI in Plan 2)
│       ├── api.py             # Starlette routes + auth middleware
│       └── daemon.py          # HarbormasterDaemon startup/shutdown orchestration
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_models.py
    ├── test_state.py
    ├── test_lock_engine.py
    ├── test_scanner.py
    ├── test_watcher.py
    ├── test_negotiation.py
    ├── test_tailscale.py
    └── test_api.py
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/harbormaster/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "setuptools-scm"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "harbormaster"
version = "0.1.0"
description = "Port allocation daemon for developers and AI agents"
requires-python = ">=3.11"
dependencies = [
    "starlette>=0.41",
    "uvicorn>=0.32",
    "psutil>=6.0",
    "aiosqlite>=0.20",
    "httpx>=0.27",
]

[project.scripts]
harbormasterd = "harbormaster.daemon:main"

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create package init and conftest**

`src/harbormaster/__init__.py` — empty file.

`tests/conftest.py`:
```python
import pytest
import asyncio

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()
```

- [ ] **Step 3: Install in dev mode**

```bash
cd ~/projects/harbormaster
pip install -e ".[dev]"
```

Expected: installs without errors, `harbormasterd` command available.

- [ ] **Step 4: Verify pytest runs**

```bash
pytest tests/ -v
```

Expected: `no tests ran` or `0 passed` — no errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat: project scaffold with pyproject.toml and test setup"
```

---

## Task 2: Models

**Files:**
- Create: `src/harbormaster/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

`tests/test_models.py`:
```python
from harbormaster.models import PortState, PortRecord, LivePort
from datetime import datetime, timezone

def test_port_state_values():
    assert PortState.OPEN.value == "open"
    assert PortState.RESERVED.value == "reserved"
    assert PortState.IN_USE.value == "in-use"
    assert PortState.CLAIMED.value == "claimed"
    assert PortState.LOCKED.value == "locked"

def test_port_record_defaults():
    record = PortRecord(port=3000, state=PortState.OPEN)
    assert record.port == 3000
    assert record.pid is None
    assert record.process_name is None
    assert record.reserved_until is None

def test_live_port_fields():
    lp = LivePort(port=3000, pid=1234, process_name="node", is_listen=True, interface="127.0.0.1")
    assert lp.port == 3000
    assert lp.is_listen is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError: cannot import name 'PortState'`

- [ ] **Step 3: Implement models**

`src/harbormaster/models.py`:
```python
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from datetime import datetime


class PortState(enum.Enum):
    OPEN = "open"
    RESERVED = "reserved"
    IN_USE = "in-use"
    CLAIMED = "claimed"
    LOCKED = "locked"


@dataclass
class PortRecord:
    port: int
    state: PortState
    pid: int | None = None
    process_name: str | None = None
    reserved_until: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "state": self.state.value,
            "pid": self.pid,
            "process_name": self.process_name,
            "reserved_until": self.reserved_until.isoformat() if self.reserved_until else None,
        }


@dataclass
class LivePort:
    port: int
    pid: int
    process_name: str
    is_listen: bool          # True = LISTEN (incoming), False = ESTABLISHED (outgoing)
    interface: str           # bound IP address, e.g. "127.0.0.1" or "100.x.x.x"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_models.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/models.py tests/test_models.py
git commit -m "feat: port state models (PortState, PortRecord, LivePort)"
```

---

## Task 3: Config Module

**Files:**
- Create: `src/harbormaster/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

`tests/test_config.py`:
```python
import pytest
import tomllib
from pathlib import Path
from harbormaster.config import HarbormasterConfig, load_config, save_config

def test_default_config():
    cfg = HarbormasterConfig()
    assert cfg.api_port == 19191
    assert cfg.watch_range == (1024, 49151)
    assert cfg.approval_gateway == "tui"
    assert cfg.approval_timeout == 0
    assert len(cfg.secret) == 64  # 32 bytes hex

def test_load_config_creates_file_if_missing(tmp_path):
    config_file = tmp_path / "config.toml"
    cfg = load_config(config_file)
    assert config_file.exists()
    assert cfg.api_port == 19191

def test_save_and_reload_config(tmp_path):
    config_file = tmp_path / "config.toml"
    cfg = load_config(config_file)
    cfg.approval_gateway = "telegram"
    save_config(cfg, config_file)
    reloaded = load_config(config_file)
    assert reloaded.approval_gateway == "telegram"

def test_secret_stable_across_reloads(tmp_path):
    config_file = tmp_path / "config.toml"
    cfg1 = load_config(config_file)
    cfg2 = load_config(config_file)
    assert cfg1.secret == cfg2.secret
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement config**

`src/harbormaster/config.py`:
```python
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
```

- [ ] **Step 4: Add `tomli_w` to deps** (tomllib is read-only stdlib)

In `pyproject.toml` dependencies add: `"tomli-w>=1.0"`, then:
```bash
pip install tomli-w
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_config.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add src/harbormaster/config.py tests/test_config.py pyproject.toml
git commit -m "feat: config module with TOML load/save and auto-generated secret"
```

---

## Task 4: SQLite State

**Files:**
- Create: `src/harbormaster/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

`tests/test_state.py`:
```python
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from harbormaster.models import PortState, PortRecord
from harbormaster.state import StateDB

@pytest.fixture
async def db(tmp_path):
    d = StateDB(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()

async def test_set_and_get_port(db):
    record = PortRecord(port=3000, state=PortState.LOCKED, pid=1234, process_name="node")
    await db.set_port(record)
    result = await db.get_port(3000)
    assert result is not None
    assert result.state == PortState.LOCKED
    assert result.pid == 1234
    assert result.process_name == "node"

async def test_get_missing_port_returns_none(db):
    result = await db.get_port(9999)
    assert result is None

async def test_remove_port(db):
    await db.set_port(PortRecord(port=3000, state=PortState.LOCKED))
    await db.remove_port(3000)
    assert await db.get_port(3000) is None

async def test_list_ports(db):
    await db.set_port(PortRecord(port=3000, state=PortState.LOCKED))
    await db.set_port(PortRecord(port=4000, state=PortState.CLAIMED, pid=5678))
    ports = await db.list_ports()
    assert len(ports) == 2
    port_numbers = {p.port for p in ports}
    assert {3000, 4000} == port_numbers

async def test_get_locked_ports(db):
    await db.set_port(PortRecord(port=3000, state=PortState.LOCKED))
    await db.set_port(PortRecord(port=4000, state=PortState.CLAIMED))
    locked = await db.get_locked_ports()
    assert len(locked) == 1
    assert locked[0].port == 3000

async def test_expire_reservations(db):
    past = datetime.utcnow() - timedelta(hours=1)
    future = datetime.utcnow() + timedelta(hours=1)
    await db.set_port(PortRecord(port=3000, state=PortState.RESERVED, reserved_until=past))
    await db.set_port(PortRecord(port=4000, state=PortState.RESERVED, reserved_until=future))
    await db.expire_reservations()
    assert await db.get_port(3000) is None
    result = await db.get_port(4000)
    assert result is not None

async def test_upsert_updates_existing(db):
    await db.set_port(PortRecord(port=3000, state=PortState.CLAIMED, pid=100))
    await db.set_port(PortRecord(port=3000, state=PortState.LOCKED, pid=100))
    result = await db.get_port(3000)
    assert result.state == PortState.LOCKED
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_state.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement StateDB**

`src/harbormaster/state.py`:
```python
from __future__ import annotations
import aiosqlite
from datetime import datetime
from pathlib import Path
from harbormaster.models import PortRecord, PortState


class StateDB:
    def __init__(self, db_path: Path):
        self._path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS ports (
                port INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                pid INTEGER,
                process_name TEXT,
                reserved_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def get_port(self, port: int) -> PortRecord | None:
        async with self._db.execute(
            "SELECT * FROM ports WHERE port = ?", (port,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    async def set_port(self, record: PortRecord) -> None:
        now = datetime.utcnow().isoformat()
        await self._db.execute("""
            INSERT INTO ports (port, state, pid, process_name, reserved_until, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(port) DO UPDATE SET
                state=excluded.state,
                pid=excluded.pid,
                process_name=excluded.process_name,
                reserved_until=excluded.reserved_until,
                updated_at=excluded.updated_at
        """, (
            record.port,
            record.state.value,
            record.pid,
            record.process_name,
            record.reserved_until.isoformat() if record.reserved_until else None,
            now,
            now,
        ))
        await self._db.commit()

    async def remove_port(self, port: int) -> None:
        await self._db.execute("DELETE FROM ports WHERE port = ?", (port,))
        await self._db.commit()

    async def list_ports(self) -> list[PortRecord]:
        async with self._db.execute("SELECT * FROM ports ORDER BY port") as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def get_locked_ports(self) -> list[PortRecord]:
        async with self._db.execute(
            "SELECT * FROM ports WHERE state = ?", (PortState.LOCKED.value,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def get_reserved_ports(self) -> list[PortRecord]:
        async with self._db.execute(
            "SELECT * FROM ports WHERE state = ?", (PortState.RESERVED.value,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def expire_reservations(self) -> None:
        now = datetime.utcnow().isoformat()
        await self._db.execute("""
            DELETE FROM ports
            WHERE state = ? AND reserved_until IS NOT NULL AND reserved_until < ?
        """, (PortState.RESERVED.value, now))
        await self._db.commit()

    def _row_to_record(self, row: aiosqlite.Row) -> PortRecord:
        return PortRecord(
            port=row["port"],
            state=PortState(row["state"]),
            pid=row["pid"],
            process_name=row["process_name"],
            reserved_until=(
                datetime.fromisoformat(row["reserved_until"])
                if row["reserved_until"] else None
            ),
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_state.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/state.py tests/test_state.py
git commit -m "feat: SQLite state module with port CRUD and reservation expiry"
```

---

## Task 5: Lock Engine

**Files:**
- Create: `src/harbormaster/lock_engine.py`
- Create: `tests/test_lock_engine.py`

- [ ] **Step 1: Write failing tests**

`tests/test_lock_engine.py`:
```python
import pytest
import socket
from harbormaster.lock_engine import LockEngine, PrivilegedPortError

@pytest.fixture
async def engine():
    e = LockEngine()
    yield e
    await e.shutdown()

def _get_ephemeral_port() -> int:
    """Find a free port by binding briefly to port 0."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

async def test_lock_free_port(engine):
    port = _get_ephemeral_port()
    result = await engine.lock(port)
    assert result is True
    assert engine.is_locked(port)

async def test_lock_already_locked_port_is_idempotent(engine):
    port = _get_ephemeral_port()
    await engine.lock(port)
    result = await engine.lock(port)
    assert result is True  # already held by us — idempotent

async def test_lock_in_use_port_fails(engine):
    # Hold a port externally, then try to lock it
    with socket.socket() as external:
        external.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        external.bind(("127.0.0.1", 0))
        port = external.getsockname()[1]
        result = await engine.lock(port)
    assert result is False

async def test_unlock_releases_port(engine):
    port = _get_ephemeral_port()
    await engine.lock(port)
    result = await engine.unlock(port)
    assert result is True
    assert not engine.is_locked(port)
    # Port should now be bindable by someone else
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))  # should not raise

async def test_unlock_non_locked_port(engine):
    result = await engine.unlock(9999)
    assert result is False

async def test_locked_ports_list(engine):
    p1 = _get_ephemeral_port()
    p2 = _get_ephemeral_port()
    await engine.lock(p1)
    await engine.lock(p2)
    locked = engine.locked_ports()
    assert p1 in locked
    assert p2 in locked

async def test_privileged_port_raises(engine):
    with pytest.raises(PrivilegedPortError):
        await engine.lock(80)

async def test_shutdown_releases_all(engine):
    port = _get_ephemeral_port()
    await engine.lock(port)
    await engine.shutdown()
    assert not engine.is_locked(port)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_lock_engine.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement LockEngine**

`src/harbormaster/lock_engine.py`:
```python
from __future__ import annotations
import socket
import asyncio


class PrivilegedPortError(Exception):
    """Raised when attempting to lock a port below 1024."""


class LockEngine:
    def __init__(self):
        self._sockets: dict[int, socket.socket] = {}
        self._lock = asyncio.Lock()

    async def lock(self, port: int) -> bool:
        """
        Lock a port by binding a socket to it.
        Returns True on success, False if port is already in use by another process.
        Raises PrivilegedPortError for ports < 1024.
        Idempotent: locking an already-held port returns True.
        """
        if port < 1024:
            raise PrivilegedPortError(
                f"Port {port} requires elevated privileges to lock. "
                "Harbormaster can track and claim it but cannot enforce hard locks."
            )
        async with self._lock:
            if port in self._sockets:
                return True  # already held by us
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                self._sockets[port] = sock
                return True
            except OSError:
                sock.close()
                return False

    async def unlock(self, port: int) -> bool:
        """Release a held socket. Returns False if port was not locked by us."""
        async with self._lock:
            sock = self._sockets.pop(port, None)
            if sock is None:
                return False
            try:
                sock.close()
            except OSError:
                pass
            return True

    def is_locked(self, port: int) -> bool:
        return port in self._sockets

    def locked_ports(self) -> list[int]:
        return list(self._sockets.keys())

    async def shutdown(self) -> None:
        async with self._lock:
            for sock in self._sockets.values():
                try:
                    sock.close()
                except OSError:
                    pass
            self._sockets.clear()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_lock_engine.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/lock_engine.py tests/test_lock_engine.py
git commit -m "feat: lock engine with socket-based port holding and PrivilegedPortError"
```

---

## Task 6: Negotiation Holds

**Files:**
- Create: `src/harbormaster/negotiation.py`
- Create: `tests/test_negotiation.py`

- [ ] **Step 1: Write failing tests**

`tests/test_negotiation.py`:
```python
import pytest
import asyncio
from harbormaster.negotiation import NegotiationHolds

@pytest.fixture
def holds():
    return NegotiationHolds()

def test_add_and_check_hold(holds):
    holds.add(3000, ttl_seconds=10)
    assert holds.is_held(3000)

def test_release_hold(holds):
    holds.add(3000, ttl_seconds=10)
    holds.release(3000)
    assert not holds.is_held(3000)

def test_hold_expiry(holds):
    holds.add(3000, ttl_seconds=0)  # immediate expiry
    holds.expire_stale()
    assert not holds.is_held(3000)

def test_next_available_skips_held(holds):
    holds.add(3000, ttl_seconds=60)
    port = holds.next_available(3000, max_port=3010, unavailable={3001, 3002})
    assert port == 3003

def test_next_available_returns_none_when_exhausted(holds):
    result = holds.next_available(3000, max_port=3001, unavailable={3000, 3001})
    assert result is None

def test_next_available_returns_preferred_if_clear(holds):
    port = holds.next_available(3000, max_port=65000, unavailable=set())
    assert port == 3000

def test_double_add_resets_ttl(holds):
    holds.add(3000, ttl_seconds=60)
    holds.add(3000, ttl_seconds=60)  # should not raise, just refreshes
    assert holds.is_held(3000)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_negotiation.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement NegotiationHolds**

`src/harbormaster/negotiation.py`:
```python
from __future__ import annotations
from datetime import datetime, timedelta


class NegotiationHolds:
    """
    In-memory short-lived port holds issued during /request negotiation.
    Not persisted. Prevents two simultaneous /request calls from returning
    the same port before either caller has had a chance to bind.
    """

    def __init__(self):
        self._holds: dict[int, datetime] = {}

    def add(self, port: int, ttl_seconds: int = 10) -> None:
        self._holds[port] = datetime.utcnow() + timedelta(seconds=ttl_seconds)

    def release(self, port: int) -> None:
        self._holds.pop(port, None)

    def is_held(self, port: int) -> bool:
        expiry = self._holds.get(port)
        if expiry is None:
            return False
        if datetime.utcnow() >= expiry:
            del self._holds[port]
            return False
        return True

    def expire_stale(self) -> None:
        now = datetime.utcnow()
        expired = [p for p, exp in self._holds.items() if now >= exp]
        for p in expired:
            del self._holds[p]

    def next_available(
        self,
        preferred: int,
        max_port: int,
        unavailable: set[int],
    ) -> int | None:
        """
        Return the first port >= preferred that is not held and not in unavailable.
        Returns None if no port found up to max_port.
        """
        for port in range(preferred, max_port + 1):
            if port not in unavailable and not self.is_held(port):
                return port
        return None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_negotiation.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/negotiation.py tests/test_negotiation.py
git commit -m "feat: in-memory negotiation holds with TTL and next-available scan"
```

---

## Task 7: Port Scanner

**Files:**
- Create: `src/harbormaster/scanner.py`
- Create: `tests/test_scanner.py`

- [ ] **Step 1: Write failing tests**

`tests/test_scanner.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from harbormaster.models import PortState, PortRecord, LivePort
from harbormaster.scanner import PortScanner

def _make_mock_conn(laddr_ip, laddr_port, pid, status):
    conn = MagicMock()
    conn.laddr.ip = laddr_ip
    conn.laddr.port = laddr_port
    conn.pid = pid
    conn.status = status
    return conn

def _make_mock_proc(pid, name):
    proc = MagicMock()
    proc.pid = pid
    proc.name.return_value = name
    return proc

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_port = AsyncMock(return_value=None)
    db.set_port = AsyncMock()
    db.list_ports = AsyncMock(return_value=[])
    return db

async def test_scan_returns_live_ports(mock_db):
    scanner = PortScanner(mock_db, watch_range=(1024, 49151))
    conn = _make_mock_conn("127.0.0.1", 3000, 1234, "LISTEN")
    proc = _make_mock_proc(1234, "node")
    with patch("psutil.net_connections", return_value=[conn]), \
         patch("psutil.Process", return_value=proc):
        ports = await scanner.scan()
    assert len(ports) == 1
    assert ports[0].port == 3000
    assert ports[0].process_name == "node"
    assert ports[0].is_listen is True

async def test_scan_excludes_out_of_range(mock_db):
    scanner = PortScanner(mock_db, watch_range=(3000, 4000))
    conn = _make_mock_conn("127.0.0.1", 80, 1, "LISTEN")
    proc = _make_mock_proc(1, "nginx")
    with patch("psutil.net_connections", return_value=[conn]), \
         patch("psutil.Process", return_value=proc):
        ports = await scanner.scan()
    assert len(ports) == 0

async def test_reconcile_auto_registers_in_use(mock_db):
    scanner = PortScanner(mock_db, watch_range=(1024, 49151))
    live = [LivePort(port=3000, pid=1234, process_name="node", is_listen=True, interface="127.0.0.1")]
    mock_db.get_port.return_value = None
    await scanner.reconcile(live)
    mock_db.set_port.assert_called_once()
    record = mock_db.set_port.call_args[0][0]
    assert record.port == 3000
    assert record.state == PortState.CLAIMED
    assert record.pid == 1234

async def test_reconcile_skips_already_registered(mock_db):
    scanner = PortScanner(mock_db, watch_range=(1024, 49151))
    live = [LivePort(port=3000, pid=1234, process_name="node", is_listen=True, interface="127.0.0.1")]
    mock_db.get_port.return_value = PortRecord(port=3000, state=PortState.LOCKED, pid=1234)
    await scanner.reconcile(live)
    mock_db.set_port.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_scanner.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement PortScanner**

`src/harbormaster/scanner.py`:
```python
from __future__ import annotations
import asyncio
import psutil
from harbormaster.models import LivePort, PortRecord, PortState
from harbormaster.state import StateDB


class PortScanner:
    def __init__(self, db: StateDB, watch_range: tuple[int, int] = (1024, 49151)):
        self._db = db
        self._watch_range = watch_range

    async def scan(self) -> list[LivePort]:
        """Return live snapshot of ports within watch_range from psutil."""
        lo, hi = self._watch_range
        result: list[LivePort] = []
        try:
            conns = psutil.net_connections(kind="inet")
        except psutil.AccessDenied:
            return result
        for conn in conns:
            if not conn.laddr or conn.pid is None:
                continue
            port = conn.laddr.port
            if not (lo <= port <= hi):
                continue
            try:
                proc = psutil.Process(conn.pid)
                name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                name = "unknown"
            result.append(LivePort(
                port=port,
                pid=conn.pid,
                process_name=name,
                is_listen=conn.status == "LISTEN",
                interface=conn.laddr.ip,
            ))
        return result

    async def reconcile(self, live_ports: list[LivePort]) -> None:
        """
        Auto-register any in-use port not yet tracked as claimed.
        Skips ports already in a managed state (claimed, locked, reserved).
        """
        for lp in live_ports:
            existing = await self._db.get_port(lp.port)
            if existing is not None:
                continue  # already tracked — watcher handles updates
            record = PortRecord(
                port=lp.port,
                state=PortState.CLAIMED,
                pid=lp.pid,
                process_name=lp.process_name,
            )
            await self._db.set_port(record)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_scanner.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/scanner.py tests/test_scanner.py
git commit -m "feat: port scanner with psutil scan and auto-registration reconciliation"
```

---

## Task 8: Process Watcher

**Files:**
- Create: `src/harbormaster/watcher.py`
- Create: `tests/test_watcher.py`

- [ ] **Step 1: Write failing tests**

`tests/test_watcher.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from harbormaster.models import PortState, PortRecord
from harbormaster.watcher import ProcessWatcher

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.list_ports = AsyncMock(return_value=[])
    db.remove_port = AsyncMock()
    db.set_port = AsyncMock()
    return db

async def test_dead_process_removes_record(mock_db):
    record = PortRecord(port=3000, state=PortState.CLAIMED, pid=9999, process_name="node")
    mock_db.list_ports.return_value = [record]
    watcher = ProcessWatcher(mock_db)
    with patch("psutil.pid_exists", return_value=False):
        await watcher.check_all()
    mock_db.remove_port.assert_called_once_with(3000)

async def test_live_process_unchanged(mock_db):
    record = PortRecord(port=3000, state=PortState.CLAIMED, pid=1234, process_name="node")
    mock_db.list_ports.return_value = [record]
    watcher = ProcessWatcher(mock_db)
    import psutil as _psutil
    mock_proc = type("P", (), {"name": lambda self: "node"})()
    with patch("psutil.pid_exists", return_value=True), \
         patch("psutil.Process", return_value=mock_proc):
        await watcher.check_all()
    mock_db.remove_port.assert_not_called()

async def test_pid_recycled_rereg(mock_db):
    """PID exists but process name changed — treat as recycled, re-register."""
    record = PortRecord(port=3000, state=PortState.CLAIMED, pid=1234, process_name="node")
    mock_db.list_ports.return_value = [record]
    watcher = ProcessWatcher(mock_db)
    mock_proc = type("P", (), {"name": lambda self: "python3"})()
    with patch("psutil.pid_exists", return_value=True), \
         patch("psutil.Process", return_value=mock_proc):
        await watcher.check_all()
    mock_db.set_port.assert_called_once()
    updated = mock_db.set_port.call_args[0][0]
    assert updated.process_name == "python3"

async def test_locked_port_not_removed_on_process_exit(mock_db):
    """Locked ports keep their record even if the process exits (daemon holds the socket)."""
    record = PortRecord(port=3000, state=PortState.LOCKED, pid=1234, process_name="node")
    mock_db.list_ports.return_value = [record]
    watcher = ProcessWatcher(mock_db)
    with patch("psutil.pid_exists", return_value=False):
        await watcher.check_all()
    mock_db.remove_port.assert_not_called()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_watcher.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement ProcessWatcher**

`src/harbormaster/watcher.py`:
```python
from __future__ import annotations
import psutil
from harbormaster.models import PortRecord, PortState
from harbormaster.state import StateDB


class ProcessWatcher:
    """Monitors registered PIDs and cleans up state when processes exit."""

    def __init__(self, db: StateDB):
        self._db = db

    async def check_all(self) -> None:
        records = await self._db.list_ports()
        for record in records:
            if record.state == PortState.LOCKED:
                # Daemon holds the socket — keep the record regardless of process state
                continue
            if record.pid is None:
                continue
            await self._check_record(record)

    async def _check_record(self, record: PortRecord) -> None:
        if not psutil.pid_exists(record.pid):
            await self._db.remove_port(record.port)
            return
        try:
            proc = psutil.Process(record.pid)
            current_name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            await self._db.remove_port(record.port)
            return
        if current_name != record.process_name:
            # PID recycled — update registration to new process
            updated = PortRecord(
                port=record.port,
                state=record.state,
                pid=record.pid,
                process_name=current_name,
            )
            await self._db.set_port(updated)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_watcher.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/watcher.py tests/test_watcher.py
git commit -m "feat: process watcher with death detection and PID recycle guard"
```

---

## Task 9: Tailscale Detector

**Files:**
- Create: `src/harbormaster/tailscale.py`
- Create: `tests/test_tailscale.py`

- [ ] **Step 1: Write failing tests**

`tests/test_tailscale.py`:
```python
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from harbormaster.tailscale import TailscaleDetector, TailscaleInfo

MOCK_STATUS = json.dumps({
    "Self": {
        "TailscaleIPs": ["100.64.0.1", "fd7a::1"],
        "HostName": "geo-hp-omen",
    }
})

async def test_detect_returns_info_when_available():
    detector = TailscaleDetector()
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(MOCK_STATUS.encode(), b""))
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        info = await detector.detect()
    assert info is not None
    assert info.ipv4 == "100.64.0.1"
    assert info.hostname == "geo-hp-omen"

async def test_detect_returns_none_when_tailscale_missing():
    detector = TailscaleDetector()
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        info = await detector.detect()
    assert info is None

async def test_detect_returns_none_on_error_exit():
    detector = TailscaleDetector()
    proc = MagicMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(b"", b"not connected"))
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        info = await detector.detect()
    assert info is None

async def test_is_tailscale_interface():
    detector = TailscaleDetector()
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(MOCK_STATUS.encode(), b""))
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        await detector.detect()
    assert detector.is_tailscale_ip("100.64.0.1")
    assert not detector.is_tailscale_ip("127.0.0.1")
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tailscale.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement TailscaleDetector**

`src/harbormaster/tailscale.py`:
```python
from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass


@dataclass
class TailscaleInfo:
    ipv4: str
    ipv6: str | None
    hostname: str


class TailscaleDetector:
    def __init__(self):
        self._current: TailscaleInfo | None = None
        self._known_ips: set[str] = set()

    async def detect(self) -> TailscaleInfo | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "tailscale", "status", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                self._current = None
                self._known_ips = set()
                return None
        except FileNotFoundError:
            self._current = None
            self._known_ips = set()
            return None

        try:
            data = json.loads(stdout)
            ips: list[str] = data.get("Self", {}).get("TailscaleIPs", [])
            hostname: str = data.get("Self", {}).get("HostName", "")
            ipv4 = next((ip for ip in ips if ":" not in ip), None)
            ipv6 = next((ip for ip in ips if ":" in ip), None)
            if ipv4 is None:
                self._current = None
                self._known_ips = set()
                return None
            self._current = TailscaleInfo(ipv4=ipv4, ipv6=ipv6, hostname=hostname)
            self._known_ips = set(ips)
            return self._current
        except (json.JSONDecodeError, KeyError):
            self._current = None
            self._known_ips = set()
            return None

    def is_tailscale_ip(self, ip: str) -> bool:
        return ip in self._known_ips

    @property
    def current(self) -> TailscaleInfo | None:
        return self._current
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_tailscale.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/tailscale.py tests/test_tailscale.py
git commit -m "feat: Tailscale detector with reconnect handling and IP tracking"
```

---

## Task 10: Approval Gateway Base + TUI Stub

**Files:**
- Create: `src/harbormaster/approval/__init__.py`
- Create: `src/harbormaster/approval/base.py`
- Create: `src/harbormaster/approval/tui_stub.py`

- [ ] **Step 1: Create approval package**

`src/harbormaster/approval/__init__.py`:
```python
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult
```

- [ ] **Step 2: Implement base gateway**

`src/harbormaster/approval/base.py`:
```python
from __future__ import annotations
import abc
import uuid
from dataclasses import dataclass, field
from enum import Enum


class ApprovalResult(Enum):
    ALLOW = "allow"
    DENY = "deny"
    TIMEOUT = "timeout"


@dataclass
class ApprovalRequest:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    action: str = ""         # "lock" or "evict"
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

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """Convenience: send + wait."""
        await self.send_request(request)
        return await self.wait_for_response(request)
```

- [ ] **Step 3: Implement TUI stub gateway**

The real TUI gateway (Plan 2) opens a websocket to the running TUI. This stub logs to stderr and blocks until stdin input — useful for testing without a TUI.

`src/harbormaster/approval/tui_stub.py`:
```python
from __future__ import annotations
import asyncio
import sys
from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult


class TuiStubGateway(ApprovalGateway):
    """
    Stub gateway used when no TUI is connected.
    Prints to stderr and waits for stdin input (y/n).
    In production use, the real TUI gateway (Plan 2) replaces this.
    """

    def __init__(self, timeout: int = 0):
        self._timeout = timeout  # 0 = wait forever
        self._pending: dict[str, asyncio.Future] = {}

    async def send_request(self, request: ApprovalRequest) -> None:
        print(
            f"\n[Harbormaster] Approval required:\n"
            f"  Action: {request.action}\n"
            f"  Port:   {request.port}\n"
            f"  Process: {request.process_name} (PID {request.pid})\n"
            f"  Requester: {request.requester}\n"
            f"Allow? [y/N]: ",
            end="",
            flush=True,
            file=sys.stderr,
        )

    async def wait_for_response(self, request: ApprovalRequest) -> ApprovalResult:
        loop = asyncio.get_event_loop()
        try:
            coro = loop.run_in_executor(None, input)
            if self._timeout > 0:
                answer = await asyncio.wait_for(coro, timeout=self._timeout)
            else:
                answer = await coro
        except asyncio.TimeoutError:
            print("\n[Harbormaster] Approval timed out — denying.", file=sys.stderr)
            return ApprovalResult.DENY
        except EOFError:
            return ApprovalResult.DENY
        return ApprovalResult.ALLOW if answer.strip().lower() == "y" else ApprovalResult.DENY

    async def cancel(self, request_id: str) -> None:
        pass  # nothing to cancel for stdin-based gateway
```

- [ ] **Step 4: Run all tests to verify nothing broken**

```bash
pytest tests/ -v
```

Expected: all previous tests still pass, no new failures.

- [ ] **Step 5: Commit**

```bash
git add src/harbormaster/approval/ 
git commit -m "feat: approval gateway base class and TUI stub for interactive prompts"
```

---

## Task 11: HTTP API

**Files:**
- Create: `src/harbormaster/api.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

`tests/test_api.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient
from harbormaster.api import build_app
from harbormaster.models import PortState, PortRecord
from harbormaster.config import HarbormasterConfig

SECRET = "test-secret-abc123"

@pytest.fixture
def cfg():
    c = HarbormasterConfig()
    c.secret = SECRET
    c.watch_range = (1024, 49151)
    return c

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.list_ports = AsyncMock(return_value=[])
    db.get_port = AsyncMock(return_value=None)
    db.set_port = AsyncMock()
    db.remove_port = AsyncMock()
    return db

@pytest.fixture
def mock_lock_engine():
    le = AsyncMock()
    le.lock = AsyncMock(return_value=True)
    le.unlock = AsyncMock(return_value=True)
    le.locked_ports = MagicMock(return_value=[])
    return le

@pytest.fixture
def mock_holds():
    h = MagicMock()
    h.is_held = MagicMock(return_value=False)
    h.next_available = MagicMock(return_value=3000)
    h.add = MagicMock()
    h.release = MagicMock()
    return h

@pytest.fixture
def mock_gateway():
    gw = AsyncMock()
    from harbormaster.approval.base import ApprovalResult
    gw.request_approval = AsyncMock(return_value=ApprovalResult.ALLOW)
    return gw

@pytest.fixture
def client(cfg, mock_db, mock_lock_engine, mock_holds, mock_gateway):
    app = build_app(cfg=cfg, db=mock_db, lock_engine=mock_lock_engine,
                    holds=mock_holds, gateway=mock_gateway)
    return TestClient(app, raise_server_exceptions=True)

def auth(secret=SECRET):
    return {"X-Harbormaster-Secret": secret}

def test_health(client):
    r = client.get("/health", headers=auth())
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_no_auth_returns_403(client):
    r = client.get("/health")
    assert r.status_code == 403

def test_wrong_secret_returns_403(client):
    r = client.get("/health", headers={"X-Harbormaster-Secret": "wrong"})
    assert r.status_code == 403

def test_request_port(client, mock_holds, mock_db):
    mock_db.list_ports.return_value = []
    r = client.get("/request?port=3000", headers=auth())
    assert r.status_code == 200
    data = r.json()
    assert "assigned" in data
    assert "hold_expires_at" in data

def test_request_port_no_available_returns_409(client, mock_holds):
    mock_holds.next_available.return_value = None
    r = client.get("/request?port=3000", headers=auth())
    assert r.status_code == 409

def test_lock_port(client):
    r = client.post("/lock", json={"port": 3001}, headers=auth())
    assert r.status_code == 200

def test_lock_port_failed_returns_409(client, mock_lock_engine):
    mock_lock_engine.lock.return_value = False
    r = client.post("/lock", json={"port": 3001}, headers=auth())
    assert r.status_code == 409

def test_unlock_port(client, mock_db):
    mock_db.get_port.return_value = PortRecord(port=3001, state=PortState.LOCKED)
    r = client.post("/unlock", json={"port": 3001}, headers=auth())
    assert r.status_code == 200

def test_claim_port(client):
    r = client.post("/claim", json={"port": 3001, "pid": 1234, "name": "node"}, headers=auth())
    assert r.status_code == 200

def test_list_ports(client, mock_db):
    mock_db.list_ports.return_value = [
        PortRecord(port=3000, state=PortState.LOCKED, pid=1234, process_name="node")
    ]
    r = client.get("/list", headers=auth())
    assert r.status_code == 200
    ports = r.json()["ports"]
    assert len(ports) == 1
    assert ports[0]["port"] == 3000
    assert ports[0]["state"] == "locked"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_api.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement the API**

`src/harbormaster/api.py`:
```python
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from harbormaster.approval.base import ApprovalGateway, ApprovalRequest, ApprovalResult
from harbormaster.config import HarbormasterConfig
from harbormaster.lock_engine import LockEngine, PrivilegedPortError
from harbormaster.models import PortRecord, PortState
from harbormaster.negotiation import NegotiationHolds
from harbormaster.state import StateDB


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str):
        super().__init__(app)
        self._secret = secret

    async def dispatch(self, request: Request, call_next):
        if request.headers.get("X-Harbormaster-Secret") != self._secret:
            return JSONResponse({"error": "unauthorized"}, status_code=403)
        return await call_next(request)


def build_app(
    cfg: HarbormasterConfig,
    db: StateDB,
    lock_engine: LockEngine,
    holds: NegotiationHolds,
    gateway: ApprovalGateway,
) -> Starlette:

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({
            "status": "ok",
            "locked": len(lock_engine.locked_ports()),
        })

    async def request_port(request: Request) -> JSONResponse:
        preferred = int(request.query_params.get("port", 3000))
        max_port = int(request.query_params.get("max_port", 65000))
        # Build set of unavailable ports
        records = await db.list_ports()
        unavailable = {
            r.port for r in records
            if r.state in (PortState.LOCKED, PortState.RESERVED, PortState.CLAIMED)
        }
        holds.expire_stale()
        assigned = holds.next_available(preferred, max_port, unavailable)
        if assigned is None:
            return JSONResponse(
                {"error": f"No available port found in range {preferred}–{max_port}"},
                status_code=409,
            )
        holds.add(assigned, ttl_seconds=10)
        expiry = (datetime.utcnow() + timedelta(seconds=10)).isoformat() + "Z"
        reason = None
        if assigned != preferred:
            blocking = next((r for r in records if r.port == preferred), None)
            if blocking:
                reason = f"{preferred} {blocking.state.value} by {blocking.process_name} PID {blocking.pid}"
        return JSONResponse({
            "assigned": assigned,
            "preferred": preferred,
            "reason": reason,
            "hold_expires_at": expiry,
        })

    async def lock_port(request: Request) -> JSONResponse:
        body = await request.json()
        port = body["port"]
        approval = ApprovalRequest(action="lock", port=port)
        result = await gateway.request_approval(approval)
        if result != ApprovalResult.ALLOW:
            return JSONResponse({"error": "denied"}, status_code=403)
        try:
            success = await lock_engine.lock(port)
        except PrivilegedPortError as e:
            return JSONResponse({"error": str(e)}, status_code=422)
        if not success:
            return JSONResponse({"error": f"Port {port} is in use and cannot be locked"}, status_code=409)
        existing = await db.get_port(port)
        record = PortRecord(
            port=port,
            state=PortState.LOCKED,
            pid=existing.pid if existing else None,
            process_name=existing.process_name if existing else None,
        )
        await db.set_port(record)
        return JSONResponse({"port": port, "state": "locked"})

    async def unlock_port(request: Request) -> JSONResponse:
        body = await request.json()
        port = body["port"]
        await lock_engine.unlock(port)
        await db.remove_port(port)
        return JSONResponse({"port": port, "state": "open"})

    async def evict_port(request: Request) -> JSONResponse:
        import subprocess, signal
        body = await request.json()
        port = body["port"]
        existing = await db.get_port(port)
        pid = existing.pid if existing else None
        process_name = existing.process_name if existing else None

        # Check if systemd-managed
        is_systemd = False
        if pid:
            try:
                r = subprocess.run(
                    ["systemctl", "status", str(pid)],
                    capture_output=True, timeout=2
                )
                is_systemd = r.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        approval = ApprovalRequest(
            action="evict",
            port=port,
            pid=pid,
            process_name=process_name,
            requester=f"{'systemd-managed — may restart automatically. ' if is_systemd else ''}",
        )
        result = await gateway.request_approval(approval)
        if result != ApprovalResult.ALLOW:
            return JSONResponse({"error": "denied"}, status_code=403)

        if pid:
            try:
                import os
                os.kill(pid, signal.SIGTERM)
                await asyncio.sleep(3)
                if psutil_pid_exists(pid):
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        try:
            await lock_engine.lock(port)
        except PrivilegedPortError:
            pass
        record = PortRecord(port=port, state=PortState.LOCKED)
        await db.set_port(record)
        return JSONResponse({"port": port, "state": "locked", "evicted_pid": pid})

    async def claim_port(request: Request) -> JSONResponse:
        body = await request.json()
        port = body["port"]
        pid = body.get("pid")
        name = body.get("name", "unknown")
        holds.release(port)
        record = PortRecord(port=port, state=PortState.CLAIMED, pid=pid, process_name=name)
        await db.set_port(record)
        return JSONResponse({"port": port, "state": "claimed"})

    async def reserve_port(request: Request) -> JSONResponse:
        from datetime import timezone
        body = await request.json()
        port = body["port"]
        ttl_seconds = body.get("ttl_seconds")
        if ttl_seconds is None:
            return JSONResponse({"error": "ttl_seconds required"}, status_code=422)
        reserved_until = None if ttl_seconds == -1 else datetime.utcnow() + timedelta(seconds=ttl_seconds)
        record = PortRecord(port=port, state=PortState.RESERVED, reserved_until=reserved_until)
        await db.set_port(record)
        return JSONResponse({
            "port": port,
            "state": "reserved",
            "reserved_until": reserved_until.isoformat() if reserved_until else "permanent",
        })

    async def unreserve_port(request: Request) -> JSONResponse:
        port = int(request.path_params["port"])
        existing = await db.get_port(port)
        if existing is None or existing.state != PortState.RESERVED:
            return JSONResponse({"error": "Port is not reserved"}, status_code=404)
        await db.remove_port(port)
        return JSONResponse({"port": port, "state": "open"})

    async def list_ports(request: Request) -> JSONResponse:
        records = await db.list_ports()
        return JSONResponse({"ports": [r.to_dict() for r in records]})

    routes = [
        Route("/health", health),
        Route("/request", request_port),
        Route("/lock", lock_port, methods=["POST"]),
        Route("/unlock", unlock_port, methods=["POST"]),
        Route("/evict", evict_port, methods=["POST"]),
        Route("/claim", claim_port, methods=["POST"]),
        Route("/reserve", reserve_port, methods=["POST"]),
        Route("/reserve/{port:int}", unreserve_port, methods=["DELETE"]),
        Route("/list", list_ports),
    ]

    return Starlette(
        routes=routes,
        middleware=[Middleware(AuthMiddleware, secret=cfg.secret)],
    )


def psutil_pid_exists(pid: int) -> bool:
    import psutil
    return psutil.pid_exists(pid)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_api.py -v
```

Expected: `11 passed`

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/harbormaster/api.py tests/test_api.py
git commit -m "feat: Starlette HTTP API with secret auth, all port endpoints"
```

---

## Task 12: Daemon Orchestration

**Files:**
- Create: `src/harbormaster/daemon.py`

- [ ] **Step 1: Implement HarbormasterDaemon**

No unit tests for the orchestration layer — it's a thin wiring class. Integration tested by running it.

`src/harbormaster/daemon.py`:
```python
from __future__ import annotations
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

from harbormaster.api import build_app
from harbormaster.approval.tui_stub import TuiStubGateway
from harbormaster.config import HarbormasterConfig, load_config, _default_db_path
from harbormaster.lock_engine import LockEngine
from harbormaster.models import PortState
from harbormaster.negotiation import NegotiationHolds
from harbormaster.scanner import PortScanner
from harbormaster.state import StateDB
from harbormaster.tailscale import TailscaleDetector
from harbormaster.watcher import ProcessWatcher

logger = logging.getLogger("harbormaster")


class HarbormasterDaemon:
    def __init__(self, config_path: Path | None = None, db_path: Path | None = None):
        self.cfg = load_config(config_path)
        self._db_path = db_path or _default_db_path()
        self.db = StateDB(self._db_path)
        self.lock_engine = LockEngine()
        self.holds = NegotiationHolds()
        self.gateway = TuiStubGateway(timeout=self.cfg.approval_timeout)
        self.scanner = PortScanner(self.db, watch_range=tuple(self.cfg.watch_range))
        self.watcher = ProcessWatcher(self.db)
        self.tailscale = TailscaleDetector()
        self._scan_task: asyncio.Task | None = None

    async def startup(self) -> None:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
        logger.info("Harbormaster starting up")

        # 1. Init DB
        await self.db.init()
        await self.db.expire_reservations()

        # 2. Lock own API port first — before anything else
        api_port = self.cfg.api_port
        success = await self.lock_engine.lock(api_port)
        if not success:
            logger.error(f"Cannot bind to API port {api_port} — already in use. Is another instance running?")
            sys.exit(1)
        logger.info(f"API port :{api_port} locked")

        # 3. Re-acquire all locked ports from SQLite
        locked_records = await self.db.get_locked_ports()
        for record in locked_records:
            if record.port == api_port:
                continue
            ok = await self.lock_engine.lock(record.port)
            if not ok:
                logger.warning(f"Could not re-acquire lock on :{record.port} — port is in use")

        # 4. Detect Tailscale
        ts = await self.tailscale.detect()
        if ts:
            logger.info(f"Tailscale detected: {ts.ipv4} ({ts.hostname})")
        else:
            logger.info("Tailscale not available")

        # 5. Initial scan
        live = await self.scanner.scan()
        await self.scanner.reconcile(live)

        logger.info(f"Startup complete — {len(locked_records)} lock(s) restored")

    async def _background_loop(self) -> None:
        tailscale_tick = 0
        while True:
            await asyncio.sleep(2)
            try:
                live = await self.scanner.scan()
                await self.scanner.reconcile(live)
                await self.watcher.check_all()
                self.holds.expire_stale()
                tailscale_tick += 1
                if tailscale_tick >= 15:  # every ~30s
                    tailscale_tick = 0
                    await self.tailscale.detect()
            except Exception as e:
                logger.exception(f"Background loop error: {e}")

    async def shutdown(self) -> None:
        logger.info("Harbormaster shutting down")
        if self._scan_task:
            self._scan_task.cancel()
        await self.lock_engine.shutdown()
        await self.db.close()

    async def serve(self) -> None:
        await self.startup()
        app = build_app(
            cfg=self.cfg,
            db=self.db,
            lock_engine=self.lock_engine,
            holds=self.holds,
            gateway=self.gateway,
        )
        self._scan_task = asyncio.create_task(self._background_loop())
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.cfg.api_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        try:
            await server.serve()
        finally:
            await self.shutdown()


def main() -> None:
    daemon = HarbormasterDaemon()
    try:
        asyncio.run(daemon.serve())
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 2: Smoke test the daemon**

```bash
harbormasterd &
sleep 2
SECRET=$(python3 -c "
import tomllib, pathlib, os
p = pathlib.Path(os.environ.get('XDG_CONFIG_HOME', pathlib.Path.home()/'.config'))/'harbormaster'/'config.toml'
print(tomllib.loads(p.read_text())['daemon']['secret'])
")
curl -s -H "X-Harbormaster-Secret: $SECRET" http://localhost:19191/health
```

Expected output:
```json
{"status": "ok", "locked": 1}
```

```bash
curl -s -H "X-Harbormaster-Secret: $SECRET" http://localhost:19191/list
kill %1  # stop background daemon
```

- [ ] **Step 3: Commit**

```bash
git add src/harbormaster/daemon.py
git commit -m "feat: daemon orchestration — startup, background scan loop, uvicorn serve"
```

---

## Task 13: systemd User Service

**Files:**
- Create: `systemd/harbormaster.service`

- [ ] **Step 1: Write the unit file**

`systemd/harbormaster.service`:
```ini
[Unit]
Description=Harbormaster Port Allocation Daemon
Documentation=https://github.com/ryancalpin/harbormaster
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/harbormasterd
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Add install command to daemon.py**

Add this function at the bottom of `src/harbormaster/daemon.py`:

```python
def install_service() -> None:
    """Copy systemd unit file and enable the user service."""
    import shutil, subprocess
    from importlib.resources import files

    unit_src = Path(__file__).parent.parent.parent / "systemd" / "harbormaster.service"
    systemd_user_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_user_dir.mkdir(parents=True, exist_ok=True)
    dest = systemd_user_dir / "harbormaster.service"
    shutil.copy(unit_src, dest)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "harbormaster"], check=True)
    print(f"Harbormaster service installed and started.")
    print(f"  Status: systemctl --user status harbormaster")
    print(f"  Logs:   journalctl --user -u harbormaster -f")
```

Update the `main()` function to handle the `install` subcommand:

```python
def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        install_service()
        return
    daemon = HarbormasterDaemon()
    try:
        asyncio.run(daemon.serve())
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 3: Test install**

```bash
harbormasterd install
systemctl --user status harbormaster
```

Expected: service is active (running).

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Final commit**

```bash
git add systemd/ src/harbormaster/daemon.py
git commit -m "feat: systemd user service unit file and install command"
git push
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Lock engine with socket holding → Task 5
- ✅ PrivilegedPortError for <1024 → Task 5
- ✅ SQLite state with all port states → Task 4
- ✅ Auto-registration of in-use ports → Task 7
- ✅ Process death watcher + PID recycle guard → Task 8
- ✅ In-memory negotiation holds (no pending state exposed to user) → Task 6
- ✅ Tailscale detection + reconnect → Task 9
- ✅ Approval gateway interface → Task 10
- ✅ TUI stub gateway (real TUI gateway in Plan 2) → Task 10
- ✅ HTTP API with all endpoints + auth → Task 11
- ✅ Port 19191 self-locked on startup → Task 12
- ✅ Daemon startup order → Task 12
- ✅ systemd user service + install → Task 13
- ✅ Reserved port TTL required → Task 11 (`/reserve` returns 422 if ttl_seconds missing)
- ✅ hm request max port 65000 + error → Task 11 (`/request` returns 409)
- ✅ Starlette (not FastAPI) → Task 11
- ✅ Config with secret, watch_range, display_priority → Task 3
- ✅ Tailscale IP change handling → Task 9

**Not in Plan 1 (Plan 2):**
- TUI (harbor) — Textual app
- CLI (hm) — click/typer commands
- MCP server — stdio proxy
- Additional gateways (Telegram, Discord, Slack, ntfy, webhook)
- `hm reserve` TTL prompt
- Packaging (pipx)
