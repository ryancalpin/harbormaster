# Harbormaster Plan 3a Design — Ship v0.2.0

**Date:** 2026-05-10
**Status:** Approved

---

## Scope

Four deliverables that together constitute a shippable v0.2.0 release:

1. README + documentation
2. Build-ready PyPI packaging (no publish step)
3. CLI polish (daemon error messages, interactive reserve prompt, shell completion)
4. Integration tests against a live daemon

---

## 1. README + Documentation

A single `README.md` at the project root. Content:

- **Installation** — `pip install harbormaster` (once published); for now, `pip install -e .`
- **Quickstart** — start daemon, run `hm list`, `hm request`, `hm reserve`
- **`hm` command reference** — table of all subcommands with args and brief description
- **TUI** — ASCII screenshot or description, how to launch (`harbormaster --tui`)
- **MCP** — one-paragraph config block showing how to add harbormaster to an MCP client config (`harbormaster --mcp`)
- **Configuration reference** — all `~/.config/harbormaster/config.toml` keys, types, defaults, and descriptions
- **Approval gateways** — brief section per gateway (ntfy, Telegram, webhook, Slack, Discord) with required config keys

No separate docs site. All content lives in `README.md`.

---

## 2. PyPI Packaging (Build-Ready)

**`pyproject.toml` additions:**

- `license = "MIT"`
- `classifiers`:
  - `"License :: OSI Approved :: MIT License"`
  - `"Programming Language :: Python :: 3"`, `":: 3.11"`, `":: 3.12"`, `":: 3.13"`
  - `"Topic :: System :: Networking"`
  - `"Development Status :: 4 - Beta"`
- `[project.urls]`: `Homepage`, `Source` (GitHub), `Bug Tracker`

**`LICENSE` file:** MIT license text with current year and author name.

**CI check (`.github/workflows/ci.yml`):** Add a `build` step after tests:
```yaml
- name: Build and check wheel
  run: |
    pip install build twine
    python -m build
    twine check dist/*
```

This verifies the wheel and sdist are valid without publishing. No PyPI token needed.

---

## 3. CLI Polish

### 3a. Daemon-down error messages

Currently a connection error produces a raw `httpx.ConnectError` traceback. New behavior: catch `httpx.ConnectError` (and `httpx.RemoteProtocolError`) in `build_client` or a shared error handler, print a clean message, and exit 1:

```
harbormaster daemon is not running.
Start it with: harbormaster
```

Implementation: wrap the `client.get/post/delete` calls in each command with a helper `def api_call(fn, *args, **kwargs)` that catches connection errors and prints the message.

### 3b. Interactive `hm reserve` prompt

If `hm reserve` is invoked without `--port`, prompt interactively:

```
Port to reserve: _
```

Use `input()` (no extra dependency). Validate the input is a valid port number before proceeding. If stdin is not a TTY (e.g. piped), print an error and exit 1.

### 3c. Shell completion via shtab

Add a `hm completion` subcommand:

```
hm completion {bash,zsh,fish}
```

Prints the static completion script to stdout. User installs it by redirecting:

```bash
hm completion bash > ~/.bash_completion.d/hm
hm completion zsh > ~/.zfunc/_hm
hm completion fish > ~/.config/fish/completions/hm.fish
```

Implementation: `shtab.complete(parser, shell)` where `parser` is the existing argparse parser. `shtab` added as a dependency in `pyproject.toml` (`shtab>=1.6`).

`pyproject.toml` documents the installation one-liner in a comment or README section.

---

## 4. Integration Tests

### Fixture design

`tests/integration/conftest.py` provides a session-scoped `daemon` fixture:

1. Creates a temporary directory with a test `config.toml` (no approval gateway, ephemeral DB path)
2. Spawns `harbormaster` subprocess with `--config <tmpdir>/config.toml`
3. Polls `GET /health` with 5s timeout (100ms intervals)
4. Yields a configured `httpx.Client` (or `DaemonClient`) pointed at the daemon's port
5. On teardown: sends `SIGTERM` to subprocess, waits up to 3s, then `SIGKILL` if needed; removes temp dir

Port selection: use a fixed test port (e.g. `19999`) or pick a random available port and pass it via env var / config override.

### Test coverage

Marked `@pytest.mark.integration`. Excluded from default `pytest` run via `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-m 'not integration'"
```

Run with: `pytest -m integration`

Tests:
1. **Health check** — `GET /health` returns 200
2. **Request → lock → unlock cycle** — request port, lock it, unlock it, verify state transitions
3. **Reserve → list** — reserve a port, `GET /ports` shows it reserved
4. **Evict** — lock a port, evict it, verify it's gone
5. **Status** — `GET /status` returns expected fields
6. **Daemon-down CLI message** — (unit test, not integration) stop daemon, run `hm list`, verify stderr contains the friendly message

---

## Testing Strategy

- Unit tests remain in `tests/` (no marker) — run on every `pytest` invocation
- Integration tests in `tests/integration/` with `@pytest.mark.integration` — run separately
- CI runs unit tests on every push; integration tests can be a separate job or manual trigger
- `build`/`twine check` runs after tests in CI

---

## Out of Scope

- Publishing to PyPI (manual step, future)
- Docs site / mkdocs
- Windows support for shell completion install paths
- Telegram concurrent approval handling (deferred to future plan)
- Webhook response signing (deferred to future plan)
