"""Token-only schema probe. Does not call signIn."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from time import time
from typing import Any

import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024


def _schema(value: Any) -> Any:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        if not value:
            return "list[empty]"
        if all(isinstance(item, dict) for item in value):
            merged: dict[str, str] = {}
            for item in value:
                for key, item_value in item.items():
                    kind = _schema(item_value) if not isinstance(item_value, (dict, list)) else type(item_value).__name__
                    previous = merged.get(key)
                    if previous is None:
                        merged[key] = str(kind)
                    elif kind not in previous.split("|"):
                        merged[key] = f"{previous}|{kind}"
            return {"list": merged, "len": len(value)}
        return {"list": _schema(value[0]), "len": len(value)}
    if isinstance(value, dict):
        return {str(key): _schema(item) for key, item in value.items()}
    return type(value).__name__


async def main() -> None:
    load_dotenv(ROOT / ".env")
    token = os.environ.get("KWORK_TOKEN", "").strip()
    if not token:
        print(
            "PROBE_STOP no_token. Обнови его командой signIn с домашней машины, это займёт две минуты."
        )
        raise SystemExit(2)
    timeout = aiohttp.ClientTimeout(total=45)
    headers = {
        "Authorization": aiohttp.encode_basic_auth("mobile_api", "qFvfRl7w"),
        "User-Agent": "kwork-parser/0.1",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://api.kwork.ru/projects",
            params={"token": token, "categories": "all", "page": "1"},
            headers=headers,
        ) as response:
            body = await response.content.read(MAX_BYTES + 1)
            status = response.status
            content_type = response.headers.get("Content-Type", "")
    if len(body) > MAX_BYTES or status in {401, 403} or body.lstrip().startswith(b"<"):
        print(f"PROBE_STOP http={status} bytes={len(body)}")
        raise SystemExit(2)
    if "html" in content_type.lower():
        print(f"PROBE_STOP html http={status}")
        raise SystemExit(2)
    payload = json.loads(body.decode("utf-8"))
    if token in json.dumps(payload, ensure_ascii=False):
        print("PROBE_STOP response_contains_token")
        raise SystemExit(2)
    print(f"PROJECTS_OK http={status} bytes={len(body)}")
    print("PROJECTS_SCHEMA " + json.dumps(_schema(payload), ensure_ascii=False, sort_keys=True))
    projects = payload.get("response") if isinstance(payload, dict) else None
    if isinstance(projects, list) and projects and isinstance(projects[0], dict):
        now = time()
        for key in ("date_confirm", "time_left"):
            value = projects[0].get(key)
            print(f"{key.upper()} sample_type={type(value).__name__} now={int(now)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception as error:
        print(f"PROBE_STOP crash {type(error).__name__}", file=sys.stderr)
        raise SystemExit(2) from None
