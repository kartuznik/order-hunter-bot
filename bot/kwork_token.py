"""Manual Kwork token age. This module never calls signIn."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Protocol

from bot.database import SeenStorage
from bot.kwork_api import NOTICE_AUTH, NOTICE_MISSING

logger = logging.getLogger("order_hunter.kwork_token")


class OwnerAlerter(Protocol):
    async def send_owner_alert(self, text: str) -> None: ...

NOTICE_EXPIRY = "token_expiry"
WARN_INTERVAL = timedelta(days=1)
NOTICES_CLEARED_ON_UPDATE = (NOTICE_AUTH, NOTICE_MISSING, NOTICE_EXPIRY)


def validate_token(token: str) -> str:
    value = token.strip()
    if (
        not value
        or any(character.isspace() for character in value)
        or any(character in value for character in "#'\"")
        or not 8 <= len(value) <= 256
    ):
        raise ValueError("token rejected")
    return value


def parse_updated_at(raw: str) -> datetime | None:
    text = raw.strip()
    if not text or text.isdigit():
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def expiry_due(updated_at: datetime | None, now: datetime, warn_days: int) -> bool:
    if updated_at is None:
        return True
    return now - updated_at >= timedelta(days=warn_days)


def expiry_message(updated_at: datetime | None, warn_days: int) -> str:
    if updated_at is None:
        head = "Дата записи Kwork-токена неизвестна."
    else:
        head = f"Kwork-токен записан больше {warn_days} дней назад."
    return (
        f"{head} Обнови его с домашней машины командой curl signIn "
        "и на сервере выполни "
        "venv/bin/python scripts/manual_token_update.py '<токен>'. "
        "С VPS signIn не вызывать: датацентровый IP получает капчу. "
        "Инструкция: docs/kwork_token_refresh.md"
    )


def render_token_status(
    *,
    token: str,
    updated_raw: str,
    now: datetime,
    warn_days: int,
    auth_failed: bool,
) -> str:
    value = token.strip()
    updated_at = parse_updated_at(updated_raw)
    if updated_at is None:
        recorded = "не записана" if not updated_raw.strip() else "не дата"
        age = "неизвестен"
    else:
        recorded = updated_at.isoformat(timespec="seconds")
        age = str(max(0, (now - updated_at).days))
    return (
        "Kwork token\n"
        f"задан: {'да' if value else 'нет'}\n"
        f"длина: {len(value)}\n"
        f"записан: {recorded}\n"
        f"дней с записи: {age}\n"
        f"порог предупреждения, дней: {warn_days}\n"
        f"отказ /projects: {'да' if auth_failed else 'нет'}"
    )


def apply_token_to_env(text: str, token: str, updated_at: str) -> str:
    updates = {
        "KWORK_TOKEN": validate_token(token),
        "KWORK_TOKEN_UPDATED_AT": updated_at,
    }
    newline = "\n"
    lines = text.splitlines(keepends=True)
    seen: set[str] = set()
    rewritten: list[str] = []
    for line in lines:
        ending = newline if line.endswith("\n") else ""
        body = line[:-1] if ending else line
        if not body or body.lstrip().startswith("#") or "=" not in body:
            rewritten.append(line)
            continue
        key, _value = body.split("=", 1)
        if key in updates:
            rewritten.append(f"{key}={updates[key]}{ending or newline}")
            seen.add(key)
            continue
        rewritten.append(line)
    missing = [key for key in updates if key not in seen]
    if missing:
        if rewritten and not rewritten[-1].endswith(newline):
            rewritten[-1] += newline
        rewritten.extend(f"{key}={updates[key]}{newline}" for key in missing)
    return "".join(rewritten)


def clear_token_notices(storage: SeenStorage) -> None:
    for key in NOTICES_CLEARED_ON_UPDATE:
        storage.clear_notice(key)


async def maybe_warn_token_expiry(
    storage: SeenStorage,
    notifier: OwnerAlerter,
    *,
    token: str,
    updated_raw: str,
    warn_days: int,
    now: datetime,
) -> bool:
    if not token.strip():
        return False
    updated_at = parse_updated_at(updated_raw)
    if not expiry_due(updated_at, now, warn_days):
        storage.clear_notice(NOTICE_EXPIRY)
        return False
    if storage.get_notice(NOTICE_EXPIRY) == "sent":
        return False
    try:
        await notifier.send_owner_alert(expiry_message(updated_at, warn_days))
    except Exception as error:
        logger.error("Kwork token expiry alert failed: %s", type(error).__name__)
        return False
    storage.set_notice(NOTICE_EXPIRY, "sent")
    return True
