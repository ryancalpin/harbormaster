# Harbormaster Plan 3c — Web UI Dashboard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a browser-based port dashboard served by the existing daemon at `GET /ui` — no build tooling, no extra process, vanilla JS polling every 2.5 seconds.

**Architecture:** A new `web.py` module reads `static/index.html` via `importlib.resources`, injects the daemon secret as a JS constant, and returns the completed HTML. `build_app()` gets a `GET /ui` route (auth-exempt), and `AuthMiddleware` is updated to skip the secret check for that path. All JS in the HTML calls the existing JSON API endpoints.

**Tech Stack:** Python 3.11+, Starlette, `importlib.resources`, vanilla JS (no npm, no bundler)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/harbormaster/web.py` | Create | `build_ui_response(secret)` — read HTML, inject secret |
| `src/harbormaster/static/index.html` | Create | Complete self-contained dashboard (inline CSS + JS) |
| `src/harbormaster/api.py` | Modify | Skip auth for `/ui`; add `GET /ui` route |
| `pyproject.toml` | Modify | `package-data` so `static/index.html` ships with the package |
| `tests/test_web.py` | Create | Unit tests for `build_ui_response` and `GET /ui` route |

---

### Task 1: web.py module and static/index.html

**Files:**
- Create: `src/harbormaster/static/index.html`
- Create: `src/harbormaster/web.py`
- Create: `tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web.py
import pytest
from harbormaster.web import build_ui_response


def test_secret_injected():
    html = build_ui_response("my-test-secret")
    assert 'const HM_SECRET = "my-test-secret"' in html


def test_required_dom_ids():
    html = build_ui_response("s")
    assert 'id="port-table"' in html
    assert 'id="approval-banner"' in html


def test_api_endpoints_referenced():
    html = build_ui_response("s")
    assert "/list" in html
    assert "/approvals" in html
    assert "/unlock" in html
    assert "/lock" in html
    assert "/evict" in html
    assert "/reserve/" in html


def test_placeholder_not_in_output():
    html = build_ui_response("real-secret")
    assert "__HM_SECRET__" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'harbormaster.web'`

- [ ] **Step 3: Create the static directory and index.html**

Create directory `src/harbormaster/static/` then write `src/harbormaster/static/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Harbormaster</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace; font-size: 14px; }

#header { display: flex; align-items: center; gap: 16px; padding: 12px 20px; background: #161b22; border-bottom: 1px solid #30363d; }
#header h1 { font-size: 16px; font-weight: 600; color: #e6edf3; }
#status-dot { width: 8px; height: 8px; border-radius: 50%; background: #3fb950; display: inline-block; margin-right: 4px; }
#status-text { font-size: 12px; color: #8b949e; }
#port-count { font-size: 12px; color: #8b949e; margin-left: auto; }

