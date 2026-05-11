# Harbormaster Plan 3c Design — Web UI Dashboard

**Date:** 2026-05-11
**Status:** Approved

---

## Scope

A browser-based port dashboard served directly by the existing daemon. Provides the same port management actions as the Textual TUI — lock, unlock, evict, reserve, unreserve — plus live approval handling. No separate process, no build tooling, no external JS dependencies.

---

## Architecture

### Serving

A new module `src/harbormaster/web.py` exposes one function:

```python
def build_ui_response(secret: str) -> str
```

It reads `src/harbormaster/static/index.html` via `importlib.resources`, injects the daemon secret as a JS constant (`const HM_SECRET = "...";`), and returns the completed HTML string.

`build_app()` in `api.py` gains a new route:

```
GET /ui  →  text/html, no auth required
```

The route calls `build_ui_response(cfg.secret)` and returns the HTML. No auth is required to load the page — the secret is embedded by the server at serve time.

### Package data

`pyproject.toml` gains a `[tool.setuptools.package-data]` entry so `static/index.html` is included in the installed package:

```toml
[tool.setuptools.package-data]
harbormaster = ["static/*.html"]
```

---

## HTML/JS Structure

`src/harbormaster/static/index.html` — single self-contained file. Inline CSS and JS. No external dependencies (no CDN, no npm).

### Layout (option B: table + approval banner)

1. **Header bar** — "⚓ Harbormaster" title, daemon status indicator (green dot = ok, red = unreachable), port count
2. **Approval banner** — hidden by default (`display: none`). Appears full-width in orange when `GET /approvals` returns one or more pending requests. Each approval shows action + port + requester, with Allow and Deny buttons inline.
3. **Port table** — columns: PORT / STATE / PROCESS / PID / RESERVED UNTIL / ACTIONS
   - State rendered as colored badges: locked (green), claimed (orange), reserved (blue), in-use (gray)
   - Per-row action buttons rendered based on state:
     - `locked` → Unlock, Evict
     - `claimed` → Lock, Evict
     - `reserved` → Unreserve
     - `in-use` → Lock, Evict

### Polling

```javascript
setInterval(refresh, 2500);
```

`refresh()` calls `GET /list` and `GET /approvals` in parallel using `Promise.all`. On success, re-renders the table and updates the approval banner. On network failure (daemon unreachable), updates the status indicator to red and clears the table.

### Auth

All `fetch()` calls include:

```javascript
headers: { "X-Harbormaster-Secret": HM_SECRET }
```

`HM_SECRET` is a JS constant injected into the HTML by `build_ui_response` at serve time. The user never configures anything in the browser.

### Action flow

Each action button calls the corresponding API endpoint then immediately calls `refresh()` — no waiting for the next poll interval. Example: clicking Unlock on port 3000 calls `POST /unlock` with `{"port": 3000}`, then refreshes.

---

## API Endpoints Used

All existing — no new endpoints required:

| Endpoint | Used for |
|----------|----------|
| `GET /health` | Status bar |
| `GET /list` | Port table |
| `GET /approvals` | Approval banner |
| `POST /approvals/{id}/respond` | Allow/Deny buttons |
| `POST /lock` | Lock action |
| `POST /unlock` | Unlock action |
| `POST /evict` | Evict action |
| `DELETE /reserve/{port}` | Unreserve action |

---

## Visual Style

GitHub dark theme matching the Textual TUI:
- Background: `#0d1117`
- Surface: `#161b22`
- Border: `#30363d`
- Text: `#e6edf3`
- Muted: `#8b949e`
- Green (locked): `#3fb950`
- Orange (claimed): `#f0883e`
- Blue (reserved): `#58a6ff`
- Red (danger/evict): `#f85149`

---

## Testing

`tests/test_web.py` — unit tests for `build_ui_response`:

1. Assert returned HTML contains `HM_SECRET` injected correctly
2. Assert HTML contains required DOM element IDs (`port-table`, `approval-banner`)
3. Assert HTML references the correct API endpoint paths (`/list`, `/approvals`, `/unlock`, `/lock`, `/evict`)
4. Assert `GET /ui` route returns `200 text/html` via the existing test client pattern

No browser automation (Selenium/Playwright) — the JS behavior is simple enough that endpoint coverage + DOM structure checks are sufficient.

---

## Out of Scope

- WebSocket / Server-Sent Events for push updates (polling at 2.5s is sufficient)
- Authentication UI (secret embedded at serve time)
- Mobile-optimized layout
- Dark/light theme toggle
- Pagination (same as TUI — show all ports)
