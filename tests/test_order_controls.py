from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.database import SeenStorage
from bot.kwork_api import KworkTickResult, cards_from_payload, run_kwork_loop
from bot.kwork_api import POLL_MAX_SECONDS, POLL_MIN_SECONDS, next_wait_seconds
from bot.kwork_filter import (
    REASON_ACCEPT,
    REASON_BLACKLIST,
    REASON_GRAY,
    REASON_LOW,
    REASON_NO_PROFILE,
    REASON_RED,
    decide_card,
)
from bot.config import GREEN_WEIGHTS
from bot.models import OrderCard
from bot.owner_commands import OwnerCommands, callback_key, order_keyboard, reason_keyboard
from bot.run_control import RunControl
from bot.suggestions import refresh_suggestions

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def _storage(tmp_path: Path) -> SeenStorage:
    return SeenStorage(tmp_path / "orders.db")


def _card(title: str, **kwargs) -> OrderCard:
    return OrderCard(
        source="kwork_api",
        external_id=kwargs.pop("external_id", "1"),
        title=title,
        link=kwargs.pop("link", "https://kwork.ru/projects/1"),
        description=kwargs.pop("description", ""),
        price=kwargs.pop("price", "8000"),
        user_id=kwargs.pop("user_id", None),
        username=kwargs.pop("username", ""),
    )


def _remember(storage: SeenStorage, card: OrderCard) -> str:
    key = callback_key(card.external_id)
    storage.save_snapshot(
        callback_key=key,
        external_id=card.external_id,
        source=card.source,
        title=card.title,
        description=card.description,
        link=card.link,
        price=card.price,
        user_id=card.user_id,
        username=card.username,
    )
    return key


def _commands(storage: SeenStorage, run=None) -> OwnerCommands:
    async def _idle():
        return KworkTickResult()

    return OwnerCommands(storage, RunControl(), run or _idle)


def test_username_comes_from_project_payload() -> None:
    cards = cards_from_payload(
        {"success": True, "response": [{"id": 15, "title": "Бот", "description": "", "price": 2500, "username": " Buyer "}]}
    )
    assert cards[0].username == "Buyer"


def test_profile_words_and_zero_score_journal() -> None:
    assert GREEN_WEIGHTS["агент"] == 3
    assert GREEN_WEIGHTS["ии"] == 2
    assert GREEN_WEIGHTS["gpt"] == 3
    assert GREEN_WEIGHTS["chatgpt"] == 3
    assert GREEN_WEIGHTS["нейросеть"] == 2
    assert GREEN_WEIGHTS["парсер"] == 3
    assert GREEN_WEIGHTS["парсинг"] == 3
    assert GREEN_WEIGHTS["автоматизация"] == 2
    for removed in ("pytest", "unittest", "тестирование", "ci/cd", "github actions", "systemd", "nginx", "оплата", "сервер", "vps"):
        assert removed not in GREEN_WEIGHTS
    zero = decide_card(_card("Дополненная реальность"), title_repeat=False)
    assert zero.reason == REASON_NO_PROFILE
    assert zero.accept is False
    low = decide_card(_card("просто телеграм"), title_repeat=False)
    assert low.reason == REASON_LOW
    assert low.accept is True
    assert low.score == 2
    paid = decide_card(_card("Python бот", price="8000", description="нужно за 1 день"), title_repeat=False)
    assert paid.reason == REASON_ACCEPT
    neural = decide_card(_card("Нейросеть для текстов"), title_repeat=False)
    assert neural.reason == REASON_LOW
    assert neural.matched_red == ""


