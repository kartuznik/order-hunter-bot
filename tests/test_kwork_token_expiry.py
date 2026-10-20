from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.database import SeenStorage
from bot.kwork_token import (
    NOTICE_EXPIRY,
    apply_token_to_env,
    expiry_due,
    maybe_warn_token_expiry,
    parse_updated_at,
    render_token_status,
)
from scripts.manual_token_update import main as update_main


class _Notifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_owner_alert(self, text: str) -> None:
        self.sent.append(text)


def test_warn_days_boundary() -> None:
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    fresh = now - timedelta(days=6, hours=23)
    due = now - timedelta(days=7)
    assert expiry_due(fresh, now, 7) is False
    assert expiry_due(due, now, 7) is True
    assert expiry_due(None, now, 7) is True
    assert parse_updated_at("31536000") is None


def test_expiry_notice_is_sent_once(tmp_path: Path) -> None:
    storage = SeenStorage(tmp_path / "probe.db")
    notifier = _Notifier()
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    old = (now - timedelta(days=8)).isoformat()

    async def _run() -> tuple[bool, bool]:
        first = await maybe_warn_token_expiry(
            storage,
            notifier,
            token="abcdefgh",
            updated_raw=old,
            warn_days=7,
            now=now,
        )
        second = await maybe_warn_token_expiry(
            storage,
            notifier,
            token="abcdefgh",
            updated_raw=old,
            warn_days=7,
            now=now,
        )
        return first, second

    first, second = asyncio.run(_run())
    assert first is True
    assert second is False
    assert len(notifier.sent) == 1
    assert "abcdefgh" not in notifier.sent[0]
    assert storage.get_notice(NOTICE_EXPIRY) == "sent"


def test_fresh_token_does_not_notify_and_clears_notice(tmp_path: Path) -> None:
    storage = SeenStorage(tmp_path / "probe.db")
    storage.set_notice(NOTICE_EXPIRY, "sent")
    notifier = _Notifier()
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    fresh = (now - timedelta(days=1)).isoformat()

    sent = asyncio.run(
        maybe_warn_token_expiry(
            storage,
            notifier,
            token="abcdefgh",
            updated_raw=fresh,
            warn_days=7,
            now=now,
        )
    )
    assert sent is False
    assert notifier.sent == []
    assert storage.get_notice(NOTICE_EXPIRY) is None


def test_status_hides_token_and_reports_auth() -> None:
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    secret = "super-secret-token"
    text = render_token_status(
        token=secret,
        updated_raw="2026-10-01T12:00:00+03:00",
        now=now,
        warn_days=7,
        auth_failed=True,
    )
    assert secret not in text
    assert "длина: 18" in text
    assert "отказ /projects: да" in text
    assert "2026-10-01T12:00:00+03:00" in text


def test_manual_update_rewrites_env_without_restart(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=keep-me\nKWORK_TOKEN=old-token-value\nKWORK_TOKEN_EXPIRES=31536000\n",
        encoding="utf-8",
    )
    db_file = tmp_path / "probe.db"
    storage = SeenStorage(db_file)
    storage.set_notice("projects_auth", "sent")
    code = update_main(
        [
            "new-token-value",
            "--env",
            str(env_file),
            "--db",
            str(db_file),
            "--no-restart",
        ]
    )
    assert code == 0
    rewritten = env_file.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=keep-me" in rewritten
    assert "KWORK_TOKEN=new-token-value" in rewritten
    assert "KWORK_TOKEN=old-token-value" not in rewritten
    assert "KWORK_TOKEN_EXPIRES=31536000" in rewritten
    assert "KWORK_TOKEN_UPDATED_AT=2026-" in rewritten
    assert storage.get_notice("projects_auth") is None
    direct = apply_token_to_env("KWORK_TOKEN=old-token-value\n", "replacement-token", "2026-10-20T09:00:00+03:00")
    assert direct == "KWORK_TOKEN=replacement-token\nKWORK_TOKEN_UPDATED_AT=2026-10-20T09:00:00+03:00\n"
