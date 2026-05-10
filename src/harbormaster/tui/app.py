from __future__ import annotations
import asyncio
from textual.app import App, ComposeResult
from textual.widgets import (
    DataTable, Button, Static, Label, Footer
)
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.reactive import reactive
from textual import on

from harbormaster.tui.client import DaemonClient


STATE_BADGE = {
    "locked": "🔒",
    "claimed": "◈",
    "reserved": "⏳",
    "in-use": "○",
    "open": " ",
}

FILTERS = ["all", "in", "out", "locked"]
FILTER_LABELS = ["ALL", "↓ IN", "↑ OUT", "🔒 Locked"]


class ApprovalModal(ModalScreen[str]):
    """Overlay shown when the daemon needs approval for a lock/evict action."""

    def __init__(self, approval: dict) -> None:
        super().__init__()
        self._approval = approval

    def compose(self) -> ComposeResult:
        a = self._approval
        detail = (
            f"Action:  {a['action'].upper()}\n"
            f"Port:    :{a['port']}\n"
            f"Process: {a.get('process_name') or 'unknown'} (PID {a.get('pid') or '?'})"
        )
        if a.get("requester"):
            detail += f"\n⚠ {a['requester']}"
        with Static(id="approval-dialog"):
            yield Label("⚓ Approval Required", id="approval-title")
            yield Label(detail, id="approval-detail")
            with Static(id="approval-buttons"):
                yield Button("✓ Allow", id="btn-allow", variant="success")
                yield Button("✗ Deny", id="btn-deny", variant="error")

    @on(Button.Pressed, "#btn-allow")
    def allow(self) -> None:
        self.dismiss("allow")

    @on(Button.Pressed, "#btn-deny")
    def deny(self) -> None:
        self.dismiss("deny")


class HarbormasterApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "⚓ HARBORMASTER"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "filter_all", "All", show=False),
        Binding("2", "filter_in", "In", show=False),
        Binding("3", "filter_out", "Out", show=False),
        Binding("4", "filter_locked", "Locked", show=False),
    ]

    _current_filter: reactive[str] = reactive("all")
    _selected_row: reactive[int | None] = reactive(None)
    _all_ports: list[dict] = []
    _daemon_ok: bool = False

    def compose(self) -> ComposeResult:
        yield Static("", id="header-bar")
        with Static(id="filter-bar"):
            for i, label in enumerate(FILTER_LABELS):
                yield Button(label, id=f"filter-{FILTERS[i]}", classes="-active" if i == 0 else "")
        yield DataTable(id="port-table", cursor_type="row", zebra_stripes=True)
        with Static(id="action-bar"):
            yield Button("🔒 Lock", id="btn-lock")
            yield Button("🔓 Unlock", id="btn-unlock")
            yield Button("⚡ Evict", id="btn-evict")
            yield Button("📋 Copy", id="btn-copy")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#port-table", DataTable)
        table.add_columns("", "PORT", "PROCESS", "PID", "STATE")
        self.set_interval(2.5, self._refresh_ports)
        self.set_interval(1.0, self._check_approvals)
        self.run_worker(self._refresh_ports(), exclusive=True)

    async def _refresh_ports(self) -> None:
        client = DaemonClient()
        try:
            async with client:
                live_data = await client.live_ports()
                health = await client.health()
            self._all_ports = live_data["ports"]
            self._daemon_ok = health.get("status") == "ok"
            ts_ip = live_data.get("tailscale_ip")
            self._render_table(ts_ip)
            locked = health.get("locked", 0)
            status = "🟢 daemon" if self._daemon_ok else "🔴 daemon"
            self.query_one("#header-bar", Static).update(
                f"⚓ HARBORMASTER   {status}   {locked} locked"
            )
        except Exception:
            self._daemon_ok = False
            self.query_one("#header-bar", Static).update(
                "⚓ HARBORMASTER   🔴 daemon offline"
            )

    def _render_table(self, tailscale_ip: str | None) -> None:
        table = self.query_one("#port-table", DataTable)
        table.clear()
        f = self._current_filter
        ports = self._all_ports

        if f == "in":
            ports = [p for p in ports if p.get("is_listen")]
        elif f == "out":
            ports = [p for p in ports if not p.get("is_listen")]
        elif f == "locked":
            ports = [p for p in ports if p.get("state") == "locked"]

        localhost = [p for p in ports if not tailscale_ip or p.get("interface") != tailscale_ip]
        tailscale = [p for p in ports if tailscale_ip and p.get("interface") == tailscale_ip]

        def add_section(label: str, rows: list[dict]) -> None:
            if not rows:
                return
            table.add_row("──", f"── {label} ──────────────────", "", "", "", key=f"__section_{label}")
            for row in rows:
                direction = "↓" if row.get("is_listen") else "↑"
                port_str = f":{row['port']}"
                process = row.get("process_name") or ""
                pid = str(row.get("pid") or "")
                badge = STATE_BADGE.get(row.get("state", "open"), "")
                table.add_row(direction, port_str, process, pid, badge, key=str(row["port"]))

        add_section("LOCALHOST", localhost)
        add_section("TAILSCALE", tailscale)

    async def _check_approvals(self) -> None:
        if not self._daemon_ok:
            return
        client = DaemonClient()
        try:
            async with client:
                approvals = await client.list_approvals()
        except Exception:
            return
        if not approvals:
            return
        approval = approvals[0]

        async def handle_approval() -> None:
            result = await self.push_screen_wait(ApprovalModal(approval))
            client2 = DaemonClient()
            try:
                async with client2:
                    await client2.respond_approval(approval["request_id"], result or "deny")
            except Exception:
                pass

        self.run_worker(handle_approval(), exclusive=False)

    @on(Button.Pressed, "#filter-all")
    def filter_all(self) -> None:
        self._set_filter("all")

    @on(Button.Pressed, "#filter-in")
    def filter_in(self) -> None:
        self._set_filter("in")

    @on(Button.Pressed, "#filter-out")
    def filter_out(self) -> None:
        self._set_filter("out")

    @on(Button.Pressed, "#filter-locked")
    def filter_locked(self) -> None:
        self._set_filter("locked")

    def action_filter_all(self) -> None:
        self._set_filter("all")

    def action_filter_in(self) -> None:
        self._set_filter("in")

    def action_filter_out(self) -> None:
        self._set_filter("out")

    def action_filter_locked(self) -> None:
        self._set_filter("locked")

    def action_refresh(self) -> None:
        self.run_worker(self._refresh_ports(), exclusive=True)

    def _set_filter(self, f: str) -> None:
        self._current_filter = f
        for filt in FILTERS:
            btn = self.query_one(f"#filter-{filt}", Button)
            if filt == f:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")
        ts_ip = None
        self._render_table(ts_ip)

    @on(DataTable.RowSelected)
    def row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value if event.row_key else None
        if key and key.startswith("__section_"):
            self._selected_row = None
            self.query_one("#action-bar").remove_class("visible")
            return
        try:
            self._selected_row = int(key) if key else None
        except (ValueError, TypeError):
            self._selected_row = None
        if self._selected_row is not None:
            self.query_one("#action-bar").add_class("visible")
        else:
            self.query_one("#action-bar").remove_class("visible")

    @on(Button.Pressed, "#btn-lock")
    def action_lock(self) -> None:
        if self._selected_row is None:
            return
        self.run_worker(self._do_lock(self._selected_row), exclusive=False)

    @on(Button.Pressed, "#btn-unlock")
    def action_unlock(self) -> None:
        if self._selected_row is None:
            return
        self.run_worker(self._do_unlock(self._selected_row), exclusive=False)

    @on(Button.Pressed, "#btn-evict")
    def action_evict(self) -> None:
        if self._selected_row is None:
            return
        self.run_worker(self._do_evict(self._selected_row), exclusive=False)

    @on(Button.Pressed, "#btn-copy")
    def action_copy(self) -> None:
        if self._selected_row is not None:
            self.notify(str(self._selected_row), title="Port copied")

    async def _do_lock(self, port: int) -> None:
        client = DaemonClient()
        try:
            async with client:
                await client.lock(port)
            await self._refresh_ports()
        except Exception as e:
            self.notify(f"Lock failed: {e}", severity="error")

    async def _do_unlock(self, port: int) -> None:
        client = DaemonClient()
        try:
            async with client:
                await client.unlock(port)
            await self._refresh_ports()
        except Exception as e:
            self.notify(f"Unlock failed: {e}", severity="error")

    async def _do_evict(self, port: int) -> None:
        client = DaemonClient()
        try:
            async with client:
                await client.evict(port)
            await self._refresh_ports()
        except Exception as e:
            self.notify(f"Evict failed: {e}", severity="error")


def main() -> None:
    app = HarbormasterApp()
    app.run()
