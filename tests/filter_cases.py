from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.keywords import evaluate_filter

CORE = ["bot", "бот", "telegram", "телеграм", "tg"]
SECONDARY = [
    "python",
    "ai",
    "ии",
    "gpt",
    "автоматизация",
    "парсер",
    "скрипт",
    "магазин",
    "оплата",
    "корзина",
    "анкета",
    "заявка",
    "опрос",
    "рассылка",
]
NEGATIVE = [
    "копирайт",
    "рерайт",
    "дизайн",
]


def _assert_case(text: str, expected_passed: bool, expected_blocked: bool) -> None:
    passed, blocked, _ = evaluate_filter(
        text=text,
        core_keywords=CORE,
        secondary_keywords=SECONDARY,
        negative_keywords=NEGATIVE,
    )
    assert passed is expected_passed, f"Unexpected pass for: {text!r}"
    assert blocked is expected_blocked, f"Unexpected block for: {text!r}"


def main() -> None:
    # rejected: no core and no secondary whole-word matches
    _assert_case(
        "Нужен копи паст и поменять текст: проектная работа на дому",
        expected_passed=False,
        expected_blocked=False,
    )
    # passed: has core telegram/бот and secondary анкета
    _assert_case(
        "нужен telegram бот для анкеты",
        expected_passed=True,
        expected_blocked=False,
    )
    # blocked: negative words have top priority
    _assert_case(
        "копирайт рерайт",
        expected_passed=False,
        expected_blocked=True,
    )
    print("FILTER_CASES_OK")


if __name__ == "__main__":
    main()
