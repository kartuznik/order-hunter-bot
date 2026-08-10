from __future__ import annotations

import re
from functools import lru_cache

WORD_RE = re.compile(r"(?<!\w)[\w]+(?!\w)", re.IGNORECASE)
RU_ENDINGS = (
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
    "ие",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)


def _contains_cyrillic(value: str) -> bool:
    return any("а" <= ch <= "я" or "А" <= ch <= "Я" or ch in {"ё", "Ё"} for ch in value)


def _normalize_ru(word: str) -> str:
    token = word.lower().replace("ё", "е")
    for ending in RU_ENDINGS:
        if len(token) > len(ending) + 2 and token.endswith(ending):
            return token[: -len(ending)]
    return token


@lru_cache(maxsize=256)
def _normalized_keywords(keywords_key: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for keyword in keywords_key:
        token = keyword.lower().strip()
        if _contains_cyrillic(token):
            token = _normalize_ru(token)
        result.append(token)
    return tuple(result)


def _tokenize_words(text: str) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text)]


def _count_whole_word_matches(text: str, keywords: list[str]) -> int:
    keyword_key = tuple(k.strip().lower() for k in keywords if k.strip())
    if not keyword_key:
        return 0
    normalized_keys = _normalized_keywords(keyword_key)
    raw_tokens = _tokenize_words(text)
    normalized_tokens = [
        _normalize_ru(token) if _contains_cyrillic(token) else token for token in raw_tokens
    ]

    matched = 0
    for idx, key in enumerate(keyword_key):
        key_norm = normalized_keys[idx]
        if key in raw_tokens or key_norm in normalized_tokens:
            matched += 1
    return matched


def evaluate_filter(
    text: str,
    core_keywords: list[str],
    secondary_keywords: list[str],
    negative_keywords: list[str],
) -> tuple[bool, bool, tuple[int, int]]:
    if _count_whole_word_matches(text, negative_keywords) > 0:
        return False, True, (0, 0)
    core_matches = _count_whole_word_matches(text, core_keywords)
    secondary_matches = _count_whole_word_matches(text, secondary_keywords)
    passed = core_matches >= 1 and secondary_matches >= 1
    return passed, False, (core_matches, secondary_matches)
