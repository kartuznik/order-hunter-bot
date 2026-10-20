"""Text and buttons for the owner commands. This module does not talk to Telegram."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import SeenStorage
from bot.kwork_filter import parse_budget_rub
from bot.models import OrderCard
from bot.run_control import RunControl
from bot.suggestions import apply_suggestion, decline_suggestion, refresh_suggestions, suggestion_lines

FEEDBACK_WINDOW = timedelta(days=30)
PARK_DAYS = 7
JUNK_VOTES = 3
REASON_LABELS = {
    "stack": "не мой стек",
    "budget": "низкий бюджет",
    "customer": "не тот заказчик",
    "spam": "спам",
    "duplicate": "дубль",
    "none": "без причины",
}
REASON_CODES = {
    "t": "stack",
    "b": "budget",
    "c": "customer",
    "s": "spam",
    "d": "duplicate",
    "n": "none",
}
COMMANDS = {
    "/stats",
    "/kwork_token_status",
    "/run_now",
    "/run_stats",
    "/pause",
    "/resume",
    "/feedback_stats",
    "/blacklist",
    "/parked",
    "/parked_clear",
    "/suggestions",
    "/rejected_stats",
}


def command_name(text: str) -> str | None:
    token = text.strip().split(maxsplit=1)[0].lower()
    name = token.split("@", 1)[0]
    if name in COMMANDS:
        return name
    return None


def callback_key(external_id: str) -> str:
    return hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:16]


def order_keyboard(card: OrderCard) -> InlineKeyboardMarkup:
    key = callback_key(card.external_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть заказ", url=card.link)],
            [
                InlineKeyboardButton(text="Релевантно", callback_data=f"fb:r:{key}"),
                InlineKeyboardButton(text="Мусор", callback_data=f"fb:j:{key}"),
            ],
        ]
    )


def reason_keyboard(card_key: str, link: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"fb:n:{code}:{card_key}")
        for code, label in (
            ("t", "не мой стек"),
            ("b", "низкий бюджет"),
            ("c", "не тот заказчик"),
            ("s", "спам"),
            ("d", "дубль"),
            ("n", "без причины"),
        )
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="Открыть заказ", url=link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _card_from_snapshot(snapshot: dict) -> OrderCard:
    return OrderCard(
        source=str(snapshot["source"]),
        external_id=str(snapshot["external_id"]),
        title=str(snapshot["title"]),
        link=str(snapshot["link"]),
        description=str(snapshot["description"]),
        price=str(snapshot["price"]),
        user_id=snapshot["user_id"],
        username=str(snapshot["username"] or ""),
    )


def suggestion_keyboard(suggestion_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Применить", callback_data=f"sg:a:{suggestion_id}"),
            InlineKeyboardButton(text="Отклонить", callback_data=f"sg:d:{suggestion_id}"),
        ]]
    )


def format_source_run(row: dict) -> str:
    label = "Kwork" if row["source"] == "kwork" else "Почта"
    if row["auth_error"]:
        reason = "отказ авторизации" if row["auth_error"] == "auth" else row["auth_error"]
        return f"{label} {row['started_at']}\nпрогон не состоялся: {reason}."
    reasons = row["reasons"]
    return (
        f"{label} {row['started_at']}\n"
        f"найдено: {row['found']}\n"
        f"дошло до владельца: {row['new_sent']}\n"
        f"отсеяно красным списком: {int(reasons.get('blocked_by_red_list', 0))}\n"
        f"отсеяно блэклистом: {int(reasons.get('blocked_by_blacklist', 0))}\n"
        f"без слов профиля: {int(reasons.get('no_profile_match', 0))}"
    )


def format_run_now(*, found: int, new_sent: int, auth_error: str, reasons: dict[str, int]) -> str:
    if auth_error:
        reason = "отказ авторизации" if auth_error == "auth" else auth_error
        return f"Прогон Kwork не состоялся: {reason}."
    text = format_source_run(
        {
            "source": "kwork",
            "started_at": "",
            "found": found,
            "new_sent": new_sent,
            "auth_error": "",
            "reasons": reasons,
        }
    )
    return text.replace("Kwork \n", "Прогон Kwork\n", 1)


def format_run_stats(rows: list[dict]) -> str:
    if not rows:
        return "Прогонов ещё не было."
    return "\n\n".join(format_source_run(row) for row in rows)


def format_rejected_stats(report: dict) -> str:
    counts = report["counts"]
    lines = [
        "Отсев за 30 дней",
        f"красный список: {counts.get('blocked_by_red_list', 0)}",
        f"блэклист: {counts.get('blocked_by_blacklist', 0)}",
        f"нет слов профиля: {counts.get('no_profile_match', 0)}",
        "Последние без слов профиля:",
    ]
    titles = report["no_profile_titles"]
    if titles:
        lines.extend(f"- {title}" for title in titles)
    else:
        lines.append("нет")
    return "\n".join(lines)


def format_feedback_stats(storage: SeenStorage, *, now: datetime) -> str:
    since = (now.astimezone(UTC) - FEEDBACK_WINDOW).isoformat(timespec="seconds")
    votes = storage.feedback_since(since)
    relevant = sum(1 for vote in votes if vote["verdict"] == "relevant")
    junk = [vote for vote in votes if vote["verdict"] == "junk"]
    total = relevant + len(junk)
    percent = 0 if total == 0 else round(100 * relevant / total)
    reasons: dict[str, int] = {}
    customers: dict[str, int] = {}
    for vote in junk:
        if vote["reason"]:
            label = REASON_LABELS.get(str(vote["reason"]), str(vote["reason"]))
            reasons[label] = reasons.get(label, 0) + 1
        name = str(vote["username"] or "").strip() or (
            f"user {vote['user_id']}" if vote["user_id"] is not None else ""
        )
        if name:
            customers[name] = customers.get(name, 0) + 1
    lines = [
        "Фидбэк за 30 дней",
        f"оценок: {total}",
        f"релевантных: {percent}%",
        f"мусор: {len(junk)}",
    ]
    lines.append("Причины мусора:")
    if reasons:
        lines.extend(
            f"{label}: {count}" for label, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        )
    else:
        lines.append("нет")
    lines.append("Заказчики по мусору:")
    if customers:
        lines.extend(
            f"{name}: {count}" for name, count in sorted(customers.items(), key=lambda item: (-item[1], item[0]))[:5]
        )
    else:
        lines.append("нет")
    return "\n".join(lines)


def format_parked(storage: SeenStorage, *, now: datetime) -> str:
    rows = storage.parked_list(now)
    if not rows:
        return "Парковка пуста."
    lines = ["Парковка"]
    for row in rows[:30]:
        lines.append(
            f"#{row['order_id']} {row['title']} — {row['price']} ₽, балл {row['score']}, до {row['expires_at']}"
        )
    if len(rows) > 30:
        lines.append(f"ещё {len(rows) - 30}")
    return "\n".join(lines)


def format_suggestions(storage: SeenStorage) -> str:
    lines = suggestion_lines(storage)
    if not lines:
        return "Предложений нет."
    return "\n".join(text for _suggestion_id, text in lines)


class OwnerCommands:
    def __init__(self, storage: SeenStorage, run_control: RunControl, run_kwork) -> None:
        self.storage = storage
        self.run_control = run_control
        self._run_kwork = run_kwork

    async def run_now(self, *, now: datetime | None = None) -> str:
        moment = now or datetime.now(tz=UTC)
        async with self.run_control.lock:
            outcome = await self._run_kwork()
            self._record("kwork", outcome, moment)
        metrics = outcome.metrics or {}
        reasons = {} if outcome.auth_error else metrics.get("reasons", {})
        return format_run_now(
            found=0 if outcome.auth_error else outcome.found,
            new_sent=0 if outcome.metrics is None else int(metrics.get("sent_notifications", 0)),
            auth_error=outcome.auth_error,
            reasons={str(key): int(value) for key, value in reasons.items()},
        )

    def record_kwork(self, outcome, *, now: datetime | None = None) -> None:
        self._record("kwork", outcome, now or datetime.now(tz=UTC))

    def record_mail(self, metrics: dict, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(tz=UTC)
        self.storage.save_run(
            started_at=moment.astimezone(UTC).isoformat(timespec="seconds"),
            source="mail",
            found=int(metrics["seen_total"]),
            passed=int(metrics["passed_filter"]),
            new_sent=int(metrics["sent_notifications"]),
            parked=int(metrics["parked"]),
            auth_error="",
            reasons={str(key): int(value) for key, value in metrics["reasons"].items()},
        )

    def _record(self, source: str, outcome, moment: datetime) -> None:
        metrics = outcome.metrics or {}
        reasons = metrics.get("reasons", {})
        self.storage.save_run(
            started_at=moment.astimezone(UTC).isoformat(timespec="seconds"),
            source=source,
            found=0 if outcome.auth_error else int(outcome.found),
            passed=0 if outcome.metrics is None else int(metrics.get("passed_filter", 0)),
            new_sent=0 if outcome.metrics is None else int(metrics.get("sent_notifications", 0)),
            parked=0 if outcome.metrics is None else int(metrics.get("parked", 0)),
            auth_error=outcome.auth_error,
            reasons={} if outcome.auth_error else {str(key): int(value) for key, value in reasons.items()},
        )

    def run_stats(self) -> str:
        return format_run_stats(self.storage.runs())

    def rejected_stats(self, *, now: datetime | None = None) -> str:
        return format_rejected_stats(self.storage.rejection_report(now or datetime.now(tz=UTC)))

    def pause(self) -> str:
        return self.run_control.pause()

    def resume(self) -> str:
        return self.run_control.resume()

    def feedback_stats(self, *, now: datetime | None = None) -> str:
        return format_feedback_stats(self.storage, now=now or datetime.now(tz=UTC))

    def blacklist(self, text: str, *, now: datetime | None = None) -> str:
        parts = text.strip().split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else ""
        pattern = parts[2].strip() if len(parts) > 2 else ""
        moment = (now or datetime.now(tz=UTC)).astimezone(UTC).isoformat(timespec="seconds")
        if action == "add":
            if not pattern:
                return "Укажи паттерн: /blacklist add текст"
            result = self.storage.blacklist_add(pattern, source="manual", added_at=moment)
            if result == "exists":
                return "Такой паттерн уже есть."
            return "Паттерн добавлен."
        if action == "remove":
            if not pattern:
                return "Укажи паттерн: /blacklist remove текст"
            if not self.storage.blacklist_remove(pattern):
                return "Паттерн не найден."
            return "Паттерн удалён."
        if action == "list":
            rows = self.storage.blacklist_patterns()
            if not rows:
                return "Блэклист пуст."
            return "Блэклист\n" + "\n".join(rows)
        return "Команды: /blacklist add, /blacklist remove, /blacklist list."

    def parked(self, *, now: datetime | None = None) -> str:
        return format_parked(self.storage, now=now or datetime.now(tz=UTC))

    def parked_clear(self) -> str:
        count = self.storage.clear_parked()
        return f"Парковка очищена: {count}."

    def suggestions(self) -> str:
        return format_suggestions(self.storage)

    def suggestion_markups(self) -> list[tuple[str, InlineKeyboardMarkup]]:
        return [(text, suggestion_keyboard(suggestion_id)) for suggestion_id, text in suggestion_lines(self.storage)]

    def handle_callback(self, data: str, *, now: datetime | None = None) -> tuple[str, InlineKeyboardMarkup | None]:
        moment = now or datetime.now(tz=UTC)
        if data.startswith("sg:"):
            return self._suggestion_callback(data, moment), None
        if not data.startswith("fb:"):
            return "Неизвестная кнопка.", None
        parts = data.split(":")
        if len(parts) < 3:
            return "Неизвестная кнопка.", None
        kind = parts[1]
        if kind == "n":
            if len(parts) != 4:
                return "Неизвестная кнопка.", None
            reason = REASON_CODES.get(parts[2])
            card_key = parts[3]
            if reason is None:
                return "Неизвестная кнопка.", None
            snapshot = self.storage.snapshot(card_key)
            if snapshot is None or not self.storage.set_feedback_reason(snapshot["external_id"], reason):
                return "Сначала отметь заказ как мусор.", None
            refresh_suggestions(self.storage, now=moment)
            return f"Причина: {REASON_LABELS[reason]}.", order_keyboard(_card_from_snapshot(snapshot))
        card_key = parts[2]
        snapshot = self.storage.snapshot(card_key)
        if snapshot is None:
            return "Карточка не найдена.", None
        if kind == "r":
            self._write_feedback(snapshot, "relevant", None, moment)
            created = refresh_suggestions(self.storage, now=moment)
            note = " Есть новое предложение: /suggestions." if created else ""
            return f"Отмечено: релевантно.{note}", None
        if kind == "j":
            self._write_feedback(snapshot, "junk", None, moment)
            return "Отмечено: мусор.", reason_keyboard(card_key, snapshot["link"])
        return "Неизвестная кнопка.", None

    def _suggestion_callback(self, data: str, now: datetime) -> str:
        parts = data.split(":")
        if len(parts) != 3 or parts[1] not in {"a", "d"} or not parts[2].isdigit():
            return "Неизвестная кнопка."
        suggestion_id = int(parts[2])
        if parts[1] == "a":
            return apply_suggestion(self.storage, suggestion_id, now=now)
        return decline_suggestion(self.storage, suggestion_id, now=now)

    def _write_feedback(self, snapshot: dict, verdict: str, reason: str | None, now: datetime) -> None:
        self.storage.save_feedback(
            order_id=str(snapshot["external_id"]),
            verdict=verdict,
            reason=reason,
            created_at=now.astimezone(UTC).isoformat(timespec="seconds"),
            user_id=snapshot["user_id"],
            username=str(snapshot["username"] or ""),
            price_rub=parse_budget_rub(str(snapshot["price"])),
            title=str(snapshot["title"]),
            description=str(snapshot["description"]),
        )

    def penalty_for(self, user_id: int | None, *, now: datetime) -> int:
        del user_id, now
        return 0
