from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from dataclasses import replace
from datetime import UTC, datetime

from bot.config import TITLE_REPEAT_DAYS, get_settings
from bot.database import SeenStorage
from bot.kwork_api import run_kwork_loop
from bot.kwork_filter import GRAY_TITLE_PREFIX, decide_card, title_hash
from bot.kwork_html import fetch_kwork_orders
from bot.kwork_imap import fetch_kwork_orders_from_imap
from bot.models import OrderCard
from bot.notifier import Notifier
from bot.stats_listener import run_stats_listener

logger = logging.getLogger("order_hunter")


async def _collect_orders() -> list[OrderCard]:
    settings = get_settings()
    cards: list[OrderCard] = []
    cards.extend(await fetch_kwork_orders_from_imap())
    if settings.ENABLE_KWORK:
        cards.extend(await fetch_kwork_orders(settings.KWORK_PROJECTS_URL))
    return cards


async def _accept_cards(
    storage: SeenStorage,
    notifier: Notifier,
    cards: list[OrderCard],
) -> dict[str, int]:
    settings = get_settings()
    seen_total = 0
    passed_filter = 0
    blocked_by_negative = 0
    rejected_by_and_logic = 0
    sent_notifications = 0

    for card in cards:
        seen_total += 1
        decision = decide_card(
            card,
            title_repeat=storage.title_seen_within(title_hash(card.title), TITLE_REPEAT_DAYS),
        )
        if not decision.accept:
            if settings.DEBUG_FILTER_LOGS and decision.matched_red:
                logger.info(
                    'Kwork filter id=%s title=%s reason=%s score=%s matched_red="%s"',
                    card.external_id,
                    card.title.replace("\n", " ")[:60],
                    decision.reason,
                    decision.score,
                    decision.matched_red,
                )
            elif settings.DEBUG_FILTER_LOGS:
                logger.info(
                    "Kwork filter id=%s title=%s reason=%s score=%s",
                    card.external_id,
                    card.title.replace("\n", " ")[:60],
                    decision.reason,
                    decision.score,
                )
            elif decision.matched_red:
                logger.info(
                    'Kwork filter id=%s reason=%s matched_red="%s"',
                    card.external_id,
                    decision.reason,
                    decision.matched_red,
                )
            else:
                logger.info("Kwork filter id=%s reason=%s", card.external_id, decision.reason)
            if decision.reason == "blocked_by_red_list":
                blocked_by_negative += 1
            else:
                rejected_by_and_logic += 1
            continue
        passed_filter += 1
        logger.info(
            'Kwork filter id=%s title=%s accepted score=%s matched_green="%s"',
            card.external_id,
            card.title.replace("\n", " ")[:60],
            decision.score,
            decision.matched_green,
        )
        if storage.is_seen(card.source, card.external_id):
            continue
        outgoing = card
        if decision.gray:
            outgoing = replace(card, title=f"{GRAY_TITLE_PREFIX}{card.title}")
        inserted = storage.mark_seen(
            source=outgoing.source,
            external_id=outgoing.external_id,
            title=outgoing.title,
            link=outgoing.link,
            price=outgoing.price,
        )
        if not inserted:
            continue
        storage.remember_title(title_hash(card.title))
        sent = await notifier.send_order(outgoing)
        if sent:
            sent_notifications += 1

    storage.bump_stats(
        seen=seen_total,
        filtered=passed_filter,
        blocked_negative=blocked_by_negative,
        rejected_and=rejected_by_and_logic,
        notified=sent_notifications,
    )
    return {
        "seen_total": seen_total,
        "passed_filter": passed_filter,
        "blocked_by_negative": blocked_by_negative,
        "rejected_by_and_logic": rejected_by_and_logic,
        "sent_notifications": sent_notifications,
    }


async def _process_poll(storage: SeenStorage, notifier: Notifier) -> dict[str, int]:
    cards = await _collect_orders()
    return await _accept_cards(storage, notifier, cards)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings = get_settings()
    storage = SeenStorage(settings.db_file)
    notifier = Notifier(settings)
    started_at = datetime.now(tz=UTC)

    logger.info(
        "Order hunter started: interval=%ss dry_run=%s enable_kwork_imap=%s enable_kwork=%s kwork_token=%s",
        settings.POLL_INTERVAL_SECONDS,
        settings.dry_run,
        settings.ENABLE_KWORK_IMAP,
        settings.ENABLE_KWORK,
        bool(settings.kwork_token),
    )
    await notifier.send_startup_test()

    stop_event = asyncio.Event()
    stats_task = asyncio.create_task(
        run_stats_listener(settings=settings, storage=storage, stop_event=stop_event)
    )

    async def _accept_kwork(cards: list[OrderCard]) -> None:
        await _accept_cards(storage, notifier, cards)

    kwork_task = asyncio.create_task(
        run_kwork_loop(
            storage=storage,
            notifier=notifier,
            stop_event=stop_event,
            accept_cards=_accept_kwork,
        )
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        while not stop_event.is_set():
            try:
                metrics = await _process_poll(storage=storage, notifier=notifier)
                total = storage.read_stats()
                runtime_minutes = int((datetime.now(tz=UTC) - started_at).total_seconds() // 60)
                logger.info(
                    "Poll complete: seen_total=%s passed_filter=%s blocked_by_negative=%s "
                    "rejected_by_and_logic=%s sent_notifications=%s totals_seen=%s totals_passed=%s "
                    "totals_blocked=%s totals_rejected_and=%s totals_notified=%s runtime_minutes=%s",
                    metrics["seen_total"],
                    metrics["passed_filter"],
                    metrics["blocked_by_negative"],
                    metrics["rejected_by_and_logic"],
                    metrics["sent_notifications"],
                    total["total_seen"],
                    total["total_filtered"],
                    total["total_blocked_negative"],
                    total["total_rejected_and"],
                    total["total_notified"],
                    runtime_minutes,
                )
            except Exception as error:
                logger.exception("Poll cycle failed: %s", error)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue
    finally:
        stop_event.set()
        stats_task.cancel()
        kwork_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stats_task
        with contextlib.suppress(asyncio.CancelledError):
            await kwork_task
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(main())
