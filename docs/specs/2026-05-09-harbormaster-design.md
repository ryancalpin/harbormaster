# Harbormaster — Design Specification

**Date:** 2026-05-09  
**Status:** Approved  
**Repo:** https://github.com/ryancalpin/harbormaster

---

## 1. Problem Statement

Developers running multiple AI agents and dev services face constant port conflicts. Agents spin up servers on the same ports, override each other's bindings, and require manual intervention to sort out. There is no standard mechanism for processes to negotiate ports before binding, and no way to durably protect a port you're using.

Harbormaster solves this with hard enforcement (socket-holding locks that produce `EADDRINUSE` universally) combined with a cooperative allocation API for agents smart enough to ask first.

---

## 2. Name & Metaphor

**Harbormaster** — the officer who controls which ships dock at which berths. Ships (processes) must request a berth (port); the harbormaster assigns an open slip or turns them away if it's reserved.

- CLI binary: `hm`
- Daemon: `harbormasterd`
- TUI: `harbor`
- GitHub: `ryancalpin/harbormaster`

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    harbormasterd                     │
│                                                      │
│  ┌──────────────┐  ┌─────────────┐  ┌────────────┐  │
│  │ Lock Engine  │  │  HTTP API   │  │ MCP Server │  │
│  │ (sockets)    │  │ :19191      │  │ (stdio)    │  │
│  └──────────────┘  └─────────────┘  └────────────┘  │
│                                                      │
│  ┌──────────────────────────────────────────────────┐│
│  │  Approval Gateway (pluggable)                    ││
│  │  TUI · Telegram · Discord · Slack · ntfy · Webhook││
│  └──────────────────────────────────────────────────┘│
│                                                      │
│  ┌──────────────────────────────────────────────────┐│
│  │  SQLite state (locks, claims, reservations)      ││
│  └──────────────────────────────────────────────────┘│
└────────────────────┬──────────────────────┬──────────┘
                     │                      │
             ┌───────┴───────┐      ┌───────┴───────┐
             │  harbor (TUI) │      │   hm (CLI)    │
             │  Textual app  │      │  request/lock │
             └───────────────┘      └───────────────┘
