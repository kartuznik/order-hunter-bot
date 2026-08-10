from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime

from bot.config import get_settings
from bot.database import SeenStorage
from bot.fl_rss import fetch_fl_orders
from bot.keywords import evaluate_filter
from bot.kwork_html import fetch_kwork_orders
from bot.kwork_imap import fetch_kwork_orders_from_imap
from bot.models import OrderCard
from bot.notifier import Notifier

logger = logging.getLogger("order_hunter")


async def _collect_orders() -> list[OrderCard]:
    settings = get_settings()
    cards: list[OrderCard] = []
    cards.extend(await fetch_kwork_orders_from_imap())
    if settings.ENABLE_FL:
        cards.extend(await fetch_fl_orders(settings.FL_RSS_URL))
    if settings.ENABLE_KWORK:
        cards.extend(await fetch_kwork_orders(settings.KWORK_PROJECTS_URL))
    return cards


async def _process_poll(storage: SeenStorage, notifier: Notifier) -> dict[str, int]:
    settings = get_settings()
    seen_total = 0
    passed_filter = 0
    blocked_by_negative = 0
    rejected_by_and_logic = 0
    sent_notifications = 0

    cards = await _collect_orders()
    for card in cards:
        seen_total += 1
        full_text = f"{card.title}\n{card.description}"
        passed, blocked_negative, _ = evaluate_filter(
            text=full_text,
            core_keywords=settings.core_keywords,
            secondary_keywords=settings.secondary_keywords,
            negative_keywords=settings.negative_keywords,
        )
        if blocked_negative:
            blocked_by_negative += 1
            continue
        if not passed:
            rejected_by_and_logic += 1
            continue
        passed_filter += 1
        if storage.is_seen(card.source, card.external_id):
            continue
        inserted = storage.mark_seen(
            source=card.source,
            external_id=card.external_id,
            title=card.title,
            link=card.link,
            price=card.price,
        )
        if not inserted:
            continue
        sent = await notifier.send_order(card)
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
        "Order hunter started: interval=%ss dry_run=%s enable_kwork_imap=%s enable_fl=%s enable_kwork=%s",
        settings.POLL_INTERVAL_SECONDS,
        settings.dry_run,
        settings.ENABLE_KWORK_IMAP,
        settings.ENABLE_FL,
        settings.ENABLE_KWORK,
    )
    await notifier.send_startup_test()

    stop_event = asyncio.Event()
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
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(main())
