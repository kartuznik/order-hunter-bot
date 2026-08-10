from __future__ import annotations

import asyncio
import hashlib
import imaplib
import logging
import re
from collections import OrderedDict
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import unquote

from bot.config import get_settings
from bot.models import OrderCard

logger = logging.getLogger("order_hunter.kwork_imap")

TAG_RE = re.compile(r"<[^>]+>")
PROJECT_LINK_RE = re.compile(r"https://kwork\.ru/projects/\d+[^\s\"'<)]*", re.IGNORECASE)
ANCHOR_RE = re.compile(
    r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
PRICE_RE = re.compile(r"(?:Бюджет|budget|цена)\s*[:\-]?\s*([0-9\s.,]+(?:₽|руб|rub)?)", re.IGNORECASE)


def _strip_html(value: str) -> str:
    return " ".join(unescape(TAG_RE.sub(" ", value)).split())


def _extract_deep_project_link(raw_link: str) -> str:
    decoded = unquote(unescape(raw_link))
    match = PROJECT_LINK_RE.search(decoded)
    if match:
        return match.group(0)
    return ""


def _extract_project_cards(
    *,
    message_id: str,
    subject: str,
    html_parts: list[str],
    text_parts: list[str],
) -> list[OrderCard]:
    cards_by_link: OrderedDict[str, OrderCard] = OrderedDict()
    full_plain = " ".join(text_parts)
    full_html = " ".join(html_parts)

    for html_part in html_parts:
        for anchor_match in ANCHOR_RE.finditer(html_part):
            raw_href = anchor_match.group(1)
            deep_link = _extract_deep_project_link(raw_href)
            if not deep_link:
                continue
            anchor_text = _strip_html(anchor_match.group(2))
            context_start = max(0, anchor_match.start() - 200)
            context_end = min(len(html_part), anchor_match.end() + 200)
            context = _strip_html(html_part[context_start:context_end])
            price_match = PRICE_RE.search(context) or PRICE_RE.search(anchor_text)
            price = price_match.group(1).strip() if price_match else "-"
            title = anchor_text or subject or "Kwork project"
            cards_by_link.setdefault(
                deep_link,
                OrderCard(
                    source="kwork_imap",
                    external_id=deep_link,
                    title=title,
                    link=deep_link,
                    description=context[:1000],
                    price=price,
                ),
            )

    if cards_by_link:
        return list(cards_by_link.values())

    blob = " ".join([full_plain, full_html])
    for raw_link in re.findall(r"https?://[^\s\"'<>]+", blob):
        deep_link = _extract_deep_project_link(raw_link)
        if not deep_link:
            continue
        cards_by_link.setdefault(
            deep_link,
            OrderCard(
                source="kwork_imap",
                external_id=deep_link,
                title=subject or "Kwork project",
                link=deep_link,
                description=_strip_html(full_plain)[:1000] if full_plain else subject,
                price="-",
            ),
        )

    if cards_by_link:
        return list(cards_by_link.values())

    href_count = len(re.findall(r"href=[\"']", full_html, flags=re.IGNORECASE))
    projects_path_count = len(re.findall(r"/projects\b", full_html, flags=re.IGNORECASE))
    logger.info(
        "Kwork mail has no deep project links: msg_id=%s subject_len=%s href_count=%s projects_path_count=%s",
        message_id,
        len(subject),
        href_count,
        projects_path_count,
    )
    return []


def _message_to_orders(message_bytes: bytes) -> list[OrderCard]:
    settings = get_settings()
    message = BytesParser(policy=policy.default).parsebytes(message_bytes)

    from_header = (message.get("From") or "").lower()
    if settings.KWORK_EMAIL_FROM.strip() and settings.KWORK_EMAIL_FROM.lower() not in from_header:
        return []

    subject = (message.get("Subject") or "").strip()
    if settings.KWORK_EMAIL_SUBJECT_HINT.strip():
        hint = settings.KWORK_EMAIL_SUBJECT_HINT.lower().strip()
        if hint not in subject.lower():
            return []

    text_parts: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                text_parts.append(part.get_content())
            elif content_type == "text/html":
                html_parts.append(part.get_content())
    else:
        payload = message.get_content()
        if message.get_content_type() == "text/html":
            html_parts.append(payload)
        else:
            text_parts.append(payload)

    plain = " ".join(p.strip() for p in text_parts if p and p.strip())
    html_raw = [p for p in html_parts if p and p.strip()]
    if not plain and not html_raw and not subject:
        return []

    message_id = (message.get("Message-ID") or "").strip("<> ")
    if not message_id:
        date_raw = message.get("Date") or ""
        digest = hashlib.sha256(f"{subject}|{plain[:400]}|{date_raw}".encode("utf-8")).hexdigest()
        message_id = f"hash:{digest[:24]}"

    title_prefix = subject if subject else "Kwork email notification"
    date_header = message.get("Date")
    if date_header:
        with_date = parsedate_to_datetime(date_header)
        title_prefix = f"{title_prefix} [{with_date:%Y-%m-%d %H:%M}]"

    cards = _extract_project_cards(
        message_id=message_id,
        subject=title_prefix,
        html_parts=html_raw,
        text_parts=[plain] if plain else [],
    )
    return cards


def _fetch_kwork_orders_sync() -> list[OrderCard]:
    settings = get_settings()
    if not settings.ENABLE_KWORK_IMAP:
        return []
    if not settings.imap_ready:
        logger.info("Kwork IMAP not configured, skipping")
        return []

    mail = imaplib.IMAP4_SSL(settings.IMAP_HOST.strip(), settings.IMAP_PORT)
    try:
        mail.login(settings.IMAP_USERNAME.strip(), settings.IMAP_APP_PASSWORD.strip())
        mail.select(settings.IMAP_FOLDER.strip() or "INBOX")
        typ, data = mail.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return []

        results: list[OrderCard] = []
        for msg_num in data[0].split():
            typ_fetch, fetched = mail.fetch(msg_num, "(RFC822)")
            if typ_fetch != "OK" or not fetched:
                continue
            payload = fetched[0][1] if isinstance(fetched[0], tuple) and len(fetched[0]) > 1 else None
            if not payload:
                continue
            cards = _message_to_orders(payload)
            results.extend(cards)
        return results
    finally:
        try:
            mail.logout()
        except Exception:
            pass


async def fetch_kwork_orders_from_imap() -> list[OrderCard]:
    try:
        return await asyncio.to_thread(_fetch_kwork_orders_sync)
    except Exception as error:
        logger.warning("Kwork IMAP fetch failed, fallback to other sources: %s", error)
        return []


async def mark_latest_kwork_mail_unseen() -> bool:
    settings = get_settings()
    if not settings.ENABLE_KWORK_IMAP or not settings.imap_ready:
        return False

    def _mark_unseen() -> bool:
        mail = imaplib.IMAP4_SSL(settings.IMAP_HOST.strip(), settings.IMAP_PORT)
        try:
            mail.login(settings.IMAP_USERNAME.strip(), settings.IMAP_APP_PASSWORD.strip())
            mail.select(settings.IMAP_FOLDER.strip() or "INBOX")
            search_from = settings.KWORK_EMAIL_FROM.strip()
            if search_from:
                typ, data = mail.search(None, "FROM", f'"{search_from}"')
            else:
                typ, data = mail.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                return False
            latest = data[0].split()[-1]
            typ_flags, _ = mail.store(latest, "-FLAGS", "\\Seen")
            return typ_flags == "OK"
        finally:
            try:
                mail.logout()
            except Exception:
                pass

    try:
        return await asyncio.to_thread(_mark_unseen)
    except Exception:
        return False
