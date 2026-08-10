from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class SeenStorage:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS seen_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL,
                    price TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(source, external_id)
                );

                CREATE TABLE IF NOT EXISTS poll_stats (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    total_seen INTEGER NOT NULL DEFAULT 0,
                    total_filtered INTEGER NOT NULL DEFAULT 0,
                    total_notified INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(poll_stats)").fetchall()
            }
            if "total_blocked_negative" not in columns:
                conn.execute(
                    "ALTER TABLE poll_stats ADD COLUMN total_blocked_negative INTEGER NOT NULL DEFAULT 0"
                )
            if "total_rejected_and" not in columns:
                conn.execute(
                    "ALTER TABLE poll_stats ADD COLUMN total_rejected_and INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                """
                INSERT OR IGNORE INTO poll_stats (id, total_seen, total_filtered, total_notified, updated_at)
                VALUES (1, 0, 0, 0, CURRENT_TIMESTAMP)
                """
            )
            conn.commit()

    def is_seen(self, source: str, external_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_orders WHERE source = ? AND external_id = ?",
                (source, external_id),
            ).fetchone()
            return row is not None

    def mark_seen(
        self,
        *,
        source: str,
        external_id: str,
        title: str,
        link: str,
        price: str,
    ) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO seen_orders (source, external_id, title, link, price, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        external_id,
                        title,
                        link,
                        price,
                        datetime.now(tz=UTC).isoformat(),
                    ),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def bump_stats(
        self,
        *,
        seen: int,
        filtered: int,
        blocked_negative: int,
        rejected_and: int,
        notified: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE poll_stats
                SET total_seen = total_seen + ?,
                    total_filtered = total_filtered + ?,
                    total_blocked_negative = total_blocked_negative + ?,
                    total_rejected_and = total_rejected_and + ?,
                    total_notified = total_notified + ?,
                    updated_at = ?
                WHERE id = 1
                """,
                (
                    int(seen),
                    int(filtered),
                    int(blocked_negative),
                    int(rejected_and),
                    int(notified),
                    datetime.now(tz=UTC).isoformat(),
                ),
            )
            conn.commit()

    def read_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT total_seen, total_filtered, total_blocked_negative, total_rejected_and, total_notified
                FROM poll_stats
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return {
                "total_seen": 0,
                "total_filtered": 0,
                "total_blocked_negative": 0,
                "total_rejected_and": 0,
                "total_notified": 0,
            }
        return {
            "total_seen": int(row["total_seen"]),
            "total_filtered": int(row["total_filtered"]),
            "total_blocked_negative": int(row["total_blocked_negative"]),
            "total_rejected_and": int(row["total_rejected_and"]),
            "total_notified": int(row["total_notified"]),
        }
