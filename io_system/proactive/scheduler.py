"""ProactiveScheduler — sqlite-backed self-triggered check-ins.

The agent schedules check-ins via the ``schedule_proactive_check_in`` tool.
A background thread polls every ``poll_interval_seconds`` seconds, claims any
due rows atomically, and invokes ``fire_callback`` with each row. The callback
is responsible for turning the saved context into an outbound message.

Persistence is sqlite so scheduled tasks survive restarts.
"""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# The scheduler hands each due row to this callback. Row keys:
#   id, conversation_id, fire_at, context, status, created_at, fired_at.
FireCallback = Callable[[Dict[str, Any]], None]


SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_check_ins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    fire_at TEXT NOT NULL,
    context TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    fired_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_fire_at
    ON scheduled_check_ins (fire_at);
"""


def _to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class ProactiveScheduler:
    def __init__(
        self,
        db_path: str,
        fire_callback: FireCallback,
        poll_interval_seconds: float = 30.0,
    ):
        self.db_path = str(db_path)
        self.fire_callback = fire_callback
        self.poll_interval = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._init_db()

    # ----- persistence -----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # ----- public API -----

    def schedule(
        self, conversation_id: str, fire_at: datetime, context: str
    ) -> int:
        fire_at_iso = _to_utc_iso(fire_at)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO scheduled_check_ins (conversation_id, fire_at, context) "
                "VALUES (?, ?, ?)",
                (conversation_id, fire_at_iso, context),
            )
            check_in_id = cur.lastrowid
        logger.info(
            "[ProactiveScheduler] scheduled #%s fire_at=%s context=%r",
            check_in_id, fire_at_iso, context[:80],
        )
        return check_in_id

    def cancel(self, check_in_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE scheduled_check_ins SET status='cancelled' "
                "WHERE id = ? AND status = 'pending'",
                (check_in_id,),
            )
            return cur.rowcount > 0

    def list_pending(
        self, conversation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM scheduled_check_ins WHERE status = 'pending'"
        params: tuple = ()
        if conversation_id is not None:
            sql += " AND conversation_id = ?"
            params = (conversation_id,)
        sql += " ORDER BY fire_at ASC"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    # ----- background loop -----

    def _claim_due(self) -> List[Dict[str, Any]]:
        """Atomically mark and return all check-ins past their fire_at."""
        now_iso = _to_utc_iso(datetime.now(timezone.utc))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM scheduled_check_ins "
                "WHERE status = 'pending' AND fire_at <= ?",
                (now_iso,),
            ).fetchall()
            if rows:
                ids = [r["id"] for r in rows]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE scheduled_check_ins "
                    f"SET status = 'fired', fired_at = ? "
                    f"WHERE id IN ({placeholders})",
                    (now_iso, *ids),
                )
            conn.execute("COMMIT")
        return [dict(r) for r in rows]

    def _loop(self) -> None:
        logger.info(
            "[ProactiveScheduler] loop started; poll_interval=%ss db=%s",
            self.poll_interval, self.db_path,
        )
        while not self._stop_event.is_set():
            try:
                for row in self._claim_due():
                    try:
                        self.fire_callback(row)
                    except Exception:
                        logger.exception(
                            "[ProactiveScheduler] fire_callback raised for check-in %s",
                            row.get("id"),
                        )
            except Exception:
                logger.exception("[ProactiveScheduler] poll cycle errored")
            self._stop_event.wait(self.poll_interval)
        logger.info("[ProactiveScheduler] loop stopped")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ProactiveScheduler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
