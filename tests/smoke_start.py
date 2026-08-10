from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.config import get_settings
from bot.database import SeenStorage
from bot.main import _process_poll
from bot.notifier import Notifier


async def run() -> None:
    settings = get_settings()
    settings.TELEGRAM_BOT_TOKEN = "PLACEHOLDER_TOKEN"
    notifier = Notifier(settings)
    storage = SeenStorage(settings.db_file)
    await notifier.send_startup_test()
    metrics = await _process_poll(storage=storage, notifier=notifier)
    print(
        f"SMOKE_OK order_hunter /start dry_run={notifier.dry_run} "
        f"seen={metrics['seen']} filtered={metrics['filtered']}"
    )
    await notifier.close()


if __name__ == "__main__":
    asyncio.run(run())
