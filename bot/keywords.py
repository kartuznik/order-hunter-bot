from __future__ import annotations


def passes_keyword_filter(text: str, keywords: list[str]) -> bool:
    haystack = text.lower()
    return any(keyword in haystack for keyword in keywords)
