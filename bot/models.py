from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OrderCard:
    source: str
    external_id: str
    title: str
    link: str
    description: str
    price: str
