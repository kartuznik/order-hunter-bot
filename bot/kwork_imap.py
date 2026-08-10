from __future__ import annotations

import asyncio
import hashlib
import imaplib
import logging
import re
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html import unescape

from bot.config import get_settings
from bot.models import OrderCard

logger = logging.getLogger("order_hunter.kwork_imap")

TAG_RE = re.compile(r"<[^>]+>")
PROJECT_LINK_RE = re.compile(r"https://kwork\.ru/projects/\d+[^\s\"'<)]*", re.IGNORECASE)
PRICE_RE = re.compile(r"(?:Бюджет|budget|цена)\s*[:\-]?\s*([0-9\s.,]+(?:₽|руб|rub)?)", re.IGNORECASE)


def _strip_html(value: str) -> str:
    return " ".join(unescape(TAG_RE.sub(" ", value)).split())


def _message_to_order(message_bytes: bytes) -> OrderCard | None:
    settings = get_settings()
    message = BytesParser(policy=policy.default).parsebytes(message_bytes)

    from_header = (message.get("From") or "").lower()
    if settings.KWORK_EMAIL_FROM.strip() and settings.KWORK_EMAIL_FROM.lower() not in from_header:
        return None

    subject = (message.get("Subject") or "").strip()
    if settings.KWORK_EMAIL_SUBJECT_HINT.strip():
        hint = settings.KWORK_EMAIL_SUBJECT_HINT.lower().strip()
        if hint not in subject.lower():
            return None

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
    html_text = " ".join(_strip_html(p) for p in html_parts if p and p.strip())
    body = " ".join(x for x in [plain, html_text] if x).strip()
    if not body and not subject:
        return None

    link_match = PROJECT_LINK_RE.search(" ".join(html_parts + text_parts))
    link = link_match.group(0) if link_match else ""
    price_match = PRICE_RE.search(body) or PRICE_RE.search(subject)
    price = price_match.group(1).strip() if price_match else "-"

    message_id = (message.get("Message-ID") or "").strip("<> ")
    if not message_id:
        date_raw = message.get("Date") or ""
        digest = hashlib.sha256(f"{subject}|{body[:400]}|{date_raw}".encode("utf-8")).hexdigest()
        message_id = f"hash:{digest[:24]}"

    title = subject if subject else "Kwork email notification"
    if not link:
        link = "https://kwork.ru/projects"

    date_header = message.get("Date")
    if date_header:
        with_date = parsedate_to_datetime(date_header)
        title = f"{title} [{with_date:%Y-%m-%d %H:%M}]"

    return OrderCard(
        source="kwork_imap",
        external_id=message_id,
        title=title,
        link=link,
        description=body[:1200],
        price=price,
    )


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
            card = _message_to_order(payload)
            if card is not None:
                results.append(card)
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
