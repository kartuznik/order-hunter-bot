from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import get_settings
from bot.fl_rss import fetch_fl_orders
from bot.keywords import evaluate_filter


async def main() -> None:
    settings = get_settings()
    if not settings.notify_chat_ids:
        raise SystemExit("NOTIFY_CHAT_IDS is empty")

    cards = await fetch_fl_orders(settings.FL_RSS_URL)
    selected = None
    for card in cards:
        passed, blocked, _ = evaluate_filter(
            text=f"{card.title}\n{card.description}",
            core_keywords=settings.core_keywords,
            secondary_keywords=settings.secondary_keywords,
            negative_keywords=settings.negative_keywords,
        )
        if passed and not blocked:
            selected = card
            break

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        if selected is None:
            await bot.send_message(
                chat_id=settings.notify_chat_ids[0],
                text="⚠️ FL live-check: заказ по новой логике не найден в текущей выборке.",
            )
            print("FL_CONTROL_SENT_SYNTHETIC")
            return
        text = (
            "✅ FL контроль по новой логике core+secondary\n"
            f"Название: {selected.title}\n"
            f"Цена: {selected.price}\n"
            f"Ссылка: {selected.link}"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть заказ", url=selected.link)]]
        )
        await bot.send_message(chat_id=settings.notify_chat_ids[0], text=text, reply_markup=keyboard)
        print("FL_CONTROL_SENT_REAL")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
