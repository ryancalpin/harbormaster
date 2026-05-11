from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

import httpx

from harbormaster.config import load_config
from harbormaster.utils import parse_ttl

# Re-export parse_ttl so existing imports from harbormaster.cli still work
__all__ = ["parse_ttl", "build_client", "api_call"]


def _daemon_down() -> NoReturn:
    print(
        "harbormaster daemon is not running.\nStart it with: harbormaster",
        file=sys.stderr,
    )
    sys.exit(1)


def api_call(fn, *args, **kwargs) -> httpx.Response:
    try:
        return fn(*args, **kwargs)
    except (httpx.ConnectError, httpx.RemoteProtocolError):
        _daemon_down()


def build_client(cfg=None) -> httpx.Client:
    if cfg is None:
        cfg = load_config()
    return httpx.Client(
        base_url=f"http://127.0.0.1:{cfg.api_port}",
        headers={"X-Harbormaster-Secret": cfg.secret},
        timeout=30,
    )


def _state_badge(state: str) -> str:
    return {"locked": "🔒", "claimed": "◈", "reserved": "⏳", "in-use": "○", "open": " "}.get(state, state)


def cmd_request(client: httpx.Client, port: int) -> None:
    r = api_call(client.get, "/request", params={"port": port})
    if r.status_code == 409:
        print(f"No available port found starting from {port}", file=sys.stderr)
        sys.exit(1)
    r.raise_for_status()
    print(r.json()["assigned"])


def cmd_lock(client: httpx.Client, port: int) -> None:
    r = api_call(client.post, "/lock", json={"port": port})
    if r.status_code == 403:
        print("Denied.", file=sys.stderr)
        sys.exit(1)
    r.raise_for_status()
    print(f"Port {port} locked.")


def cmd_unlock(client: httpx.Client, port: int) -> None:
    r = api_call(client.post, "/unlock", json={"port": port})
    r.raise_for_status()
    print(f"Port {port} unlocked.")


def cmd_evict(client: httpx.Client, port: int) -> None:
    r = api_call(client.post, "/evict", json={"port": port})
    if r.status_code == 403:
        print("Denied.", file=sys.stderr)
        sys.exit(1)
    if r.status_code == 409:
        print(r.json().get("error", "Eviction aborted."), file=sys.stderr)
        sys.exit(1)
    r.raise_for_status()
    data = r.json()
    print(f"Port {port} evicted (PID {data.get('evicted_pid')}) and locked.")


def cmd_claim(client: httpx.Client, port: int, pid: int | None, name: str) -> None:
    r = api_call(client.post, "/claim", json={"port": port, "pid": pid, "name": name})
    r.raise_for_status()
    print(f"Port {port} claimed.")


def cmd_reserve(client: httpx.Client, port: int | None, ttl_seconds: int | None, permanent: bool) -> None:
    if port is None:
        if not sys.stdin.isatty():
            print("hm reserve: port required when stdin is not a TTY", file=sys.stderr)
            sys.exit(1)
        raw = input("Port to reserve: ").strip()
        try:
            port = int(raw)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            print(f"Invalid port: {raw!r}", file=sys.stderr)
            sys.exit(1)

    if permanent:
        ttl = -1
    elif ttl_seconds is not None:
        ttl = ttl_seconds
    else:
        print(f"Reserve port {port} for how long?")
        choices = [("1 hour", 3600), ("8 hours", 28800), ("24 hours", 86400), ("Permanent", -1)]
        for i, (label, _) in enumerate(choices, 1):
            print(f"  {i}) {label}")
        try:
            choice = int(input("Choice [1-4]: ").strip()) - 1
            if not (0 <= choice < len(choices)):
                raise IndexError
            ttl = choices[choice][1]
        except (ValueError, IndexError):
            print("Invalid choice.", file=sys.stderr)
            sys.exit(1)

    r = api_call(client.post, "/reserve", json={"port": port, "ttl_seconds": ttl})
    if r.status_code == 409:
        print(r.json().get("error", "Port already reserved."), file=sys.stderr)
        sys.exit(1)
    if r.status_code == 403:
        print("Denied.", file=sys.stderr)
        sys.exit(1)
    r.raise_for_status()
    data = r.json()
    until = data.get("reserved_until", "permanent")
    print(f"Port {port} reserved until {until}.")


