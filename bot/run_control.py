"""In-process pause flag shared by the Kwork timer and the mail poll."""

from __future__ import annotations

import asyncio


class RunControl:
    def __init__(self) -> None:
        self.paused = False
        self.lock = asyncio.Lock()

    def pause(self) -> str:
        self.paused = True
        return "Автоматические прогоны на паузе. /run_now по-прежнему запускает Kwork."

    def resume(self) -> str:
        self.paused = False
        return "Автоматические прогоны возобновлены."