```

---

## 4. Port States

| State | Description | Enforcement |
|-------|-------------|-------------|
| `open` | Nothing bound, nothing registered | None |
| `reserved` | Pre-claimed for future use, no process yet | Soft — blocks `request` from assigning it; requires TTL on creation |
| `in-use` | Process bound, not yet registered | None — auto-promoted to `claimed` on next scan cycle |
| `claimed` | Process bound + registered/tracked, not locked | Soft — blocks `request`, process-death watched |
| `locked` | Registered + daemon holds bound socket | Hard — `EADDRINUSE` for any intruder |

**No `pending` state.** Port negotiation uses an in-memory hold (not user-visible, not persisted) that expires after 10s. When `/request` returns a port, the daemon records it internally so a simultaneous second `/request` call can't return the same port. This hold evaporates once the agent calls `/claim` or the TTL expires. Nothing is shown in the TUI.

**Reserved TTL:** Creating a reservation always requires a duration. The daemon prompts if unspecified:
```
hm reserve 3000            # daemon asks: "Reserve for how long? [1h/8h/24h/permanent]"
hm reserve 3000 --ttl 8h   # explicit
hm reserve 3000 --permanent
```

**Auto-registration:** On every scan cycle (2–3s), any `in-use` port not yet in SQLite is automatically promoted to `claimed`. Harbormaster reads PID + process name from `psutil` and begins watching the process. When the process exits, state drops to `open`. PID recycling edge case: if a PID reuses a slot between scan cycles, the watcher catches the name mismatch and re-registers.

**Privileged ports (<1024):** Harbormaster cannot lock these without `CAP_NET_BIND_SERVICE`. Attempting to lock a privileged port returns a clear error: `"Port 80 requires elevated privileges to lock. Harbormaster can track and claim it but cannot enforce hard locks."` Tracking and claiming still work — only socket-holding enforcement is unavailable.

**Port range filtering:** Harbormaster watches and auto-registers ports in a configurable range. Default: `1024–49151`. Common high-churn dev ranges (3000–9999, 8000–8999) are prioritized in TUI display order. Fully configurable in `config.toml`.

**State transitions:**
```
open ──────────> reserved (user reserves, TTL required)
open ──────────> claimed  (agent requests + binds + claims)
in-use ─────────> claimed (auto-registered on next scan)
claimed ────────> locked  (user escalates)
locked ─────────> claimed (user downgrades, daemon releases socket)
claimed ────────> open    (process exits, watcher detects)
reserved ───────> claimed (agent requests + binds + claims the reserved port)
reserved ───────> open    (TTL expires or user cancels)
```

---

## 5. Components

### 5.1 `harbormasterd` — The Daemon

Runs as a **systemd service**, starts on boot. Owns all lock enforcement.

**Responsibilities:**
- Auto-locks its own API port `:19191` on startup as the very first action before any other initialization
- Maintains a bound socket for every `locked` port — universal enforcement, no onboarding required
- Exposes HTTP API on `127.0.0.1:19191` (protected by shared secret header)
- Exposes MCP server via a thin stdio proxy process (`harbormasterd --mcp`) that forwards to the running daemon at `:19191`
- Persists lock state to SQLite (`~/.local/share/harbormaster/state.db`)
- Scans live port state every 2–3 seconds via `psutil`; watches registered PIDs for exit
- Routes approval requests through configured gateway; auto-denies if primary and fallback gateways are both unreachable after configurable timeout
- Detects Tailscale interface automatically via `tailscale status --json`; re-detects on reconnect

**Lock lifecycle:**
1. `lock` request received → daemon binds socket on port → state written to SQLite
2. Socket held until explicit `unlock` or daemon stop
3. On daemon restart → SQLite locks restored → sockets re-acquired before accepting new requests

**Eviction flow:**
1. `evict` request received → daemon checks if PID is managed by systemd (`systemctl status <pid>`)
   - If systemd-managed: warn user — "This process is managed by systemd and may restart automatically. Evict anyway?"
2. Approval gateway triggered
3. User approves → daemon sends `SIGTERM` to owning PID → waits 3s → `SIGKILL` if still running
4. Daemon immediately binds socket on now-free port → state set to `locked`

**Process watcher:**
- Every scan cycle, `psutil.pid_exists(pid)` checked for all `claimed` ports
- On process exit: state set to `open`, registration removed from SQLite
- PID mismatch guard: if PID exists but `psutil.Process(pid).name()` differs from registered name, treat as recycled PID — re-register with new process info

**Tailscale reconnect handling:**
- Tailscale IP detected via `tailscale status --json` on startup and every 30s
- If IP changes (reconnect/network switch): sockets bound to old Tailscale IP are released and re-acquired on new IP
- If `tailscale` binary not found: Tailscale section hidden from TUI, no error

### 5.2 `harbor` — TUI

Built with **Python + Textual**. Touch-primary, vertical layout, mobile-friendly.

**Layout:**
```
┌─────────────────────────────────┐
│ ⚓ HARBORMASTER    [●] daemon   │  ← header + daemon health indicator
├─────────────────────────────────┤
│  Filter: [ALL] [↓IN] [↑OUT] [🔒]│  ← tab bar
├─────────────────────────────────┤
│ ── LOCALHOST ─────────────────  │
│ ↓ :3000  node   PID 1234  🔒   │  ← locked row (highlighted)
│ ↓ :8080  python PID 4821  ○    │  ← free row
│ ── TAILSCALE ─────────────────  │
│ ↓ :5000  uvicorn PID 3310 ◈    │  ← claimed row
│ ↑ :443   curl   PID 9901  ○    │
├─────────────────────────────────┤
│ [🔒 Lock] [⚡ Evict] [📋 Copy]  │  ← action bar (appears on row tap)
└─────────────────────────────────┘
```

**Behavior:**
- Rows auto-refresh every 2–3s from daemon state + live `psutil` scan
- Tapping a row selects it and reveals the action bar
- Lock/Evict/Unlock actions send to daemon (evict triggers approval gateway)
- Approval requests from daemon appear as an overlay confirmation panel (default gateway = TUI)
- ↓ = incoming/LISTEN, ↑ = outgoing/ESTABLISHED

### 5.3 `hm` — CLI

**Note on the `hm` binary name:** `hm` is short and may conflict with existing shell aliases. The canonical unambiguous names are `harbor` (TUI) and `harbormasterd` (daemon). `hm` is a convenience alias installed alongside them.

```bash
hm request [port]            # get a safe port; scans up from preferred, max port 65000
hm lock [port]               # lock a port (triggers approval)
hm unlock [port]             # release a lock
hm evict [port]              # kill occupying process, then lock port (triggers approval)
hm claim [port]              # register a port as tracked
hm reserve [port] [--ttl X] # reserve for future use; prompts for TTL if omitted
hm unreserve [port]          # cancel a reservation
hm list                      # show all ports and states (table); --json for machine output
hm list --reserved           # show only reservations with TTL remaining
hm status                    # daemon health + locked/reserved/claimed counts
hm config                    # show/edit config
```

`hm request` outputs just the port number on stdout:
```bash
PORT=$(hm request 3000)
npm start --port $PORT
# If no port available in range, exits non-zero with: "No available port found in range 3000–65000"
```

### 5.4 HTTP API

Base URL: `http://127.0.0.1:19191`

