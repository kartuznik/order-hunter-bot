from __future__ import annotations

import imaplib
import socket
import ssl
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.config import get_settings


def main() -> None:
    settings = get_settings()

    try:
        client = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        try:
            client.login(settings.IMAP_USERNAME, settings.IMAP_APP_PASSWORD)
        finally:
            try:
                client.logout()
            except Exception:
                pass
        print("IMAP_PROBE_OK")
    except imaplib.IMAP4.error:
        print("IMAP_PROBE_FAIL auth")
    except (socket.gaierror, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError, OSError):
        print("IMAP_PROBE_FAIL connect")
    except Exception:
        print("IMAP_PROBE_FAIL other")


if __name__ == "__main__":
    main()
