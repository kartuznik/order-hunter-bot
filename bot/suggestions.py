"""Owner-confirmed filter proposals. Nothing here changes a threshold by itself."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from bot.config import BUDGET_DROP_RUB
from bot.database import SeenStorage
from bot.kwork_filter import content_stems, green_stems, red_stems

WINDOW = timedelta(days=30)
STACK_VOTES = 3
BUDGET_VOTES = 3
MIN_WORD = 4


def _stamp(now: datetime) -> str:
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="seconds")


def _payload(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def refresh_suggestions(storage: SeenStorage, *, now: datetime) -> list[dict]:
    since = _stamp(now - WINDOW)
    votes = storage.feedback_since(since)
    proposals = _budget_proposals(storage, votes) + _stack_proposals(votes)
    current = {(proposal["kind"], _payload(proposal["payload"])) for proposal in proposals}
    for row in storage.pending_suggestions():
        if (row["kind"], row["payload"]) not in current:
            storage.delete_pending(int(row["id"]))
    created: list[dict] = []
    for proposal in proposals:
        payload = _payload(proposal["payload"])
        if storage.find_suggestion(proposal["kind"], payload, "pending") is not None:
            continue
        if storage.find_suggestion(proposal["kind"], payload, "declined", since) is not None:
            continue
        if storage.find_suggestion(proposal["kind"], payload, "accepted") is not None:
            continue
        suggestion_id = storage.insert_suggestion(
            kind=proposal["kind"],
            payload=payload,
            created_at=_stamp(now),
        )
        created.append({"id": suggestion_id, "kind": proposal["kind"], "payload": proposal["payload"]})
    return created


def _budget_proposals(storage: SeenStorage, votes: list[dict]) -> list[dict]:
    current = storage.budget_override()
    floor = BUDGET_DROP_RUB if current is None else current
    lows = [
        vote
        for vote in votes
        if vote["verdict"] == "junk" and vote["reason"] == "budget" and vote["price_rub"] is not None
    ]
    orders = {vote["order_id"] for vote in lows}
    if len(orders) < BUDGET_VOTES:
        return []
    proposed = max(int(vote["price_rub"]) for vote in lows)
    if proposed <= floor:
        return []
    return [{"kind": "budget", "payload": {"value": proposed}}]


def _stack_proposals(votes: list[dict]) -> list[dict]:
    blocked = green_stems() | red_stems()
    junk = [vote for vote in votes if vote["verdict"] == "junk" and vote["reason"] == "stack"]
    relevant = [vote for vote in votes if vote["verdict"] == "relevant"]
    grouped: dict[str, set[str]] = {}
    for vote in junk:
        for stem in content_stems(f"{vote['title']}\n{vote['description']}"):
            if len(stem) < MIN_WORD or stem in blocked or stem.isdigit():
                continue
            grouped.setdefault(stem, set()).add(str(vote["order_id"]))
    proposals = []
    for stem, orders in sorted(grouped.items()):
        if len(orders) < STACK_VOTES:
            continue
        if any(stem in content_stems(f"{vote['title']}\n{vote['description']}") for vote in relevant):
            continue
        proposals.append({"kind": "red_word", "payload": {"word": stem}})
    return proposals


def apply_suggestion(storage: SeenStorage, suggestion_id: int, *, now: datetime) -> str:
    row = storage.suggestion(suggestion_id)
    if row is None or row["status"] != "pending":
        return "Предложение не найдено."
    payload = json.loads(row["payload"])
    stamp = _stamp(now)
    if row["kind"] == "budget":
        value = int(payload["value"])
        storage.set_budget_override(value, suggestion_id=suggestion_id, applied_at=stamp)
        storage.set_suggestion_status(suggestion_id, "accepted", stamp)
        return f"Применено: порог бюджета {value} ₽."
    if row["kind"] == "red_word":
        word = str(payload["word"])
        storage.add_dynamic_red(word, suggestion_id=suggestion_id, added_at=stamp)
        storage.set_suggestion_status(suggestion_id, "accepted", stamp)
        return f"Применено: в красный список добавлено «{word}»."
    return "Предложение не найдено."


def decline_suggestion(storage: SeenStorage, suggestion_id: int, *, now: datetime) -> str:
    row = storage.suggestion(suggestion_id)
    if row is None or row["status"] != "pending":
        return "Предложение не найдено."
    storage.set_suggestion_status(suggestion_id, "declined", _stamp(now))
    return "Предложение отклонено."


def suggestion_lines(storage: SeenStorage) -> list[tuple[int, str]]:
    current = storage.budget_override()
    floor = BUDGET_DROP_RUB if current is None else current
    lines = []
    for row in storage.pending_suggestions():
        payload = json.loads(row["payload"])
        if row["kind"] == "budget":
            text = (
                f"Предложение #{row['id']}: поднять порог бюджета до {payload['value']} ₽. "
                f"Сейчас {floor} ₽."
            )
        else:
            text = f"Предложение #{row['id']}: добавить в красный список слово «{payload['word']}»."
        lines.append((int(row["id"]), text))
    return lines