def test_pause_skips_the_timer_and_run_now_still_counts(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    control = RunControl()
    control.pause()

    async def run():
        return KworkTickResult(
            found=4,
            metrics={
                "passed_filter": 1,
                "sent_notifications": 1,
                "parked": 1,
                "reasons": {"blocked_by_title_score": 2, "blocked_by_budget": 1, "parked": 1, "accept": 1},
            },
        )

    commands = OwnerCommands(storage, control, run)

    async def _check() -> tuple[str, str, list[int]]:
        text = await commands.run_now(now=NOW)
        calls: list[int] = []
        stop = asyncio.Event()

        async def run_once() -> None:
            calls.append(1)
            stop.set()

        def wait() -> tuple[int, int]:
            stop.set()
            return 0, 0

        await run_kwork_loop(
            stop_event=stop,
            run_once=run_once,
            should_pause=lambda: control.paused,
            wait_seconds=wait,
        )
        return text, commands.run_stats(), calls

    text, stats, calls = asyncio.run(_check())
    assert calls == []
    assert "найдено: 4" in text
    assert "дошло до владельца: 1" in text
    assert "Kwork" in stats
    assert "Почта" not in stats
    assert control.paused is True
    assert "возобновлены" in commands.resume()


def test_auth_failure_does_not_invent_counts(tmp_path: Path) -> None:
    storage = _storage(tmp_path)

    async def run():
        return KworkTickResult(auth_error="auth")

    commands = _commands(storage, run)
    text = asyncio.run(commands.run_now(now=NOW))
    assert text == "Прогон Kwork не состоялся: отказ авторизации."
    assert "найдено:" not in text
    assert "отказ авторизации" in commands.run_stats()


def test_feedback_reason_stats_and_callback_limit(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    commands = _commands(storage)
    card = _card("Python бот", external_id="15", username="bad_buyer", user_id=4, price="7000")
    key = _remember(storage, card)
    answer, markup = commands.handle_callback(f"fb:j:{key}", now=NOW)
    assert answer == "Отмечено: мусор."
    assert markup is not None
    answer, restored = commands.handle_callback(f"fb:n:b:{key}", now=NOW)
    assert answer == "Причина: низкий бюджет."
    assert restored is not None
    stats = commands.feedback_stats(now=NOW)
    assert "релевантных: 0%" in stats
    assert "низкий бюджет: 1" in stats
    assert "bad_buyer: 1" in stats
    for keyboard in (order_keyboard(card), reason_keyboard(key, card.link)):
        for row in keyboard.inline_keyboard:
            for button in row:
                if button.callback_data:
                    assert len(button.callback_data.encode("utf-8")) <= 64


def test_blacklist_commands_match_username(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    commands = _commands(storage)
    assert commands.blacklist("/blacklist add Bad", now=NOW) == "Паттерн добавлен."
    assert commands.blacklist("/blacklist add bad", now=NOW) == "Такой паттерн уже есть."
    listed = commands.blacklist("/blacklist list")
    assert "Bad (вручную)" in listed
    decision = decide_card(
        _card("Python бот", username="bad_buyer"),
        title_repeat=False,
        blacklist_patterns=storage.blacklist_needles(),
    )
    assert decision.reason == REASON_BLACKLIST
    assert commands.blacklist("/blacklist remove bad") == "Паттерн удалён."
    assert commands.blacklist("/blacklist list") == "Блэклист пуст."


def test_parked_list_and_clear(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    commands = _commands(storage)
    storage.park_order(order_id="15", title="Python api", price="5000", score=2, now=NOW, days=7)
    text = commands.parked(now=NOW)
    assert "#15 Python api — 5000 ₽, балл 2" in text
    assert (NOW + timedelta(days=7)).isoformat(timespec="seconds") in text
    assert commands.parked_clear() == "Парковка очищена: 1."
    assert commands.parked(now=NOW) == "Парковка пуста."


def test_budget_suggestion_waits_for_accept(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    commands = _commands(storage)
    for index, price in enumerate(("6000", "7000", "9000"), start=1):
        card = _card("Python бот", external_id=str(index), price=price, user_id=index)
        key = _remember(storage, card)
        commands.handle_callback(f"fb:j:{key}", now=NOW)
        commands.handle_callback(f"fb:n:b:{key}", now=NOW)
    assert "поднять порог бюджета до 9000" in commands.suggestions()
    assert storage.budget_override() is None
    assert decide_card(_card("Python бот", price="8000"), title_repeat=False).reason == REASON_ACCEPT
    applied = commands.handle_callback("sg:a:1", now=NOW)[0]
    assert applied == "Применено: порог бюджета 9000 ₽."
    assert decide_card(
        _card("Python бот", price="1500"),
        title_repeat=False,
        budget_drop_rub=storage.budget_override(),
    ).reason == REASON_GRAY
    assert refresh_suggestions(storage, now=NOW) == []


def test_stack_suggestion_ignores_green_words_and_relevant_votes(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    commands = _commands(storage)
    texts = (
        "Python бот для битрикс",
        "Django сервис битрикс",
        "FastAPI и битрикс",
    )
    for index, title in enumerate(texts, start=1):
        card = _card(title, external_id=str(index), user_id=index)
        key = _remember(storage, card)
        commands.handle_callback(f"fb:j:{key}", now=NOW)
        commands.handle_callback(f"fb:n:t:{key}", now=NOW)
    assert "«битрикс»" in commands.suggestions()
    assert "python" not in commands.suggestions()
    liked = _card("Нужен битрикс и python бот", external_id="9")
    liked_key = _remember(storage, liked)
    commands.handle_callback(f"fb:r:{liked_key}", now=NOW)
    assert commands.suggestions() == "Предложений нет."


def test_declined_suggestion_stays_quiet_for_thirty_days(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    commands = _commands(storage)
    for index, price in enumerate(("6000", "7000", "9000"), start=1):
        card = _card("Python бот", external_id=str(index), price=price)
        key = _remember(storage, card)
        commands.handle_callback(f"fb:j:{key}", now=NOW)
        commands.handle_callback(f"fb:n:b:{key}", now=NOW)
    assert commands.handle_callback("sg:d:1", now=NOW)[0] == "Предложение отклонено."
    assert refresh_suggestions(storage, now=NOW + timedelta(days=1)) == []
    assert storage.budget_override() is None


def test_interval_offers_rejections_and_separate_runs(tmp_path: Path) -> None:
    import bot.kwork_api as kwork_api

    original = kwork_api.random.randint
    try:
        kwork_api.random.randint = lambda start, end: start
        assert next_wait_seconds()[0] == POLL_MIN_SECONDS == 300
        kwork_api.random.randint = lambda start, end: end
        assert next_wait_seconds()[0] == POLL_MAX_SECONDS == 900
    finally:
        kwork_api.random.randint = original
    cards = cards_from_payload(
        {
            "success": True,
            "response": [
                {
                    "id": 15,
                    "title": "Бот",
                    "description": "за 1 день",
                    "price": 2500,
                    "offers": 3,
                    "date_confirm": int(NOW.timestamp()) - 7200,
                    "username": "Buyer",
                }
            ],
        }
    )
    from bot.notifier import render_order

    text = render_order(cards[0], now=NOW)
    assert "Откликов: 3" in text
    assert "Возраст: 2 ч" in text
    assert "Срок: 1 дн." in text
    assert "2500" in text

    storage = _storage(tmp_path)
    commands = _commands(storage)
    storage.remember_rejection(order_id="1", title="Дополненная реальность", reason="no_profile_match", now=NOW)
    storage.remember_rejection(order_id="2", title="Отрисовка логотипа", reason="blocked_by_red_list", now=NOW)
    report = commands.rejected_stats(now=NOW)
    assert "нет слов профиля: 1" in report
    assert "красный список: 1" in report
    assert "Дополненная реальность" in report
    storage.save_run(
        started_at="2026-10-20T09:00:00+00:00",
        source="kwork",
        found=12,
        passed=1,
        new_sent=1,
        parked=0,
        auth_error="",
        reasons={"blocked_by_red_list": 4, "no_profile_match": 7},
    )
    storage.save_run(
        started_at="2026-10-20T09:01:00+00:00",
        source="mail",
        found=0,
        passed=0,
        new_sent=0,
        parked=0,
        auth_error="",
        reasons={},
    )
    stats = commands.run_stats()
    assert "Kwork" in stats
    assert "найдено: 12" in stats
    assert "отсеяно красным списком: 4" in stats
    assert "Почта" in stats
    assert "найдено: 0" in stats


def test_three_junk_votes_penalize_the_same_customer(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    commands = _commands(storage)
    for index in range(1, 4):
        card = _card("Python бот", external_id=str(index), user_id=9, username="same")
        key = _remember(storage, card)
        commands.handle_callback(f"fb:j:{key}", now=NOW)
    assert commands.penalty_for(9, now=NOW) == 0
    decision = decide_card(_card("Python бот api", user_id=9), title_repeat=False, score_penalty=3)
    assert decision.reason == REASON_ACCEPT
    assert decision.score == 6
