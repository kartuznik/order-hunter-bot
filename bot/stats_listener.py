from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot

from bot.config import Settings
from bot.database import SeenStorage

logger = logging.getLogger("order_hunter.stats_listener")


def _is_stats_command(text: str) -> bool:
    command = text.strip().split(maxsplit=1)[0].lower()
    return command == "/stats" or command.startswith("/stats@")


def _render_stats_text(stats: dict[str, int]) -> str:
    return (
        "📊 Order Hunter stats\n"
        f"seen_total: {stats['total_seen']}\n"
        f"passed_filter: {stats['total_filtered']}\n"
        f"blocked_by_negative: {stats['total_blocked_negative']}\n"
        f"rejected_by_and_logic: {stats['total_rejected_and']}\n"
        f"sent_notifications: {stats['total_notified']}"
    )


async def run_stats_listener(
    *,
    settings: Settings,
    storage: SeenStorage,
    stop_event: asyncio.Event,
) -> None:
    if settings.dry_run:
        logger.info("Stats listener disabled in dry-run mode")
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    offset: int | None = None
    try:
        while not stop_event.is_set():
            try:
                updates = await bot.get_updates(
                    offset=offset,
                    timeout=25,
                    allowed_updates=["message"],
                )
            except Exception as error:
                logger.warning("Stats listener polling error: %s", error)
                await asyncio.sleep(5)
                continue

            for upd in updates:
                offset = upd.update_id + 1
                message = upd.message
                if message is None or not message.text:
                    continue
                if not _is_stats_command(message.text):
                    continue
                chat_id = message.chat.id
                if chat_id not in settings.notify_chat_ids:
                    with contextlib.suppress(Exception):
                        await bot.send_message(chat_id=chat_id, text="Недостаточно прав.")
                    continue
                stats = storage.read_stats()
                await bot.send_message(chat_id=chat_id, text=_render_stats_text(stats))
    finally:
        await bot.session.close()
