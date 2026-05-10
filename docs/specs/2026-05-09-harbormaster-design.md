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
| `free` | No process bound, no lock | None |
| `in-use` | Process bound, unprotected | None |
| `claimed` | Tracked by Harbormaster (soft) | Visible in TUI only |
| `reserved` | Pending assignment, 10s TTL | Hard (daemon holds socket during TTL) |
| `locked` | Daemon holds bound socket | Hard — any intruder gets `EADDRINUSE` |

---

## 5. Components

### 5.1 `harbormasterd` — The Daemon

Runs as a **systemd service**, starts on boot. Owns all lock enforcement.

**Responsibilities:**
- Maintains a bound socket for every `locked` port — universal enforcement, no onboarding required for any service or agent
- Exposes HTTP API on `127.0.0.1:19191`
- Exposes MCP server on stdio (launched by MCP-aware clients)
- Persists lock state to SQLite (`~/.local/share/harbormaster/state.db`)
- Scans live port state every 2–3 seconds via `psutil` + `ss`
- Routes approval requests through configured gateway
- Detects Tailscale interface automatically via `tailscale status`

**Lock lifecycle:**
1. `lock` request received → daemon binds socket on port → state written to SQLite
2. Socket held until explicit `unlock` or daemon restart
3. On daemon restart → SQLite locks restored → sockets re-acquired on startup

**Eviction flow:**
1. `evict` request received → approval gateway triggered
2. User approves → daemon sends `SIGTERM` to owning PID → waits 3s → `SIGKILL` if needed
3. Daemon immediately binds socket on now-free port → state set to `locked`

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

```bash
hm request [port]        # get a safe port (preferred or next available)
hm lock [port]           # lock a port
hm unlock [port]         # release a lock
hm evict [port]          # kill occupying process, then lock port
hm claim [port]          # register a port as in-use by a known process
hm list                  # show all ports and states (JSON or table)
hm status                # daemon health + locked port count
hm config                # show/edit gateway config
```

`hm request` outputs just the port number on stdout, making it composable:

```bash
PORT=$(hm request 3000)
npm start --port $PORT
```

### 5.4 HTTP API

Base URL: `http://127.0.0.1:19191`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/request?port=N` | Get a free port (preferred N or next available) |
| `POST` | `/lock` | Lock a port `{"port": N}` |
| `POST` | `/unlock` | Unlock a port `{"port": N}` |
| `POST` | `/evict` | Evict + lock `{"port": N}` — triggers approval |
| `POST` | `/claim` | Soft-register a port `{"port": N, "pid": N, "name": "..."}` |
| `GET` | `/list` | All ports and states |
| `GET` | `/health` | Daemon status |

**Port negotiation response:**
```json
{
  "assigned": 3001,
  "preferred": 3000,
  "reason": "3000 locked by node PID 1234",
  "state": "reserved",
  "ttl_seconds": 10
}
```

The assigned port is reserved for 10 seconds. The requesting process should call `/claim` after binding, or the reservation expires.

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
[approval]
gateway = "tui"           # primary gateway
fallback = "tui"          # if primary unreachable, fall back to TUI
timeout = 0               # 0 = wait indefinitely (default)
                          # >0 = auto-deny after N seconds

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

| Component | Library/Tool |
|-----------|-------------|
| Language | Python 3.11+ |
| TUI | Textual |
| Daemon HTTP | FastAPI + uvicorn |
| MCP server | `mcp` Python SDK |
| Port scanning | `psutil` + `ss` subprocess |
| State | SQLite via `aiosqlite` |
| Config | TOML via `tomllib` (stdlib 3.11+) |
| System service | systemd unit file |
| Packaging | `pipx`-installable, single `pyproject.toml` |

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
