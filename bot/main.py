from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime

from bot.config import get_settings
from bot.database import SeenStorage
from bot.fl_rss import fetch_fl_orders
from bot.keywords import passes_keyword_filter
from bot.kwork_html import fetch_kwork_orders
from bot.models import OrderCard
from bot.notifier import Notifier

logger = logging.getLogger("order_hunter")


async def _collect_orders() -> list[OrderCard]:
    settings = get_settings()
    cards: list[OrderCard] = []
    if settings.ENABLE_FL:
        cards.extend(await fetch_fl_orders(settings.FL_RSS_URL))
    if settings.ENABLE_KWORK:
        cards.extend(await fetch_kwork_orders(settings.KWORK_PROJECTS_URL))
    return cards


async def _process_poll(storage: SeenStorage, notifier: Notifier) -> dict[str, int]:
    settings = get_settings()
    seen_count = 0
    filtered_count = 0
    notified_count = 0

    cards = await _collect_orders()
    for card in cards:
        seen_count += 1
        full_text = f"{card.title}\n{card.description}"
        if not passes_keyword_filter(full_text, settings.keywords):
            continue
        filtered_count += 1
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
            notified_count += 1

    storage.bump_stats(seen=seen_count, filtered=filtered_count, notified=notified_count)
    return {"seen": seen_count, "filtered": filtered_count, "notified": notified_count}


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
        "Order hunter started: interval=%ss dry_run=%s enable_fl=%s enable_kwork=%s",
        settings.POLL_INTERVAL_SECONDS,
        settings.dry_run,
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
                    "Poll complete: seen=%s filtered=%s notified=%s total_seen=%s total_filtered=%s "
                    "total_notified=%s runtime_minutes=%s",
                    metrics["seen"],
                    metrics["filtered"],
                    metrics["notified"],
                    total["total_seen"],
                    total["total_filtered"],
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
