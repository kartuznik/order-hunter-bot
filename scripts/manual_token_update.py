"""Write a hand-supplied Kwork token into .env and restart the bot. Does not call signIn."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.database import SeenStorage
from bot.kwork_token import apply_token_to_env, clear_token_notices, validate_token

SERVICE = "order-hunter-bot.service"
MOSCOW = ZoneInfo("Europe/Moscow")


def write_env_file(path: Path, text: str) -> None:
    mode = 0o600
    if path.exists():
        mode = path.stat().st_mode & 0o777
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def update_token_file(path: Path, token: str, updated_at: str) -> int:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    rewritten = apply_token_to_env(current, token, updated_at)
    write_env_file(path, rewritten)
    return len(validate_token(token))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install a Kwork token obtained on a home machine")
    parser.add_argument("token")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "order_hunter.db")
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args(argv)
    try:
        token = validate_token(args.token)
    except ValueError:
        print("token rejected", file=sys.stderr)
        return 2
    updated_at = datetime.now(MOSCOW).isoformat(timespec="seconds")
    length = update_token_file(args.env, token, updated_at)
    clear_token_notices(SeenStorage(args.db))
    print(f"updated KWORK_TOKEN length={length}")
    print(f"updated KWORK_TOKEN_UPDATED_AT={updated_at}")
    print("cleared notices projects_auth missing_token token_expiry")
    if args.no_restart:
        print("restart skipped")
        return 0
    subprocess.run(["systemctl", "restart", SERVICE], check=True)
    print(f"restart {SERVICE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