def cmd_unreserve(client: httpx.Client, port: int) -> None:
    r = api_call(client.delete, f"/reserve/{port}")
    if r.status_code == 404:
        print(f"Port {port} is not reserved.", file=sys.stderr)
        sys.exit(1)
    r.raise_for_status()
    print(f"Reservation on port {port} cancelled.")


def cmd_list(client: httpx.Client, reserved_only: bool, as_json: bool) -> None:
    r = api_call(client.get, "/list")
    r.raise_for_status()
    ports = r.json()["ports"]
    if reserved_only:
        ports = [p for p in ports if p["state"] == "reserved"]
    if as_json:
        print(json.dumps(ports, indent=2))
        return
    if not ports:
        print("No ports registered.")
        return
    print(f"{'PORT':<8} {'STATE':<10} {'PROCESS':<16} {'PID':<8} {'INFO'}")
    print("-" * 56)
    for p in ports:
        badge = _state_badge(p["state"])
        name = p.get("process_name") or ""
        pid = p.get("pid") or ""
        info = p.get("reserved_until") or ""
        print(f":{p['port']:<7} {p['state']:<10} {name:<16} {str(pid):<8} {info} {badge}")


def cmd_status(client: httpx.Client) -> None:
    r = api_call(client.get, "/health")
    r.raise_for_status()
    data = r.json()
    print(f"Daemon: {data['status']}")
    print(f"Locked ports: {data['locked']}")


def cmd_config() -> None:
    from harbormaster.config import _default_config_path
    path = _default_config_path()
    print(f"Config: {path}")
    if path.exists():
        print(path.read_text())
    else:
        print("(no config file — will be created on first daemon start)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hm", description="Harbormaster CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_req = sub.add_parser("request", help="Request a free port")
    p_req.add_argument("port", type=int, nargs="?", default=3000)

    p_lock = sub.add_parser("lock", help="Lock a port")
    p_lock.add_argument("port", type=int)

    p_unlock = sub.add_parser("unlock", help="Unlock a port")
    p_unlock.add_argument("port", type=int)

    p_evict = sub.add_parser("evict", help="Evict process on port then lock it")
    p_evict.add_argument("port", type=int)

    p_claim = sub.add_parser("claim", help="Register a port as tracked")
    p_claim.add_argument("port", type=int)
    p_claim.add_argument("--pid", type=int, default=None)
    p_claim.add_argument("--name", default="unknown")

    p_res = sub.add_parser("reserve", help="Reserve a port for future use")
    p_res.add_argument("port", type=int, nargs="?", default=None)
    p_res.add_argument("--ttl", default=None, help="e.g. 1h, 8h, 24h, 30m")
    p_res.add_argument("--permanent", action="store_true")

    p_unres = sub.add_parser("unreserve", help="Cancel a reservation")
    p_unres.add_argument("port", type=int)

    p_list = sub.add_parser("list", help="List ports")
    p_list.add_argument("--reserved", action="store_true", help="Show only reservations")
    p_list.add_argument("--json", action="store_true", dest="as_json")

    sub.add_parser("status", help="Daemon health")
    sub.add_parser("config", help="Show config")

    p_comp = sub.add_parser("completion", help="Print shell completion script")
    p_comp.add_argument("shell", choices=["bash", "zsh", "tcsh"])

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "completion":
        import shtab
        print(shtab.complete(parser, shell=args.shell))
        sys.exit(0)

    if args.command == "config":
        cmd_config()
        return

    try:
        client = build_client()
    except Exception as e:
        print(f"Cannot load config: {e}", file=sys.stderr)
        sys.exit(1)

    with client:
        if args.command == "request":
            cmd_request(client, args.port)
        elif args.command == "lock":
            cmd_lock(client, args.port)
        elif args.command == "unlock":
            cmd_unlock(client, args.port)
        elif args.command == "evict":
            cmd_evict(client, args.port)
        elif args.command == "claim":
            cmd_claim(client, args.port, args.pid, args.name)
        elif args.command == "reserve":
            ttl_seconds = parse_ttl(args.ttl) if args.ttl else None
            cmd_reserve(client, args.port, ttl_seconds, args.permanent)
        elif args.command == "unreserve":
            cmd_unreserve(client, args.port)
        elif args.command == "list":
            cmd_list(client, args.reserved, args.as_json)
        elif args.command == "status":
            cmd_status(client)
