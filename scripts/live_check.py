from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import get_settings
from bot.fl_rss import fetch_fl_orders


async def main() -> None:
    settings = get_settings()
    if not settings.notify_chat_ids:
        raise SystemExit("NOTIFY_CHAT_IDS is empty")

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    chat_id = settings.notify_chat_ids[0]
    try:
        cards = await fetch_fl_orders(settings.FL_RSS_URL)
        if cards:
            card = cards[0]
            text = (
                "✅ Контрольное уведомление (live-check)\n"
                f"Источник: {card.source.upper()}\n"
                f"Название: {card.title}\n"
                f"Цена: {card.price}\n"
                f"Ссылка: {card.link}"
            )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть заказ", url=card.link)]]
            )
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
            print("CONTROL_SENT_REAL_RSS")
        else:
            await bot.send_message(chat_id=chat_id, text="Охотник жив, тест прошел")
            print("CONTROL_SENT_SYNTHETIC")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
