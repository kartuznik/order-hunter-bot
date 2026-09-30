from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.database import SeenStorage
from bot.kwork_api import cards_from_payload
from bot.kwork_filter import (
    REASON_ACCEPT,
    REASON_BUDGET,
    REASON_DEADLINE,
    REASON_GRAY,
    REASON_MODULES,
    REASON_NO_GREEN,
    REASON_RED,
    REASON_TITLE,
    decide_card,
    title_hash,
)
from bot.models import OrderCard


def card(title: str, description: str = "", price: str = "5000") -> OrderCard:
    return OrderCard(
        source="kwork_api",
        external_id="1",
        title=title,
        link="https://kwork.ru/projects/1",
        description=description,
        price=price,
    )


def expect(order: OrderCard, reason: str, *, repeat: bool = False, gray: bool = False) -> None:
    decision = decide_card(order, title_repeat=repeat)
    assert decision.reason == reason, (decision.reason, reason, order.title)
    assert decision.accept is (reason in {REASON_ACCEPT, REASON_GRAY})
    assert decision.gray is gray


def main() -> None:
    expect(card("Сайт на react", "и python"), REASON_RED)
    expect(card("Починить email", "нужен парсер"), REASON_ACCEPT)
    expect(card("Makeup лендинг", "python скрипт"), REASON_ACCEPT)
    expect(card("Нарисовать баннер", "для кафе"), REASON_NO_GREEN)
    expect(card("Python бот", price="1500"), REASON_BUDGET)
    expect(card("Python бот", price="2500"), REASON_GRAY, gray=True)
    expect(card("Python бот", "нужно за 1 день"), REASON_DEADLINE)
    expect(card("Python бот", "успеть за 2 дня"), REASON_GRAY, gray=True)
    expect(card("Python сервис", "6 модулей в личном кабинете", price="8000"), REASON_MODULES)
    expect(card("Python сервис", "6 модулей", price="15000"), REASON_ACCEPT)
    expect(card("Python сервис", "4 модуля", price="-"), REASON_GRAY, gray=True)
    expect(card("Бот на n8n", "и python api"), REASON_RED)
    expect(card("Нейросеть для текстов", "python"), REASON_RED)
    expect(card("Нейросеть", "telegram bot на python"), REASON_ACCEPT)
    expect(card("Python, москва", "только этот город"), REASON_RED)
    expect(card("Python", "москва, формат remote"), REASON_ACCEPT)
    expect(card("Claude помощник", "на python"), REASON_GRAY, gray=True)
    expect(card("Только claude", "без стека"), REASON_NO_GREEN)
    expect(card("Python интеграция", "обычная задача"), REASON_TITLE, repeat=True)
    expect(card("CI/CD для сервиса", "github actions и python"), REASON_ACCEPT)
    expect(card("Нужен middle+ python", "в команду"), REASON_RED)

    parsed = cards_from_payload(
        {
            "success": True,
            "response": [
                {"id": 3, "title": "A", "description": "", "price": 100, "user_id": 42},
                {"id": 4, "title": "B", "description": "", "price": 100, "user_id": True},
            ],
        }
    )
    assert parsed[0].user_id == 42
    assert parsed[1].user_id is None

    with tempfile.TemporaryDirectory() as tmp:
        storage = SeenStorage(Path(tmp) / "orders.db")
        digest = title_hash("  Python   Бот ")
        assert title_hash("python бот") == digest
        assert storage.title_seen_within(digest, 7) is False
        storage.remember_title(digest)
        assert storage.title_seen_within(digest, 7) is True
        old = (datetime.now(tz=UTC) - timedelta(days=8)).isoformat()
        with sqlite3.connect(Path(tmp) / "orders.db") as conn:
            conn.execute("UPDATE title_hashes SET seen_at = ?", (old,))
        assert storage.title_seen_within(digest, 7) is False

    print("KWORK_FILTER_CASES_OK")


if __name__ == "__main__":
    main()
