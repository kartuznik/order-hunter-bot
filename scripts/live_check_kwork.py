from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.config import get_settings
from bot.kwork_imap import fetch_kwork_orders_from_imap, mark_latest_kwork_mail_unseen
from bot.notifier import Notifier


async def main() -> None:
    settings = get_settings()
    notifier = Notifier(settings)
    try:
        cards = await fetch_kwork_orders_from_imap()
        if not cards:
            marked = await mark_latest_kwork_mail_unseen()
            if marked:
                cards = await fetch_kwork_orders_from_imap()
                print("KWORK_OLD_MAIL_MARKED_UNSEEN")
            else:
                print("KWORK_MARK_UNSEEN_FAILED")

        if not cards:
            print("KWORK_LIVE_NO_PROJECT_LINKS")
            return

        sent = await notifier.send_order(cards[0])
        print("KWORK_LIVE_SENT" if sent else "KWORK_LIVE_NOT_SENT")
    finally:
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(main())
