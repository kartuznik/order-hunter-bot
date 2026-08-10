from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET

import aiohttp

from bot.models import OrderCard

PRICE_RE = re.compile(r"Бюджет:\s*([^)\]]+)", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(value: str) -> str:
    text = TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return " ".join(text.split())


def _extract_price(title: str, description: str) -> str:
    for source in (title, description):
        match = PRICE_RE.search(source)
        if match:
            return match.group(1).strip()
    return "-"


def _make_external_id(link: str, title: str) -> str:
    if link.strip():
        return link.strip()
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:20]


async def fetch_fl_orders(url: str) -> list[OrderCard]:
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            raw_xml = await response.text()

    root = ET.fromstring(raw_xml)
    items = root.findall(".//item")
    result: list[OrderCard] = []
    for item in items:
        title = _clean_text(item.findtext("title", default="").strip())
        link = item.findtext("link", default="").strip()
        description = _clean_text(item.findtext("description", default="").strip())
        if not title or not link:
            continue
        result.append(
            OrderCard(
                source="fl",
                external_id=_make_external_id(link=link, title=title),
                title=title,
                link=link,
                description=description,
                price=_extract_price(title=title, description=description),
            )
        )
    return result
