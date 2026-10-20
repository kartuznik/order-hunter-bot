from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.types import CallbackQuery

from bot.config import Settings
from bot.database import SeenStorage
from bot.kwork_api import NOTICE_AUTH
from bot.kwork_token import render_token_status
from bot.owner_commands import OwnerCommands, command_name

logger = logging.getLogger("order_hunter.stats_listener")


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
    commands: OwnerCommands,
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
                    allowed_updates=["message", "callback_query"],
                )
            except Exception as error:
                logger.warning("Stats listener polling error: %s", error)
                await asyncio.sleep(5)
                continue

            for upd in updates:
                offset = upd.update_id + 1
                if upd.callback_query is not None:
                    await _handle_callback(bot, settings, commands, upd.callback_query)
                    continue
                message = upd.message
                if message is None or not message.text:
                    continue
                name = command_name(message.text)
                if name is None:
                    continue
                chat_id = message.chat.id
                if chat_id not in settings.notify_chat_ids:
                    with contextlib.suppress(Exception):
                        await bot.send_message(chat_id=chat_id, text="Недостаточно прав.")
                    continue
                if name == "/suggestions":
                    markups = commands.suggestion_markups()
                    if not markups:
                        await bot.send_message(chat_id=chat_id, text="Предложений нет.")
                    for suggestion_text, markup in markups:
                        await bot.send_message(chat_id=chat_id, text=suggestion_text, reply_markup=markup)
                    continue
                text = await _command_text(name, message.text, settings, storage, commands)
                if text:
                    await bot.send_message(chat_id=chat_id, text=text)
    finally:
        await bot.session.close()


async def _command_text(
    name: str,
    text: str,
    settings: Settings,
    storage: SeenStorage,
    commands: OwnerCommands,
) -> str:
    if name == "/stats":
        return _render_stats_text(storage.read_stats())
    if name == "/kwork_token_status":
        return render_token_status(
            token=settings.kwork_token,
            updated_raw=settings.KWORK_TOKEN_UPDATED_AT,
            now=datetime.now(tz=UTC),
            warn_days=settings.KWORK_TOKEN_WARN_DAYS,
            auth_failed=storage.get_notice(NOTICE_AUTH) == "sent",
        )
    if name == "/run_now":
        return await commands.run_now()
    if name == "/run_stats":
        return commands.run_stats()
    if name == "/pause":
        return commands.pause()
    if name == "/resume":
        return commands.resume()
    if name == "/feedback_stats":
        return commands.feedback_stats()
    if name == "/blacklist":
        return commands.blacklist(text)
    if name == "/parked":
        return commands.parked()
    if name == "/parked_clear":
        return commands.parked_clear()
    return ""


async def _handle_callback(bot: Bot, settings: Settings, commands: OwnerCommands, query: CallbackQuery) -> None:
    message = query.message
    chat_id = message.chat.id if message is not None else None
    if chat_id not in settings.notify_chat_ids:
        with contextlib.suppress(Exception):
            await bot.answer_callback_query(query.id, text="Недостаточно прав.")
        return
    answer, markup = commands.handle_callback(query.data or "")
    with contextlib.suppress(Exception):
        await bot.answer_callback_query(query.id, text=answer[:180])
    if markup is not None and message is not None:
        with contextlib.suppress(Exception):
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message.message_id,
                reply_markup=markup,
            )
