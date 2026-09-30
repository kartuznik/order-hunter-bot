from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import Settings
from bot.models import OrderCard

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
        text = (
            f"🎯 Новый заказ ({card.source.upper()})\n"
            f"Название: {card.title}\n"
            f"Цена: {card.price}\n"
            f"Ссылка: {card.link}"
        )
        if self._settings.dry_run or not self._settings.notify_chat_ids:
            logger.info("[DRY-RUN] %s", text)
            return False

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть заказ", url=card.link)]]
        )
        for chat_id in self._settings.notify_chat_ids:
            await self._bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        return True

    async def send_owner_alert(self, text: str) -> None:
        if self._settings.dry_run or not self._settings.notify_chat_ids:
            logger.info("[DRY-RUN] %s", text)
            return
        for chat_id in self._settings.notify_chat_ids:
            await self._bot.send_message(chat_id=chat_id, text=text)