**Authentication:** All requests must include `X-Harbormaster-Secret: <secret>` header. Secret is generated on first run and stored in `~/.config/harbormaster/config.toml`. Missing or invalid secret returns `403`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/request?port=N` | Get a free port (preferred N or next available, max 65000) |
| `POST` | `/lock` | Lock a port `{"port": N}` — triggers approval |
| `POST` | `/unlock` | Unlock a port `{"port": N}` |
| `POST` | `/evict` | Evict + lock `{"port": N}` — triggers approval |
| `POST` | `/claim` | Register a port `{"port": N, "pid": N, "name": "..."}` |
| `POST` | `/reserve` | Reserve for future use `{"port": N, "ttl_seconds": N}` |
| `DELETE` | `/reserve/{port}` | Cancel a reservation |
| `GET` | `/list` | All ports and states |
| `GET` | `/health` | Daemon status, uptime, counts |

**Port negotiation response:**
```json
{
  "assigned": 3001,
  "preferred": 3000,
  "reason": "3000 locked by node PID 1234",
  "hold_expires_at": "2026-05-09T14:32:10Z"
}
```

The assigned port is held in-memory for 10 seconds. Call `/claim` after binding to make it permanent, or the hold expires and the port becomes available again.

### 5.5 MCP Server

Exposes Harbormaster as MCP tools for Claude Code, Cursor, and any MCP-aware agent.

**Tools:**

| Tool | Description | Requires Approval |
|------|-------------|-------------------|
| `request_port` | Request a safe port to bind | No |
| `list_ports` | List all ports and states | No |
| `lock_port` | Lock a port | Yes |
| `unlock_port` | Unlock a port | No |
| `evict_port` | Kill process on port, then lock | Yes |
| `claim_port` | Register a port as in-use | No |
| `daemon_status` | Check daemon health | No |

**MCP config snippet** (`.mcp.json` or `~/.claude/mcp.json`):
```json
{
  "mcpServers": {
    "harbormaster": {
      "command": "harbormasterd",
      "args": ["--mcp"]
    }
  }
}
```

---

## 6. Approval Gateway System

All destructive actions (`lock`, `evict`) require user approval before execution. The daemon blocks the requesting agent until a response is received.

### 6.1 Gateway Interface

Each gateway implements:
- `send_request(action, port, process_info, request_id)` — deliver the prompt
- `wait_for_response(request_id)` — block until user responds Allow/Deny
- `cancel(request_id)` — called if the agent disconnects before responding

### 6.2 Supported Gateways

| Gateway | Delivery | Response method |
|---------|----------|-----------------|
| `tui` | Overlay panel in running TUI | Tap Allow / Deny |
| `telegram` | Bot message with inline buttons | Tap ✅ / ❌ in Telegram |
| `discord` | Bot message with buttons | Click in Discord |
| `slack` | Block Kit message with buttons | Click in Slack |
| `ntfy` | Push notification with actions | Tap on phone |
| `webhook` | HTTP POST to configured URL | Response body `allow` or `deny` |

### 6.3 Configuration

`~/.config/harbormaster/config.toml`:

```toml
[daemon]
api_port = 19191
secret = "auto-generated-on-first-run"

