#!/usr/bin/env python3
"""Generate a one-time pairing code for the Android app.

Run this on the laptop. The code is printed here (and as a QR code) and is
never served over the network, so nobody on the LAN can pair themselves.

    python scripts/pair.py
"""

from __future__ import annotations

import argparse
import socket
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.database.base import utcnow  # noqa: E402
from app.database.migrations import run_migrations  # noqa: E402
from app.database.models import PairingCode  # noqa: E402
from app.database.session import session_scope  # noqa: E402
from app.security.tokens import generate_pairing_code, hash_pairing_code  # noqa: E402


def local_ip() -> str:
    """Best-effort LAN address, so the phone knows where to point."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def print_qr(payload: str) -> None:
    try:
        import qrcode
    except ImportError:
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(payload)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an Android pairing code")
    parser.add_argument("--no-qr", action="store_true", help="Skip the QR code")
    parser.add_argument("--host", default=None, help="Override the advertised host")
    args = parser.parse_args()

    settings = get_settings()
    run_migrations()

    code = generate_pairing_code()
    expires = utcnow() + timedelta(seconds=settings.pairing_code_ttl_seconds)

    with session_scope() as db:
        db.add(PairingCode(code_hash=hash_pairing_code(code), expires_at=expires))

    host = args.host or local_ip()
    url = f"http://{host}:{settings.port}"
    minutes = settings.pairing_code_ttl_seconds // 60

    print()
    print("  Pair your phone")
    print("  ───────────────")
    print(f"  Backend URL : {url}")
    print(f"  Pairing code: {code}")
    print(f"  Valid for   : {minutes} minute(s)")
    print()
    print("  In the app: Settings -> Pair device, enter the URL and code.")
    print()

    if not args.no_qr:
        print_qr(f"{url}|{code}")
        print("  (Scan this in the app to fill both fields.)")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
