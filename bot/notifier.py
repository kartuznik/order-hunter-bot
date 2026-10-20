from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiogram import Bot

from bot.config import Settings
from bot.kwork_filter import deadline_days
from bot.models import OrderCard
from bot.owner_commands import order_keyboard

logger = logging.getLogger("order_hunter.notifier")


class Notifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bot = None if settings.dry_run else Bot(token=settings.TELEGRAM_BOT_TOKEN)

    @property
    def dry_run(self) -> bool:
        return self._bot is None

    async def close(self) -> None:
        if self._bot is not None:
            await self._bot.session.close()

    async def send_startup_test(self) -> None:
        text = "🧪 Order Hunter стартовал. Тестовое уведомление."
        if self._settings.dry_run or not self._settings.notify_chat_ids:
            logger.info("[DRY-RUN] %s", text)
            return
        for chat_id in self._settings.notify_chat_ids:
            await self._bot.send_message(chat_id=chat_id, text=text)

    async def send_order(self, card: OrderCard) -> bool:
        text = render_order(card)
        if self._settings.dry_run or not self._settings.notify_chat_ids:
            logger.info("[DRY-RUN] %s", text)
            return False

        keyboard = order_keyboard(card)
        for chat_id in self._settings.notify_chat_ids:
            await self._bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        return True

    async def send_owner_alert(self, text: str) -> None:
        if self._settings.dry_run or not self._settings.notify_chat_ids:
            logger.info("[DRY-RUN] %s", text)
            return
        for chat_id in self._settings.notify_chat_ids:
            await self._bot.send_message(chat_id=chat_id, text=text)


def render_order(card: OrderCard, *, now: datetime | None = None) -> str:
    lines = [
        f"🎯 Новый заказ ({card.source.upper()})",
        f"Название: {card.title}",
        f"Цена: {card.price}",
    ]
    days = deadline_days(card.title, card.description)
    if days is not None:
        lines.append(f"Срок: {days} дн.")
    if isinstance(card.offers, int) and not isinstance(card.offers, bool):
        lines.append(f"Откликов: {card.offers}")
    age = _age_hours(card.date_confirm, now or datetime.now(tz=UTC))
    if age is not None:
        lines.append(f"Возраст: {age} ч")
    lines.append(f"Ссылка: {card.link}")
    return "\n".join(lines)


def _age_hours(date_confirm: int | None, now: datetime) -> int | None:
    if not isinstance(date_confirm, int) or isinstance(date_confirm, bool) or date_confirm <= 0:
        return None
    confirmed = datetime.fromtimestamp(date_confirm, tz=UTC)
    return max(0, int((now - confirmed).total_seconds() // 3600))
