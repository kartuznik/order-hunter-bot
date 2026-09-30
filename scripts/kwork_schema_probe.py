"""Schema probe for the unofficial Kwork mobile API.

Prints response keys and types only. Does not print login, password, token,
or project text. One signIn, then one /projects page. A parameter-error on
/projects may be repeated once as a form body, after another jitter.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from pathlib import Path
from time import time
from typing import Any

import aiohttp
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
API_BASE = "https://api.kwork.ru"
USER_AGENT = "kwork-parser/0.1"
MAX_BYTES = 2 * 1024 * 1024
BASIC_AUTHORIZATION = aiohttp.encode_basic_auth("mobile_api", "qFvfRl7w")


def _load_credentials() -> tuple[str, str]:
    load_dotenv(ROOT / ".env")
    login = os.environ.get("KWORK_LOGIN", "").strip()
    password = os.environ.get("KWORK_PASSWORD", "").strip()
    if not login or not password:
        print("PROBE_STOP credentials_missing")
        raise SystemExit(2)
    return login, password


def _schema(value: Any) -> Any:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        if not value:
            return {"list": "empty"}
        merged: dict[str, Any] = {}
        kinds: set[str] = set()
        uniform = True
        first = _schema(value[0])
        for item in value:
            item_schema = _schema(item)
            if item_schema != first:
                uniform = False
            if isinstance(item_schema, dict) and isinstance(first, dict):
                for key, kind in item_schema.items():
                    previous = merged.get(key)
                    if previous is None:
                        merged[key] = kind
                    elif previous != kind:
                        merged[key] = f"{previous}|{kind}"
            else:
                kinds.add(str(item_schema))
        if merged and uniform:
            return {"list": merged, "len": len(value)}
        if merged:
            return {"list": merged, "len": len(value), "mixed": True}
        return {"list": sorted(kinds) if not uniform else first, "len": len(value)}
    if isinstance(value, dict):
        return {str(key): _schema(item) for key, item in value.items()}
    return type(value).__name__


def _classify_time(values: list[int], now: float) -> str:
    if not values:
        return "absent"
    median = sorted(values)[len(values) // 2]
    if median > 10**11:
        unit = "unix_milliseconds"
        as_seconds = median / 1000.0
    elif median > 10**9:
        unit = "unix_seconds"
        as_seconds = float(median)
    else:
        return (
            f"not_unix magnitude={median} "
            f"min={min(values)} max={max(values)} now={int(now)}"
        )
    delta = int(as_seconds - now)
    return (
        f"{unit} count={len(values)} min={min(values)} max={max(values)} "
        f"median_minus_now_sec={delta}"
    )


def _collect_ints(items: list[Any], key: str) -> list[int]:
    found: list[int] = []
    for item in items:
        if not isinstance(item, dict) or key not in item:
            continue
        value = item[key]
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            found.append(value)
        elif isinstance(value, float) and value.is_integer():
            found.append(int(value))
    return found


async def _read_body(response: aiohttp.ClientResponse) -> tuple[int, str, bytes]:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(8192):
        total += len(chunk)
        if total > MAX_BYTES:
            print(f"PROBE_STOP response_cap endpoint_status={response.status}")
            raise SystemExit(2)
        chunks.append(chunk)
    body = b"".join(chunks)
    content_type = response.headers.get("Content-Type", "")
    return response.status, content_type, body


def _stop_http(label: str, status: int, content_type: str, body: bytes) -> None:
    stripped = body.lstrip()
    looks_html = stripped.startswith(b"<") or b"<html" in stripped[:200].lower()
    print(
        f"PROBE_STOP {label} http={status} content_type={content_type!r} "
        f"html={looks_html} bytes={len(body)}"
    )
    raise SystemExit(2)


def _parse_json(label: str, status: int, content_type: str, body: bytes) -> Any:
    if status in {401, 403}:
        _stop_http(label, status, content_type, body)
    stripped = body.lstrip()
    if stripped.startswith(b"<") or "html" in content_type.lower():
        _stop_http(label, status, content_type, body)
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        _stop_http(f"{label}_non_json", status, content_type, body)
    if not isinstance(parsed, dict):
        print(f"PROBE_STOP {label}_unexpected_type type={type(parsed).__name__}")
        raise SystemExit(2)
    return parsed


async def _post(
    session: aiohttp.ClientSession,
    endpoint: str,
    *,
    form: dict[str, str] | None,
    query: dict[str, str] | None,
) -> tuple[int, str, bytes]:
    try:
        async with session.post(
            f"{API_BASE}/{endpoint}",
            params=query,
            data=form,
            headers={
                "Authorization": BASIC_AUTHORIZATION,
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        ) as response:
            return await _read_body(response)
    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(f"PROBE_STOP transport endpoint={endpoint} error={type(error).__name__}")
        raise SystemExit(2) from error


async def _sleep_jitter() -> None:
    delay = random.randint(30, 90)
    print(f"JITTER_SEC {delay}")
    await asyncio.sleep(delay)


def _projects_from(payload: dict[str, Any]) -> list[Any] | None:
    response = payload.get("response")
    if isinstance(response, list):
        return response
    return None


async def main() -> None:
    login, password = _load_credentials()
    timeout = aiohttp.ClientTimeout(total=45)
    print(f"USER_AGENT {USER_AGENT}")
    async with aiohttp.ClientSession(timeout=timeout) as session:
        status, content_type, body = await _post(
            session,
            "signIn",
            form={"login": login, "password": password},
            query=None,
        )
        payload = _parse_json("signIn", status, content_type, body)
        error_code = payload.get("error_code")
        if error_code == 118:
            print("PROBE_STOP captcha_118")
            raise SystemExit(2)
        if payload.get("success") is not True:
            print(
                "PROBE_STOP signIn_not_success "
                f"http={status} error_code={error_code!r} "
                f"schema={_schema(payload)}"
            )
            raise SystemExit(2)
        response = payload.get("response")
        token = response.get("token") if isinstance(response, dict) else None
        if not isinstance(token, str) or not token:
            print(f"PROBE_STOP signIn_unexpected schema={_schema(payload)}")
            raise SystemExit(2)
        expired = response.get("expired") if isinstance(response, dict) else None
        print(f"SIGNIN_OK http={status} expired_type={type(expired).__name__}")
        print(f"SIGNIN_SCHEMA {_schema(payload)}")

        await _sleep_jitter()
        status, content_type, body = await _post(
            session,
            "projects",
            form=None,
            query={"token": token, "categories": "all", "page": "1"},
        )
        payload = _parse_json("projects", status, content_type, body)
        if payload.get("error_code") in {118, 401, 403}:
            print(f"PROBE_STOP projects_auth_or_captcha error_code={payload.get('error_code')!r}")
            raise SystemExit(2)
        projects = _projects_from(payload)
        if payload.get("success") is not True or projects is None:
            print(
                "PROJECTS_QUERY_REJECTED "
                f"http={status} error_code={payload.get('error_code')!r} "
                f"schema={_schema(payload)}"
            )
            await _sleep_jitter()
            status, content_type, body = await _post(
                session,
                "projects",
                form={"categories": "all", "page": "1"},
                query={"token": token},
            )
            payload = _parse_json("projects_form", status, content_type, body)
            projects = _projects_from(payload)
            if payload.get("success") is not True or projects is None:
                print(
                    "PROBE_STOP projects_unexpected "
                    f"http={status} error_code={payload.get('error_code')!r} "
                    f"schema={_schema(payload)}"
                )
                raise SystemExit(2)
            print("PROJECTS_VIA form_body")
        else:
            print("PROJECTS_VIA query")

        print(f"PROJECTS_OK http={status}")
        print(f"PROJECTS_SCHEMA {_schema(payload)}")
        now = time()
        print(f"NOW_EPOCH {int(now)}")
        print(f"DATE_CONFIRM {_classify_time(_collect_ints(projects, 'date_confirm'), now)}")
        print(f"TIME_LEFT {_classify_time(_collect_ints(projects, 'time_left'), now)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception as error:
        print(f"PROBE_STOP crash error={type(error).__name__}", file=sys.stderr)
        raise SystemExit(2) from None