#approval-banner { display: none; background: #2a1a00; border-left: 4px solid #f0883e; }
.approval-item { display: flex; align-items: center; gap: 12px; padding: 10px 20px; border-bottom: 1px solid #30363d; }
.approval-item:last-child { border-bottom: none; }
.approval-info { flex: 1; color: #f0883e; font-size: 13px; }
.approval-info strong { color: #e6edf3; }
.btn-allow { background: #1f3a1f; color: #3fb950; border: 1px solid #3fb950; border-radius: 4px; padding: 4px 12px; cursor: pointer; font-size: 12px; }
.btn-deny { background: #3a1f1f; color: #f85149; border: 1px solid #f85149; border-radius: 4px; padding: 4px 12px; cursor: pointer; font-size: 12px; }
.btn-allow:hover { background: #2d4a2d; }
.btn-deny:hover { background: #4a2d2d; }

#table-container { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead th { padding: 8px 16px; text-align: left; font-size: 11px; font-weight: 600; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #30363d; background: #161b22; }
tbody tr { border-bottom: 1px solid #21262d; }
tbody tr:hover { background: #161b22; }
tbody td { padding: 8px 16px; font-size: 13px; }
.port-num { color: #58a6ff; font-family: monospace; font-weight: 600; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-locked { background: #1f3a1f; color: #3fb950; }
.badge-claimed { background: #2a1f0a; color: #f0883e; }
.badge-reserved { background: #1a2a3a; color: #58a6ff; }
.badge-in-use { background: #21262d; color: #8b949e; }
.process-name { color: #e6edf3; }
.pid { color: #8b949e; font-family: monospace; }
.reserved-until { color: #8b949e; font-size: 12px; }
.actions { display: flex; gap: 6px; flex-wrap: wrap; }
.btn-action { background: #21262d; color: #cdd9e5; border: 1px solid #30363d; border-radius: 4px; padding: 3px 10px; cursor: pointer; font-size: 12px; }
.btn-action:hover { background: #30363d; }
.btn-danger { color: #f85149; border-color: #f85149; }
.btn-danger:hover { background: #2d1a1a; }
.empty-row td { text-align: center; color: #8b949e; padding: 32px; }
</style>
</head>
<body>

<div id="header">
  <h1>⚓ Harbormaster</h1>
  <span><span id="status-dot"></span><span id="status-text">connecting...</span></span>
  <span id="port-count"></span>
</div>

<div id="approval-banner"></div>

<div id="table-container">
  <table>
    <thead>
      <tr>
        <th>Port</th>
        <th>State</th>
        <th>Process</th>
        <th>PID</th>
        <th>Reserved Until</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="port-table">
      <tr class="empty-row"><td colspan="6">Loading...</td></tr>
    </tbody>
  </table>
</div>

<script>
const HM_SECRET = '__HM_SECRET__';
const H = { 'X-Harbormaster-Secret': HM_SECRET, 'Content-Type': 'application/json' };

function api(method, path, body) {
  return fetch(path, { method, headers: H, body: body ? JSON.stringify(body) : undefined });
}

function badge(state) {
  const cls = {
    locked: 'badge-locked',
    claimed: 'badge-claimed',
    reserved: 'badge-reserved',
    'in-use': 'badge-in-use',
  }[state] || 'badge-in-use';
  return `<span class="badge ${cls}">${state}</span>`;
}

function rowActions(p) {
  const btns = [];
  if (p.state === 'locked') {
    btns.push(`<button class="btn-action" onclick="act('POST','/unlock',{port:${p.port}})">Unlock</button>`);
    btns.push(`<button class="btn-action btn-danger" onclick="act('POST','/evict',{port:${p.port}})">Evict</button>`);
  } else if (p.state === 'claimed' || p.state === 'in-use') {
    btns.push(`<button class="btn-action" onclick="act('POST','/lock',{port:${p.port}})">Lock</button>`);
    btns.push(`<button class="btn-action btn-danger" onclick="act('POST','/evict',{port:${p.port}})">Evict</button>`);
  } else if (p.state === 'reserved') {
    btns.push(`<button class="btn-action btn-danger" onclick="act('DELETE','/reserve/${p.port}',null)">Unreserve</button>`);
  }
  return `<div class="actions">${btns.join('')}</div>`;
}

async function act(method, path, body) {
  await api(method, path, body);
  refresh();
}

async function respond(requestId, result) {
  await api('POST', `/approvals/${requestId}/respond`, { result });
  refresh();
}

function renderApprovals(approvals) {
  const banner = document.getElementById('approval-banner');
  if (!approvals || approvals.length === 0) {
    banner.style.display = 'none';
    banner.innerHTML = '';
    return;
  }
  banner.style.display = 'block';
  banner.innerHTML = approvals.map(a => `
    <div class="approval-item">
      <div class="approval-info">
        ⚠ <strong>${a.action.toUpperCase()}</strong> port <strong>:${a.port}</strong>
        ${a.process_name ? `— ${a.process_name} (PID ${a.pid})` : ''}
        ${a.requester && a.requester !== 'unknown' ? `— ${a.requester}` : ''}
      </div>
      <button class="btn-allow" onclick="respond('${a.request_id}','allow')">Allow</button>
      <button class="btn-deny" onclick="respond('${a.request_id}','deny')">Deny</button>
    </div>
  `).join('');
}

function renderPorts(ports) {
  const tbody = document.getElementById('port-table');
  if (!ports || ports.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="6">No ports registered.</td></tr>';
    return;
  }
  tbody.innerHTML = ports.map(p => `
    <tr>
      <td class="port-num">:${p.port}</td>
      <td>${badge(p.state)}</td>
      <td class="process-name">${p.process_name || '—'}</td>
      <td class="pid">${p.pid || '—'}</td>
      <td class="reserved-until">${p.reserved_until ? p.reserved_until.replace('T',' ').slice(0,16) : '—'}</td>
      <td>${rowActions(p)}</td>
    </tr>
  `).join('');
}

async function refresh() {
  try {
    const [listRes, approvalsRes] = await Promise.all([
      api('GET', '/list'),
      api('GET', '/approvals'),
    ]);
    const listData = await listRes.json();
    const approvalsData = await approvalsRes.json();
    const ports = listData.ports || [];

    document.getElementById('status-dot').style.background = '#3fb950';
    document.getElementById('status-text').textContent = 'daemon ok';
    document.getElementById('port-count').textContent =
      `${ports.length} port${ports.length !== 1 ? 's' : ''}`;

    renderPorts(ports);
    renderApprovals(approvalsData.approvals || []);
  } catch (_) {
    document.getElementById('status-dot').style.background = '#f85149';
    document.getElementById('status-text').textContent = 'daemon unreachable';
    document.getElementById('port-count').textContent = '';
    document.getElementById('port-table').innerHTML =
      '<tr class="empty-row"><td colspan="6">Cannot reach daemon.</td></tr>';
    document.getElementById('approval-banner').style.display = 'none';
  }
}

refresh();
setInterval(refresh, 2500);
</script>
</body>
</html>
```

- [ ] **Step 4: Create web.py**

```python
# src/harbormaster/web.py
from __future__ import annotations
import importlib.resources


def build_ui_response(secret: str) -> str:
    """Read static/index.html, inject the daemon secret, return completed HTML."""
    html = (
        importlib.resources.files("harbormaster")
        .joinpath("static/index.html")
        .read_text(encoding="utf-8")
    )
    return html.replace('__HM_SECRET__', secret)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_web.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/harbormaster/static/index.html src/harbormaster/web.py tests/test_web.py
git commit -m "feat: add web.py and static/index.html for browser dashboard"
```

---

### Task 2: GET /ui route and AuthMiddleware update

**Files:**
- Modify: `src/harbormaster/api.py`
- Modify: `tests/test_web.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_web.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from starlette.testclient import TestClient
from harbormaster.api import build_app
from harbormaster.config import HarbormasterConfig
from harbormaster.approval.tui_stub import TuiStubGateway

SECRET = "web-test-secret"


@pytest.fixture
def web_client():
    cfg = HarbormasterConfig()
    cfg.secret = SECRET
    db = AsyncMock()
    db.list_ports = AsyncMock(return_value=[])
    lock_engine = MagicMock()
    lock_engine.locked_ports = MagicMock(return_value=set())
    holds = MagicMock()
    gateway = TuiStubGateway()
    app = build_app(cfg=cfg, db=db, lock_engine=lock_engine, holds=holds, gateway=gateway)
    return TestClient(app, raise_server_exceptions=False)


def test_ui_route_returns_html(web_client):
    r = web_client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Harbormaster" in r.text
    assert SECRET in r.text


def test_ui_route_no_auth_required(web_client):
    """GET /ui must be accessible without the secret header."""
    r = web_client.get("/ui")  # no X-Harbormaster-Secret header
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_web.py::test_ui_route_returns_html tests/test_web.py::test_ui_route_no_auth_required -v
```

Expected: FAIL — `/ui` route doesn't exist yet, returns 403 from AuthMiddleware.

- [ ] **Step 3: Update AuthMiddleware to exempt /ui**

In `src/harbormaster/api.py`, update the `dispatch` method of `AuthMiddleware`:

```python
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, secret: str):
        super().__init__(app)
        self._secret = secret

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/ui":
            return await call_next(request)
        if request.headers.get("X-Harbormaster-Secret") != self._secret:
            return JSONResponse({"error": "unauthorized"}, status_code=403)
        return await call_next(request)
```

- [ ] **Step 4: Add GET /ui route to build_app()**

In `src/harbormaster/api.py`, add the import at the top:

```python
from harbormaster.web import build_ui_response
```

Add the handler inside `build_app()`, before the `routes` list:

```python
async def ui(request: Request) -> Response:
    from starlette.responses import HTMLResponse
    return HTMLResponse(build_ui_response(cfg.secret))
```

Add the route to the `routes` list:

```python
routes = [
    Route("/ui", ui),
    Route("/health", health),
    Route("/request", request_port),
    Route("/lock", lock_port, methods=["POST"]),
    Route("/unlock", unlock_port, methods=["POST"]),
    Route("/evict", evict_port, methods=["POST"]),
    Route("/claim", claim_port, methods=["POST"]),
    Route("/reserve", reserve_port, methods=["POST"]),
    Route("/reserve/{port:int}", unreserve_port, methods=["DELETE"]),
    Route("/list", list_ports),
    Route("/approvals", list_approvals),
    Route("/approvals/{request_id}/respond", respond_approval, methods=["POST"]),
    Route("/ports/live", live_ports),
]
```

- [ ] **Step 5: Run all tests**

```bash
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/harbormaster/api.py tests/test_web.py
git commit -m "feat: add GET /ui route serving the web dashboard (auth-exempt)"
```

---

### Task 3: Package data for static/index.html

**Files:**
- Modify: `pyproject.toml`

Without this, `pip install harbormaster` won't include `static/index.html` and `importlib.resources` will fail.

- [ ] **Step 1: Add package-data to pyproject.toml**

In `pyproject.toml`, add after `[tool.setuptools.packages.find]`:

```toml
[tool.setuptools.package-data]
harbormaster = ["static/*.html"]
```

- [ ] **Step 2: Reinstall the package and verify the file is included**

```bash
pip install -e . && python -c "import importlib.resources; print(importlib.resources.files('harbormaster').joinpath('static/index.html').read_text()[:50])"
```

Expected: prints the first 50 characters of the HTML file (starts with `<!DOCTYPE html>`).

- [ ] **Step 3: Run all tests once more**

```bash
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: include static/index.html in package data for web UI"
```

---

## Self-Review Checklist

- [x] Spec coverage: `build_ui_response` ✅ Task 1, `GET /ui` route ✅ Task 2, auth-exempt ✅ Task 2, `package-data` ✅ Task 3, all 4 test assertions ✅ Task 1 + 2
- [x] No placeholders: all steps have complete code
- [x] Type consistency: `build_ui_response(secret: str) -> str` defined in Task 1 and called as `build_ui_response(cfg.secret)` in Task 2 ✅
- [x] `__HM_SECRET__` placeholder replaced in `web.py` and verified absent in test `test_placeholder_not_in_output` ✅
- [x] `HTMLResponse` import: used inline inside the handler to avoid import-order issues ✅
- [x] Auth bypass: `/ui` path check added before secret check in `AuthMiddleware.dispatch` ✅
