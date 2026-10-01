from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from bot.config import (
    BUDGET_DROP_RUB,
    DEADLINE_DROP_DAYS,
    GRAY_BUDGET_RUB,
    GRAY_KEYWORDS,
    GRAY_MODULE_COUNT,
    GREEN_SCORE_THRESHOLD,
    GREEN_WEIGHTS,
    MODULE_DROP_BUDGET_RUB,
    MODULE_DROP_COUNT,
    RED_KEYWORDS,
)
from bot.models import OrderCard

GRAY_TITLE_PREFIX = "[⚠️ СЕРЫЙ] "

REASON_RED = "blocked_by_red_list"
REASON_LOW_SCORE = "blocked_by_low_score"
REASON_BUDGET = "blocked_by_budget"
REASON_DEADLINE = "blocked_by_deadline"
REASON_MODULES = "blocked_by_modules"
REASON_TITLE = "blocked_by_title_repeat"
REASON_ACCEPT = "accept"
REASON_GRAY = "gray"

_TOKEN_RE = re.compile(r"(?<!\w)[\w]+(?!\w)")
_RU_ENDINGS = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ыми",
    "ими",
    "ией",
    "иях",
    "ах",
    "ях",
    "ов",
    "ев",
    "ей",
    "ой",
    "ый",
    "ий",
    "ые",
    "ое",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)
_DAY = r"д(?:ень|ня|ней)"
_DEADLINE_RES = (
    re.compile(rf"\bза\s+(\d+)\s+{_DAY}\b"),
    re.compile(rf"\bсрок\w*\s*[:\-]?\s*(\d+)\s+{_DAY}\b"),
    re.compile(r"\bдедлайн\w*\s*[:\-]?\s*(\d+)"),
    re.compile(r"\bdeadline\s*[:\-]?\s*(\d+)"),
)
_MODULE_RE = re.compile(r"\b(\d+)\s+(?:модул|страниц|экран)")
_REMOTE_RE = re.compile(r"\bremote\b|(?<!\w)удален")
_BOT_RE = re.compile(r"(?<!\w)бот|\btelegram\b|(?<!\w)телеграм")


_TELEGRAM_FAMILY = frozenset({"telegram", "телеграм", "телеграмм", "телега", "тг"})


@dataclass(slots=True)
class FilterDecision:
    accept: bool
    reason: str
    gray: bool = False
    score: int = 0
    matched_red: str = ""


def title_hash(title: str) -> str:
    normalized = " ".join(_normalize(title).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_budget_rub(price: str) -> int | None:
    compact = _normalize(price).replace(" ", "").replace("\u00a0", "")
    if compact in {"", "-"}:
        return None
    match = re.search(r"\d+", compact)
    if match is None:
        return None
    return int(match.group(0))


def decide_card(card: OrderCard, *, title_repeat: bool) -> FilterDecision:
    text = _normalize(f"{card.title}\n{card.description}")
    score = calculate_green_score(card.title, card.description)
    matched_red = _matched_red(text)
    if matched_red is not None:
        return FilterDecision(False, REASON_RED, score=score, matched_red=matched_red)
    if score < GREEN_SCORE_THRESHOLD:
        return FilterDecision(False, REASON_LOW_SCORE, score=score)

    budget = parse_budget_rub(card.price)
    if budget is not None and budget < BUDGET_DROP_RUB:
        return FilterDecision(False, REASON_BUDGET, score=score)
    deadline_days = _deadline_days(text)
    if deadline_days is not None and deadline_days < DEADLINE_DROP_DAYS:
        return FilterDecision(False, REASON_DEADLINE, score=score)
    modules = _module_count(text)
    if (
        modules is not None
        and modules > MODULE_DROP_COUNT
        and budget is not None
        and budget < MODULE_DROP_BUDGET_RUB
    ):
        return FilterDecision(False, REASON_MODULES, score=score)
    if title_repeat:
        return FilterDecision(False, REASON_TITLE, score=score)
    if _is_gray(text, budget=budget, modules=modules):
        return FilterDecision(True, REASON_GRAY, gray=True, score=score)
    return FilterDecision(True, REASON_ACCEPT, score=score)


def calculate_green_score(title: str, description: str) -> int:
    text = _normalize(f"{title}\n{description}")
    stems = [_stem_token(token) for token in _TOKEN_RE.findall(text)]
    score = 0
    family_counted = False
    for term, weight in GREEN_WEIGHTS.items():
        if not _weight_term_matches(text, stems, term):
            continue
        if term in _TELEGRAM_FAMILY:
            if family_counted:
                continue
            family_counted = True
        score += weight
    return score


def _normalize(value: str) -> str:
    return value.lower().replace("ё", "е")


def _stem_token(token: str) -> str:
    if not _has_cyrillic(token):
        return token
    for ending in _RU_ENDINGS:
        if len(token) > len(ending) + 2 and token.endswith(ending):
            return token[: -len(ending)]
    return token


def _has_cyrillic(value: str) -> bool:
    return any("а" <= ch <= "я" for ch in value)


def _weight_term_matches(text: str, stems: list[str], term: str) -> bool:
    parts = [part for part in re.split(r"[^\w]+", _normalize(term).strip()) if part]
    if not parts or any(not _has_cyrillic(part) for part in parts):
        return _has(text, term)
    wanted = [_stem_token(part) for part in parts]
    width = len(wanted)
    return any(stems[index : index + width] == wanted for index in range(len(stems) - width + 1))


def _matched_red(text: str) -> str | None:
    stems = [_stem_token(token) for token in _TOKEN_RE.findall(text)]
    for term in RED_KEYWORDS:
        if _weight_term_matches(text, stems, term):
            return term
    if _has(text, "нейросеть") and _BOT_RE.search(text) is None:
        return "нейросеть"
    if _has(text, "москва") and _REMOTE_RE.search(text) is None:
        return "москва"
    if _has(text, "санкт-петербург") and _REMOTE_RE.search(text) is None:
        return "санкт-петербург"
    return None


def _has_green_core(text: str) -> bool:
    stems = [_stem_token(token) for token in _TOKEN_RE.findall(text)]
    return any(
        weight >= 3 and _weight_term_matches(text, stems, term)
        for term, weight in GREEN_WEIGHTS.items()
    )


def _is_gray(text: str, *, budget: int | None, modules: int | None) -> bool:
    if _has_any(text, GRAY_KEYWORDS):
        return True
    if _has(text, "claude") and _has(text, "python"):
        return True
    if budget is not None and budget < GRAY_BUDGET_RUB and _has_green_core(text):
        return True
    return budget is None and modules is not None and modules > GRAY_MODULE_COUNT


def _deadline_days(text: str) -> int | None:
    found = [int(match.group(1)) for pattern in _DEADLINE_RES for match in pattern.finditer(text)]
    if not found:
        return None
    return min(found)


def _module_count(text: str) -> int | None:
    found = [int(match.group(1)) for match in _MODULE_RE.finditer(text)]
    if not found:
        return None
    return max(found)


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_has(text, term) for term in terms)


def _has(text: str, term: str) -> bool:
    return _pattern(term).search(text) is not None


@lru_cache(maxsize=256)
def _pattern(term: str) -> re.Pattern[str]:
    normalized = _normalize(term).strip()
    body = re.escape(normalized).replace(r"\ ", r"\s+")
    start = r"\b" if normalized[:1].isalnum() else r"(?<!\w)"
    end = r"\b" if normalized[-1:].isalnum() else r"(?!\w)"
    return re.compile(start + body + end)
