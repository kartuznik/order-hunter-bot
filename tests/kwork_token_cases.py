from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.database import SeenStorage
from bot.kwork_api import (
    KworkRejected,
    cards_from_payload,
    project_link,
)


def main() -> None:
    cards = cards_from_payload(
        {
            "success": True,
            "response": [
                {"id": 15, "title": "Бот", "description": "текст", "price": 2500},
                {"id": True, "title": "skip"},
            ],
        }
    )
    assert len(cards) == 1
    assert cards[0].source == "kwork_api"
    assert cards[0].external_id == "15"
    assert cards[0].link == project_link(15) == "https://kwork.ru/projects/15"
    assert cards[0].price == "2500"

    try:
        cards_from_payload({"success": False, "error_code": 118})
    except KworkRejected as error:
        assert error.kind == "auth"
    else:
        raise AssertionError("auth payload must be rejected")

    try:
        cards_from_payload({"success": True, "response": {"id": 1}})
    except KworkRejected as error:
        assert error.kind == "shape"
    else:
        raise AssertionError("object response must be rejected")

    with tempfile.TemporaryDirectory() as folder:
        storage = SeenStorage(Path(folder) / "probe.db")
        assert storage.get_notice("projects_auth") is None
        storage.set_notice("projects_auth", "sent")
        assert storage.get_notice("projects_auth") == "sent"
        storage.clear_notice("projects_auth")
        assert storage.get_notice("projects_auth") is None

    print("KWORK_TOKEN_CASES_OK")


if __name__ == "__main__":
    main()
