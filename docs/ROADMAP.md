# Harbormaster Roadmap

## Completed

- **Plan 1** — Daemon backend: config, state DB, port scanner, lock engine, process watcher, Tailscale detection, HTTP API, systemd service
- **Plan 2** — User-facing layer: `hm` CLI, MCP server, Textual TUI, approval gateways (ntfy, Telegram, webhook, Slack, Discord), gateway factory

## Planned

### Plan 3a — Ship v0.2.0
Polish the CLI (`hm` error messages, interactive reserve prompt, shell completion), add integration tests against a live daemon, write README, publish to PyPI.

### Plan 3b — Port Expiry Notifications
New daemon feature: notify via the configured gateway when a reserved port is about to expire or a claimed port's process has died. Adds a notification-only (no approval) gateway code path.

### Plan 3c — Web UI
Browser-based port dashboard as an alternative to the Textual TUI. Served by the daemon or as a separate static build. Real-time updates, same action set as the TUI.
