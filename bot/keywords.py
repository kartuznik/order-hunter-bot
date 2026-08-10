from __future__ import annotations


def _match_count(text: str, keywords: list[str]) -> int:
    haystack = text.lower()
    return sum(1 for keyword in keywords if keyword in haystack)


def evaluate_filter(
    text: str,
    positive_keywords: list[str],
    negative_keywords: list[str],
    min_positive_matches: int,
) -> tuple[bool, bool, int]:
    haystack = text.lower()
    if any(keyword in haystack for keyword in negative_keywords):
        return False, True, 0
    matches = _match_count(haystack, positive_keywords)
    passed = matches >= min_positive_matches
    return passed, False, matches
