from __future__ import annotations
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from harbormaster.models import PortRecord, PortState


class StateDB:
    def __init__(self, db_path: Path):
        self._path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS ports (
                port INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                pid INTEGER,
                process_name TEXT,
                reserved_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def get_port(self, port: int) -> PortRecord | None:
        async with self._db.execute(
            "SELECT * FROM ports WHERE port = ?", (port,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    async def set_port(self, record: PortRecord) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("""
            INSERT INTO ports (port, state, pid, process_name, reserved_until, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(port) DO UPDATE SET
                state=excluded.state,
                pid=excluded.pid,
                process_name=excluded.process_name,
                reserved_until=excluded.reserved_until,
                updated_at=excluded.updated_at
        """, (
            record.port,
            record.state.value,
            record.pid,
            record.process_name,
            record.reserved_until.isoformat() if record.reserved_until else None,
            now,
            now,
        ))
        await self._db.commit()

    async def remove_port(self, port: int) -> None:
        await self._db.execute("DELETE FROM ports WHERE port = ?", (port,))
        await self._db.commit()

    async def list_ports(self) -> list[PortRecord]:
        async with self._db.execute("SELECT * FROM ports ORDER BY port") as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def get_locked_ports(self) -> list[PortRecord]:
        async with self._db.execute(
            "SELECT * FROM ports WHERE state = ?", (PortState.LOCKED.value,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def get_reserved_ports(self) -> list[PortRecord]:
        async with self._db.execute(
            "SELECT * FROM ports WHERE state = ?", (PortState.RESERVED.value,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_record(r) for r in rows]

    async def expire_reservations(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("""
            DELETE FROM ports
            WHERE state = ? AND reserved_until IS NOT NULL AND reserved_until < ?
        """, (PortState.RESERVED.value, now))
        await self._db.commit()

    def _row_to_record(self, row: aiosqlite.Row) -> PortRecord:
        return PortRecord(
            port=row["port"],
            state=PortState(row["state"]),
            pid=row["pid"],
            process_name=row["process_name"],
            reserved_until=(
                datetime.fromisoformat(row["reserved_until"])
                if row["reserved_until"] else None
            ),
        )
