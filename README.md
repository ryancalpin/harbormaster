# Harbormaster

Port allocation daemon for developers and AI agents. Harbormaster tracks which ports are in use on your machine and hands out clean port assignments on request — preventing "port already in use" errors across parallel dev servers, agent subprocesses, and long-running services.

## Installation

```bash
pip install harbormaster
```

Or from source:

```bash
git clone https://github.com/ryanc/harbormaster
cd harbormaster
pip install -e .
```

## Quickstart

Start the daemon (runs in the foreground):

```bash
harbormasterd
```

In another terminal, use the CLI:

```bash
hm list              # show all tracked ports
hm request           # get a free port (starting from 3000)
hm request 8000      # get a free port starting from 8000
hm lock 3001         # lock port 3001
hm unlock 3001       # release lock
hm reserve 3002      # reserve a port for later
hm status            # check daemon health
```

## hm Command Reference

| Command | Arguments | Description |
|---------|-----------|-------------|
| `hm request [port]` | `port` (default 3000) | Find and assign a free port at or above `port` |
| `hm lock <port>` | `port` | Lock a port (requires approval if gateway configured) |
| `hm unlock <port>` | `port` | Release a locked port |
| `hm evict <port>` | `port` | Kill the process on a port, then lock it |
| `hm claim <port>` | `--pid`, `--name` | Register an already-bound port as tracked |
| `hm reserve [port]` | `--ttl`, `--permanent` | Reserve a port for future use |
| `hm unreserve <port>` | `port` | Cancel a reservation |
| `hm list` | `--reserved`, `--json` | List all tracked ports |
| `hm status` | — | Show daemon health |
| `hm config` | — | Show config file path and contents |
| `hm completion <shell>` | `bash`, `zsh`, `tcsh` | Print shell completion script |

### Shell Completion

```bash
# bash
hm completion bash > ~/.bash_completion.d/hm

# zsh
hm completion zsh > ~/.zfunc/_hm

# tcsh
hm completion tcsh > ~/.tcshrc.d/hm
```

## TUI

A Textual-based terminal UI is included:

```bash
harbor
```

The TUI shows live port states, refreshes every 2.5 seconds, and surfaces approval modals when the daemon requests human confirmation for lock/evict actions.

## MCP Server

Harbormaster exposes an MCP server for AI agent integration. Add it to your MCP client config:

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

Available MCP tools: `request_port`, `claim_port`, `lock_port`, `unlock_port`, `evict_port`, `list_ports`, `daemon_status`.

## Configuration

Config file: `~/.config/harbormaster/config.toml` (created automatically on first run).

```toml
[daemon]
api_port = 19191        # port the daemon's HTTP API listens on
secret   = "..."        # shared secret for CLI/TUI/MCP auth (auto-generated)

[ports]
watch_range      = [1024, 49151]   # port range the scanner watches
display_priority = [               # ranges shown first in hm list
  "3000-3999", "4000-4999",
  "5000-5999", "8000-8999", "9000-9999"
]

[approval]
gateway = "tui"    # which gateway handles approval requests (tui, ntfy, telegram, webhook, slack, discord)
fallback = "tui"   # fallback if primary gateway fails
timeout  = 0       # seconds to wait before auto-denying (0 = wait indefinitely)
```

## Approval Gateways

When a lock or evict requires human approval, harbormaster routes the request through the configured gateway.

### ntfy

```toml
[approval]
gateway = "ntfy"

[gateways.ntfy]
topic  = "harbormaster"
server = "https://ntfy.sh"   # or your self-hosted instance
```

Subscribe on your phone; tap Allow or Deny. Harbormaster polls `<topic>-allow` and `<topic>-deny` for your response.

### Telegram

```toml
[approval]
gateway = "telegram"

[gateways.telegram]
bot_token = "YOUR_BOT_TOKEN"
chat_id   = "YOUR_CHAT_ID"
```

Get a bot token from @BotFather. Get your chat ID by messaging @userinfobot.

### Webhook

```toml
[approval]
gateway = "webhook"

[gateways.webhook]
url    = "https://your-server.example.com/approval"
secret = "hmac-signing-secret"
```

Harbormaster sends a signed POST with `{"request_id": "...", "port": ..., "action": "...", "reason": "..."}`. Respond with `{"result": "allow"}` or `{"result": "deny"}`.

### Slack

```toml
[approval]
gateway = "slack"

[gateways.slack]
webhook_url = "https://hooks.slack.com/services/..."
```

### Discord

```toml
[approval]
gateway = "discord"

[gateways.discord]
webhook_url = "https://discord.com/api/webhooks/..."
```

## License

MIT
