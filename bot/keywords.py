from __future__ import annotations


def _match_count(text: str, keywords: list[str]) -> int:
    haystack = text.lower()
    return sum(1 for keyword in keywords if keyword in haystack)


def evaluate_filter(
    text: str,
    core_keywords: list[str],
    secondary_keywords: list[str],
    negative_keywords: list[str],
    ) -> tuple[bool, bool, tuple[int, int]]:
    haystack = text.lower()
    if any(keyword in haystack for keyword in negative_keywords):
        return False, True, (0, 0)
    core_matches = _match_count(haystack, core_keywords)
    secondary_matches = _match_count(haystack, secondary_keywords)
    passed = core_matches >= 1 and secondary_matches >= 1
    return passed, False, (core_matches, secondary_matches)
