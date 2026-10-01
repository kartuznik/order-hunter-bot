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
    REASON_LOW_SCORE,
    REASON_MODULES,
    REASON_RED,
    REASON_TITLE,
    calculate_green_score,
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


def test_green_scores() -> None:
    assert calculate_green_score("телеграм бот", "") == 4
    assert calculate_green_score("парсер python", "") == 5
    assert calculate_green_score("django сайт", "") == 3
    assert calculate_green_score("просто телеграм", "") == 2
    assert calculate_green_score("api интеграция", "") == 2
    assert calculate_green_score("python api", "") == 4
    assert calculate_green_score("telegram bot", "") == 4
    assert calculate_green_score("ai llm python", "") == 9
    assert calculate_green_score("openai интеграция", "") == 3
    assert calculate_green_score("scraping парсер", "") == 4
    assert calculate_green_score("github actions deploy", "") == 2


def test_cyrillic_inflections_keep_dictionary_weight() -> None:
    assert calculate_green_score("Юкассы", "") == calculate_green_score("юкасса", "") == 1
    assert calculate_green_score("юкассы", "") == 1
    assert calculate_green_score("Юкассе", "") == 1
    assert calculate_green_score("интеграции", "") == calculate_green_score("интеграция", "") == 1
    assert calculate_green_score("интеграцию", "") == 1
    assert calculate_green_score("парсеров", "") == calculate_green_score("парсер", "") == 2
    assert calculate_green_score("парсинга", "") == calculate_green_score("парсинг", "") == 2
    assert calculate_green_score("бота", "") == calculate_green_score("бот", "") == 2
    assert calculate_green_score("сервера", "") == calculate_green_score("сервер", "") == 1


def test_stemmer_does_not_match_latin_substrings() -> None:
    assert calculate_green_score("email", "") == 0
    assert calculate_green_score("robot", "") == 0
    assert calculate_green_score("makeup", "") == 0
    assert calculate_green_score("fastapi", "") == 3
    assert calculate_green_score("chatgpt", "") == 2
    expect(card("Рассылка email"), REASON_LOW_SCORE)
    expect(card("Makeup для визитки"), REASON_LOW_SCORE)


def test_owner_inflected_title_reaches_threshold() -> None:
    title = "Настройка API интеграции и экваринга Юкассы"
    assert calculate_green_score(title, "") == 3
    expect(card(title), REASON_ACCEPT)


def test_low_score_is_rejected() -> None:
    expect(card("просто телеграм"), REASON_LOW_SCORE)
    expect(card("api интеграция"), REASON_LOW_SCORE)
    expect(card("github actions deploy"), REASON_LOW_SCORE)
    expect(card("Нарисовать баннер", "для кафе"), REASON_LOW_SCORE)
    expect(card("Починить email", "нужен парсер"), REASON_LOW_SCORE)
    expect(card("Только claude", "без стека"), REASON_LOW_SCORE)


def test_red_still_wins() -> None:
    expect(card("Сайт на react", "и python"), REASON_RED)
    expect(card("Бот на n8n", "и python api"), REASON_RED)
    expect(card("Нейросеть для текстов", "python"), REASON_RED)
    expect(card("Python, москва", "только этот город"), REASON_RED)
    expect(card("Нужен middle+ python", "в команду"), REASON_RED)


def test_score_then_budget_deadline_modules_and_gray() -> None:
    expect(card("Makeup лендинг", "python скрипт"), REASON_ACCEPT)
    expect(card("Python бот", price="1500"), REASON_BUDGET)
    expect(card("Python бот", price="2500"), REASON_GRAY, gray=True)
    expect(card("Python бот", "нужно за 1 день"), REASON_DEADLINE)
    expect(card("Python бот", "успеть за 2 дня"), REASON_GRAY, gray=True)
    expect(card("Python сервис", "6 модулей в личном кабинете", price="8000"), REASON_MODULES)
    expect(card("Python сервис", "6 модулей", price="15000"), REASON_ACCEPT)
    expect(card("Python сервис", "4 модуля", price="-"), REASON_GRAY, gray=True)
    expect(card("Нейросеть", "telegram bot на python"), REASON_ACCEPT)
    expect(card("Python", "москва, формат remote"), REASON_ACCEPT)
    expect(card("Claude помощник", "на python"), REASON_GRAY, gray=True)
    expect(card("Python интеграция", "обычная задача"), REASON_TITLE, repeat=True)
    expect(card("CI/CD для сервиса", "github actions и python"), REASON_ACCEPT)


def test_user_id_from_payload() -> None:
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


def test_telegram_family_is_counted_once() -> None:
    title = "Создать тг канал мах и телега новости"
    assert calculate_green_score(title, "") <= 2
    expect(card(title), REASON_LOW_SCORE)


def test_video_mobile_and_mini_app_are_red() -> None:
    mini = card("Доработка Mini Apps")
    mobile = card("Разработка мобильного приложения")
    montage = card("Монтаж YouTube роликов + AI сцены")
    expect(mini, REASON_RED)
    expect(mobile, REASON_RED)
    expect(montage, REASON_RED)
    assert decide_card(montage, title_repeat=False).matched_red == "монтаж"
    expect(card("Нужен монтаж роликов"), REASON_RED)
    expect(card("Сделать мобильного приложения на заказ"), REASON_RED)


def test_relevant_bot_and_ai_check_still_pass() -> None:
    bot_title = "Разработка телеграмм бота"
    assert calculate_green_score(bot_title, "") >= 3
    expect(card(bot_title), REASON_ACCEPT)
    ai_title = "AI-проверка домашних заданий"
    assert calculate_green_score(ai_title, "") >= 3
    expect(card(ai_title), REASON_ACCEPT)


def test_cheap_price_without_green_core_is_not_gray() -> None:
    expect(card("телеграм бот", price="2500"), REASON_ACCEPT)
    expect(card("Python бот", price="2500"), REASON_GRAY, gray=True)


def test_title_repeat_window() -> None:
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
