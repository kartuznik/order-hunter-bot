"""Kwork mobile project list. The token is supplied by hand. This module never calls signIn."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

import aiohttp

from bot.config import get_settings
from bot.database import SeenStorage
from bot.models import OrderCard
from bot.notifier import Notifier

logger = logging.getLogger("order_hunter.kwork_api")

API_PROJECTS = "https://api.kwork.ru/projects"
USER_AGENT = "kwork-parser/0.1"
MAX_BYTES = 2 * 1024 * 1024
POLL_BASE_SECONDS = 300
JITTER_MIN_SECONDS = 30
JITTER_MAX_SECONDS = 90
MISSING_TOKEN_HINT = (
    "Нет Kwork-токена. Обнови его командой signIn с домашней машины, это займёт две минуты."
)
TOKEN_STALE = (
    "Kwork-токен протух, обнови вручную с домашней машины (curl signIn) "
    "и положи новый KWORK_TOKEN в .env"
)
SHAPE_PROBLEM = "Kwork /projects вернул неожиданную форму ответа."
NOTICE_MISSING = "missing_token"
NOTICE_AUTH = "projects_auth"
NOTICE_SHAPE = "projects_shape"


class KworkRejected(Exception):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(kind)


def project_link(project_id: int) -> str:
    return f"https://kwork.ru/projects/{project_id}"


def next_wait_seconds() -> tuple[int, int]:
    jitter = random.randint(JITTER_MIN_SECONDS, JITTER_MAX_SECONDS)
    return POLL_BASE_SECONDS + jitter, jitter


def cards_from_payload(payload: dict[str, Any]) -> list[OrderCard]:
    if payload.get("success") is not True:
        raise KworkRejected("auth")
    response = payload.get("response")
    if not isinstance(response, list):
        raise KworkRejected("shape")
    cards: list[OrderCard] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        project_id = item.get("id")
        if not isinstance(project_id, int) or isinstance(project_id, bool):
            continue
        price = item.get("price")
        user_raw = item.get("user_id")
        user_id = user_raw if isinstance(user_raw, int) and not isinstance(user_raw, bool) else None
        cards.append(
            OrderCard(
                source="kwork_api",
                external_id=str(project_id),
                title=str(item.get("title") or "Kwork project"),
                link=project_link(project_id),
                description=str(item.get("description") or ""),
                price=str(price) if isinstance(price, int) and not isinstance(price, bool) else "-",
                user_id=user_id,
            )
        )
    return cards


async def _read_capped(response: aiohttp.ClientResponse) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(8192):
        total += len(chunk)
        if total > MAX_BYTES:
            raise KworkRejected("shape")
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_kwork_projects(token: str) -> list[OrderCard]:
    timeout = aiohttp.ClientTimeout(total=45)
    headers = {
        "Authorization": aiohttp.encode_basic_auth("mobile_api", "qFvfRl7w"),
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                API_PROJECTS,
                params={"token": token, "categories": "all", "page": "1"},
                headers=headers,
            ) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                body = await _read_capped(response)
    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        raise KworkRejected("transport") from error

    if status in {401, 403} or body.lstrip().startswith(b"<") or "html" in content_type.lower():
        logger.error("Kwork projects rejected http=%s html=%s", status, body.lstrip().startswith(b"<"))
        raise KworkRejected("auth")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KworkRejected("shape") from error
    if not isinstance(payload, dict):
        raise KworkRejected("shape")
    if payload.get("error_code") in {118, 401, 403} or payload.get("success") is not True:
        logger.error("Kwork projects rejected error_code=%s", payload.get("error_code"))
        raise KworkRejected("auth")
    return cards_from_payload(payload)


async def _alert_once(storage: SeenStorage, notifier: Notifier, key: str, text: str) -> None:
    if storage.get_notice(key) == "sent":
        return
    try:
        await notifier.send_owner_alert(text)
    except Exception as error:
        logger.error("Kwork alert failed kind=%s", type(error).__name__)
        return
    storage.set_notice(key, "sent")


async def run_kwork_loop(
    *,
    storage: SeenStorage,
    notifier: Notifier,
    stop_event: asyncio.Event,
    accept_cards,
) -> None:
    while not stop_event.is_set():
        try:
            await _kwork_tick(storage=storage, notifier=notifier, accept_cards=accept_cards)
        except Exception as error:
            logger.error("Kwork tick failed: %s", type(error).__name__)
        delay, jitter = next_wait_seconds()
        logger.info("Kwork next poll base=%s jitter=%s sleep=%s", POLL_BASE_SECONDS, jitter, delay)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            continue


async def _kwork_tick(*, storage: SeenStorage, notifier: Notifier, accept_cards) -> None:
    settings = get_settings()
    token = settings.kwork_token
    if not token:
        if storage.get_notice(NOTICE_MISSING) != "sent":
            logger.error(MISSING_TOKEN_HINT)
        await _alert_once(storage, notifier, NOTICE_MISSING, MISSING_TOKEN_HINT)
        return
    storage.clear_notice(NOTICE_MISSING)

    try:
        cards = await fetch_kwork_projects(token)
    except KworkRejected as error:
        logger.error("Kwork projects rejected kind=%s", error.kind)
        if error.kind == "auth":
            await _alert_once(storage, notifier, NOTICE_AUTH, TOKEN_STALE)
        elif error.kind == "shape":
            await _alert_once(storage, notifier, NOTICE_SHAPE, SHAPE_PROBLEM)
        return
    storage.clear_notice(NOTICE_AUTH)
    storage.clear_notice(NOTICE_SHAPE)
    logger.info("Kwork poll complete cards=%s", len(cards))
    await accept_cards(cards)