[ports]
watch_range = [1024, 49151]   # ports outside this range are ignored
display_priority = [          # shown first in TUI regardless of port number
  "3000-3999",
  "4000-4999",
  "5000-5999",
  "8000-8999",
  "9000-9999",
]

[approval]
gateway = "tui"           # primary gateway
fallback = "tui"          # used if primary is unreachable
timeout = 0               # 0 = wait indefinitely (default)
                          # >0 = auto-deny after N seconds if no response

[gateways.telegram]
bot_token = "..."
chat_id = "..."

[gateways.discord]
webhook_url = "..."

[gateways.slack]
webhook_url = "..."

[gateways.ntfy]
topic = "harbormaster"
server = "https://ntfy.sh"   # or self-hosted

[gateways.webhook]
url = "https://your-service.com/harbormaster/approve"
secret = "..."               # HMAC-signed payload
```

### 6.4 Approval Flow

```
Agent calls evict_port(3000)
        ↓
Daemon sends approval request to configured gateway
        ↓
User sees: "Agent wants to evict port 3000 (node PID 1234). Allow?"
        ↓
User responds Allow / Deny
        ↓ Allow                    ↓ Deny
Daemon evicts + locks         Daemon returns error
Daemon responds to agent      Agent receives denial
```

---

## 7. Tailscale Integration

Harbormaster detects the Tailscale interface automatically:
- Runs `tailscale status --json` on startup and on each refresh
- Identifies the Tailscale IP and interface name (`tailscale0`)
- Groups TUI rows under `── LOCALHOST ──` or `── TAILSCALE ──` based on bound interface
- Locks applied to Tailscale-bound ports hold on the Tailscale interface address

---

## 8. Tech Stack

| Component | Library/Tool | Rationale |
|-----------|-------------|-----------|
| Language | Python 3.11+ | |
| TUI | Textual | Touch-friendly, CSS-like styling |
| Daemon HTTP | Starlette + uvicorn | Async, ~60% lighter than FastAPI; no Pydantic/OpenAPI overhead needed |
| MCP server | `mcp` Python SDK (stdio proxy) | Thin wrapper; forwards to daemon HTTP API |
| Port scanning | `psutil` | Cross-platform, no subprocess needed |
| State | SQLite via `aiosqlite` | Zero-dependency persistence |
| Config | TOML via `tomllib` (stdlib 3.11+) | No extra deps |
| System service | systemd user unit | Runs as current user, not root |
| Packaging | `pipx`-installable, single `pyproject.toml` | |

---

## 9. Installation (planned)

```bash
pipx install harbormaster
sudo harbormasterd install    # installs + enables systemd service
harbor                        # launch TUI
```

---

## 10. CLAUDE.md Integration Snippet

For AI agents to use cooperative port negotiation:

```markdown
## Port Management
Before starting any server or service, request a port from Harbormaster:
  Shell: PORT=$(hm request <preferred_port>) 
  HTTP:  curl -s "localhost:19191/request?port=<preferred>" | jq .assigned
Use the returned port. Do not hardcode ports.
```

---

## 11. Out of Scope (v1)

- Per-action gateway overrides (single gateway per user is sufficient)
- Windows support
- Docker network interface detection (future)
- Web UI (CLI + TUI covers all cases)
- Port forwarding / proxy features
