from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path


class SeenStorage:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0)
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

                CREATE TABLE IF NOT EXISTS kwork_notices (
                    notice_key TEXT PRIMARY KEY,
                    notice_value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS title_hashes (
                    title_hash TEXT PRIMARY KEY,
                    seen_at TEXT NOT NULL
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
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS order_runs (
                    source TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    found INTEGER NOT NULL,
                    passed INTEGER NOT NULL,
                    new_sent INTEGER NOT NULL,
                    parked INTEGER NOT NULL,
                    auth_error TEXT NOT NULL DEFAULT '',
                    reasons_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rejected_orders (
                    order_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (order_id, reason)
                );

                CREATE TABLE IF NOT EXISTS order_snapshots (
                    callback_key TEXT PRIMARY KEY,
                    external_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    link TEXT NOT NULL,
                    price TEXT NOT NULL,
                    user_id INTEGER,
                    username TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_feedback (
                    order_id TEXT PRIMARY KEY,
                    verdict TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    user_id INTEGER,
                    username TEXT NOT NULL DEFAULT '',
                    price_rub INTEGER,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS order_blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL UNIQUE,
                    added_at TEXT NOT NULL,
                    source TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_parked (
                    order_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    price TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    parked_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT
                );

                CREATE TABLE IF NOT EXISTS order_overrides (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    suggestion_id INTEGER,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS order_dynamic_red (
                    word TEXT PRIMARY KEY,
                    suggestion_id INTEGER,
                    added_at TEXT NOT NULL
                );
                """
            )
            run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(order_runs)").fetchall()}
            if "id" in run_columns:
                conn.execute("ALTER TABLE order_runs RENAME TO order_runs_old")
                conn.execute(
                    """
                    CREATE TABLE order_runs (
                        source TEXT PRIMARY KEY,
                        started_at TEXT NOT NULL,
                        found INTEGER NOT NULL,
                        passed INTEGER NOT NULL,
                        new_sent INTEGER NOT NULL,
                        parked INTEGER NOT NULL,
                        auth_error TEXT NOT NULL DEFAULT '',
                        reasons_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO order_runs (
                        source, started_at, found, passed, new_sent, parked, auth_error, reasons_json
                    )
                    SELECT source, started_at, found, passed, new_sent, parked, auth_error, reasons_json
                    FROM order_runs_old
                    """
                )
                conn.execute("DROP TABLE order_runs_old")
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

    def title_seen_within(self, title_hash: str, days: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT seen_at FROM title_hashes WHERE title_hash = ?",
                (title_hash,),
            ).fetchone()
        if row is None:
            return False
        seen_at = datetime.fromisoformat(str(row["seen_at"]))
        if seen_at.tzinfo is None:
            seen_at = seen_at.replace(tzinfo=UTC)
        return datetime.now(tz=UTC) - seen_at < timedelta(days=days)

    def remember_title(self, title_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO title_hashes (title_hash, seen_at)
                VALUES (?, ?)
                ON CONFLICT(title_hash) DO UPDATE SET seen_at = excluded.seen_at
                """,
                (title_hash, datetime.now(tz=UTC).isoformat()),
            )
            conn.commit()

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

    def get_notice(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT notice_value FROM kwork_notices WHERE notice_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return str(row["notice_value"])

    def set_notice(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kwork_notices (notice_key, notice_value)
                VALUES (?, ?)
                ON CONFLICT(notice_key) DO UPDATE SET notice_value = excluded.notice_value
                """,
                (key, value),
            )
            conn.commit()

    def clear_notice(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM kwork_notices WHERE notice_key = ?", (key,))
            conn.commit()

    def save_run(
        self,
        *,
        started_at: str,
        source: str,
        found: int,
        passed: int,
        new_sent: int,
        parked: int,
        auth_error: str,
        reasons: dict[str, int],
    ) -> None:
        payload = json.dumps(reasons, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO order_runs (
                    source, started_at, found, passed, new_sent, parked, auth_error, reasons_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    started_at = excluded.started_at,
                    found = excluded.found,
                    passed = excluded.passed,
                    new_sent = excluded.new_sent,
                    parked = excluded.parked,
                    auth_error = excluded.auth_error,
                    reasons_json = excluded.reasons_json
                """,
                (source, started_at, found, passed, new_sent, parked, auth_error, payload),
            )
            conn.commit()

    def runs(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM order_runs ORDER BY source").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["reasons"] = json.loads(item.pop("reasons_json"))
            result.append(item)
        return result

    def remember_rejection(self, *, order_id: str, title: str, reason: str, now: datetime) -> None:
        current = now.astimezone(UTC)
        stamp = current.isoformat(timespec="seconds")
        cutoff = (current - timedelta(days=30)).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("DELETE FROM rejected_orders WHERE created_at < ?", (cutoff,))
            conn.execute(
                """
                INSERT INTO rejected_orders (order_id, reason, title, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(order_id, reason) DO UPDATE SET
                    title = excluded.title
                """,
                (order_id, reason, title, stamp),
            )
            conn.commit()

    def rejection_report(self, now: datetime) -> dict:
        current = now.astimezone(UTC)
        cutoff = (current - timedelta(days=30)).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("DELETE FROM rejected_orders WHERE created_at < ?", (cutoff,))
            conn.commit()
            counts = conn.execute(
                """
                SELECT reason, COUNT(*) AS total
                FROM rejected_orders
                WHERE created_at >= ?
                GROUP BY reason
                """,
                (cutoff,),
            ).fetchall()
            samples = conn.execute(
                """
                SELECT title FROM rejected_orders
                WHERE reason = 'no_profile_match' AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 15
                """,
                (cutoff,),
            ).fetchall()
        return {
            "counts": {str(row["reason"]): int(row["total"]) for row in counts},
            "no_profile_titles": [str(row["title"]) for row in samples],
        }

    def save_snapshot(
        self,
        *,
        callback_key: str,
        external_id: str,
        source: str,
        title: str,
        description: str,
        link: str,
        price: str,
        user_id: int | None,
        username: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO order_snapshots (
                    callback_key, external_id, source, title, description, link, price, user_id, username
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(callback_key) DO UPDATE SET
                    external_id = excluded.external_id,
                    source = excluded.source,
                    title = excluded.title,
                    description = excluded.description,
                    link = excluded.link,
                    price = excluded.price,
                    user_id = excluded.user_id,
                    username = excluded.username
                """,
                (callback_key, external_id, source, title, description, link, price, user_id, username),
            )
            conn.commit()

    def snapshot(self, callback_key: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM order_snapshots WHERE callback_key = ?",
                (callback_key,),
            ).fetchone()
        return dict(row) if row is not None else None

    def save_feedback(
        self,
        *,
        order_id: str,
        verdict: str,
        reason: str | None,
        created_at: str,
        user_id: int | None,
        username: str,
        price_rub: int | None,
        title: str,
        description: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO order_feedback (
                    order_id, verdict, reason, created_at, user_id, username, price_rub, title, description
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    verdict = excluded.verdict,
                    reason = excluded.reason,
                    created_at = excluded.created_at,
                    user_id = excluded.user_id,
                    username = excluded.username,
                    price_rub = excluded.price_rub,
                    title = excluded.title,
                    description = excluded.description
                """,
                (order_id, verdict, reason, created_at, user_id, username, price_rub, title, description),
            )
            conn.commit()

    def set_feedback_reason(self, order_id: str, reason: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE order_feedback
                SET reason = ?
                WHERE order_id = ? AND verdict = 'junk'
                """,
                (reason, order_id),
            )
            conn.commit()
            return cursor.rowcount == 1

    def feedback_since(self, since_iso: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM order_feedback WHERE created_at >= ? ORDER BY created_at",
                (since_iso,),
            ).fetchall()
        return [dict(row) for row in rows]

    def penalized_user_ids(self, since_iso: str, minimum: int) -> set[int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id
                FROM order_feedback
                WHERE verdict = 'junk' AND user_id IS NOT NULL AND created_at >= ?
                GROUP BY user_id
                HAVING COUNT(*) >= ?
                """,
                (since_iso, minimum),
            ).fetchall()
        return {int(row["user_id"]) for row in rows}

    def blacklist_add(self, pattern: str, *, source: str, added_at: str) -> str:
        cleaned = pattern.strip()
        if not cleaned:
            return "empty"
        with self._connect() as conn:
            existing = conn.execute("SELECT pattern FROM order_blacklist").fetchall()
            if any(str(row["pattern"]).casefold() == cleaned.casefold() for row in existing):
                return "exists"
            conn.execute(
                "INSERT INTO order_blacklist (pattern, added_at, source) VALUES (?, ?, ?)",
                (cleaned, added_at, source),
            )
            conn.commit()
        return "added"

    def blacklist_remove(self, pattern: str) -> bool:
        cleaned = pattern.strip()
        with self._connect() as conn:
            rows = conn.execute("SELECT id, pattern FROM order_blacklist").fetchall()
            matched = [int(row["id"]) for row in rows if str(row["pattern"]).casefold() == cleaned.casefold()]
            if not matched:
                return False
            conn.execute(
                f"DELETE FROM order_blacklist WHERE id IN ({','.join('?' for _ in matched)})",
                matched,
            )
            conn.commit()
        return True

    def blacklist_patterns(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT pattern, source FROM order_blacklist ORDER BY pattern COLLATE NOCASE"
            ).fetchall()
        return [f"{row['pattern']} ({'вручную' if row['source'] == 'manual' else 'из фидбэка'})" for row in rows]

    def blacklist_needles(self) -> tuple[str, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT pattern FROM order_blacklist ORDER BY id").fetchall()
        return tuple(str(row["pattern"]) for row in rows)

    def park_order(
        self,
        *,
        order_id: str,
        title: str,
        price: str,
        score: int,
        now: datetime,
        days: int,
    ) -> None:
        current = now.astimezone(UTC).isoformat(timespec="seconds")
        expires = (now.astimezone(UTC) + timedelta(days=days)).isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expires_at FROM order_parked WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is not None and str(row["expires_at"]) > current:
                conn.execute(
                    "UPDATE order_parked SET title = ?, price = ?, score = ? WHERE order_id = ?",
                    (title, price, score, order_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO order_parked (order_id, title, price, score, parked_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(order_id) DO UPDATE SET
                        title = excluded.title,
                        price = excluded.price,
                        score = excluded.score,
                        parked_at = excluded.parked_at,
                        expires_at = excluded.expires_at
                    """,
                    (order_id, title, price, score, current, expires),
                )
            conn.commit()

    def parked_list(self, now: datetime) -> list[dict]:
        current = now.astimezone(UTC).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute("DELETE FROM order_parked WHERE expires_at <= ?", (current,))
            conn.commit()
            rows = conn.execute(
                "SELECT * FROM order_parked ORDER BY score DESC, parked_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_parked(self) -> int:
        with self._connect() as conn:
            count = conn.execute("DELETE FROM order_parked").rowcount
            conn.commit()
        return count

    def budget_override(self) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM order_overrides WHERE key = 'BUDGET_DROP_RUB'"
            ).fetchone()
        if row is None:
            return None
        return int(row["value"])

    def set_budget_override(self, value: int, *, suggestion_id: int, applied_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO order_overrides (key, value, suggestion_id, applied_at)
                VALUES ('BUDGET_DROP_RUB', ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    suggestion_id = excluded.suggestion_id,
                    applied_at = excluded.applied_at
                """,
                (str(value), suggestion_id, applied_at),
            )
            conn.commit()

    def dynamic_red_words(self) -> tuple[str, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT word FROM order_dynamic_red ORDER BY word").fetchall()
        return tuple(str(row["word"]) for row in rows)

    def add_dynamic_red(self, word: str, *, suggestion_id: int, added_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO order_dynamic_red (word, suggestion_id, added_at)
                VALUES (?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    suggestion_id = excluded.suggestion_id,
                    added_at = excluded.added_at
                """,
                (word, suggestion_id, added_at),
            )
            conn.commit()

    def insert_suggestion(self, *, kind: str, payload: str, created_at: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO order_suggestions (kind, payload, status, created_at)
                VALUES (?, ?, 'pending', ?)
                """,
                (kind, payload, created_at),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def find_suggestion(self, kind: str, payload: str, status: str, since_iso: str | None = None) -> dict | None:
        query = "SELECT * FROM order_suggestions WHERE kind = ? AND payload = ? AND status = ?"
        params: list[object] = [kind, payload, status]
        if since_iso is not None:
            query += " AND COALESCE(decided_at, created_at) >= ?"
            params.append(since_iso)
        query += " ORDER BY id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row is not None else None

    def pending_suggestions(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM order_suggestions WHERE status = 'pending' ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def suggestion(self, suggestion_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM order_suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def delete_pending(self, suggestion_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM order_suggestions WHERE id = ? AND status = 'pending'",
                (suggestion_id,),
            )
            conn.commit()

    def set_suggestion_status(self, suggestion_id: int, status: str, decided_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE order_suggestions SET status = ?, decided_at = ? WHERE id = ?",
                (status, decided_at, suggestion_id),
            )
            conn.commit()
