# Harbormaster

> A port allocation daemon and TUI for developers and AI agents. Like a real harbormaster — controls which ships dock at which berths, turns away unauthorized vessels, and assigns open slips on request.

**Status: Design phase — PRs and feedback welcome**

---

## The Problem

AI agents and dev services constantly race for the same ports. One agent starts on `:3000`, another one spins up and steals it, everything breaks. There's no standard way for processes to negotiate ports before binding, and no way to protect a port you're actively using.

## What Harbormaster Does

- **Hard port locks** — holds a real socket on locked ports so nothing can steal them (`EADDRINUSE` for any intruder, no onboarding required)
- **Port allocation API** — processes request a port before binding; Harbormaster returns the requested port or the next available one if it's taken/locked
- **MCP server** — MCP-aware agents (Claude Code, Cursor, etc.) get first-class tool access with user confirmation on destructive actions
- **TUI** — touch-friendly vertical terminal UI showing live port state across localhost and Tailscale, with lock/evict/copy actions
- **Systemd daemon** — `harbormasterd` runs as a system service; locks survive TUI restarts

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  harbormasterd                   │
│  ┌─────────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Lock engine │  │ HTTP API │  │ MCP server │  │
│  │ (sockets)   │  │ :19191   │  │ (stdio)    │  │
│  └─────────────┘  └──────────┘  └────────────┘  │
│  ┌──────────────────────────────────────────────┐ │
│  │  SQLite state (locks, claims, reservations)  │ │
│  └──────────────────────────────────────────────┘ │
└──────────────┬──────────────────────────┬─────────┘
               │                          │
        ┌──────┴──────┐          ┌────────┴────────┐
        │  harbor TUI │          │  harbor CLI      │
        │  (Textual)  │          │  pgrep, lock,   │
        └─────────────┘          │  unlock, evict  │
                                 └─────────────────┘
```

## Port States

| State | Meaning | Enforcement |
|-------|---------|-------------|
| `free` | No process bound | None |
| `in-use` | Process bound, unprotected | None |
| `claimed` | Tracked by Harbormaster | Soft (visible in TUI) |
| `locked` | Daemon holds socket | Hard (`EADDRINUSE` on conflict) |
| `reserved` | Pending assignment (10s TTL) | Hard during TTL |

## Components

### `harbormasterd` — The Daemon
- Systemd service, starts on boot
- Holds bound sockets for all locked ports
- HTTP API on `127.0.0.1:19191`
- MCP server on stdio (for agent tool use)
- SQLite for persistent lock state
- Auto-refreshes port list every 2-3s via `ss`/`psutil`

### `harbor` — TUI
- Python + Textual
- Vertical layout, touch-primary (mobile-friendly)
- Shows localhost + Tailscale interfaces
- ↓ incoming / ↑ outgoing indicators
- Lock / Evict / Copy actions per port
- Connects to daemon socket for live state

### `hm` — CLI
- `hm request [port]` — get a safe port to bind to
- `hm lock [port]` — lock a port
- `hm unlock [port]` — release a lock
- `hm evict [port]` — kill the process on a port, then lock it
- `hm list` — show all ports and their states
- `hm status` — daemon health check

### MCP Server
- Exposes Harbormaster as MCP tools for AI agents
- Tools: `request_port`, `lock_port`, `unlock_port`, `evict_port`, `list_ports`
- Destructive actions (`evict`, `lock`) trigger user confirmation
- Agents don't need onboarding — enforcement is universal regardless

## Port Negotiation Flow

```
Agent wants port 3000
        ↓
GET /request?port=3000   (or: hm request 3000)
        ↓
Daemon checks:
  locked?  → scan up
  in-use?  → scan up
  free?    → reserve for 10s, return port
        ↓
Agent gets {"assigned": 3001, "reason": "3000 locked by node PID 1234"}
        ↓
Agent binds to 3001
        ↓
Agent calls POST /claim {"port": 3001}   (optional, enables TUI tracking)
```

## Why Not Just Use...

- **portreserve** — ancient, no API, no allocation logic, no TUI
- **Port Authority / port-manager** — view-only or subdomain mapping, no hard enforcement
- **Firewall rules** — require root, no negotiation, no TUI

## Tech Stack

- Language: Python 3.11+
- TUI: [Textual](https://github.com/Textualize/textual)
- Daemon HTTP: FastAPI (lightweight)
- MCP: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- Port scanning: `psutil` + `ss`
- State: SQLite via `aiosqlite`
- Service: systemd unit file

## Installation

> Coming soon

## Roadmap

- [ ] Core daemon with socket locking
- [ ] HTTP API (`/request`, `/lock`, `/unlock`, `/evict`, `/claim`, `/list`)
- [ ] SQLite state persistence
- [ ] TUI (Textual, vertical layout, touch-friendly)
- [ ] Tailscale interface detection
- [ ] `hm` CLI
- [ ] MCP server with user confirmation
- [ ] systemd service + install script
- [ ] Homebrew/pipx packaging
- [ ] CLAUDE.md snippet for AI agent integration
- [ ] Docker support

## Contributing

Design phase — issues and discussion welcome. Implementation starting soon.

---

*Named after the harbor authority officer who controls which ships dock at which berths.*
