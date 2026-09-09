"""Token and pairing-code primitives.

Two different hashing strategies, on purpose:

* **Device tokens** are 256-bit random secrets. Brute force is infeasible, so
  a fast SHA-256 digest is used - this keeps per-request auth cheap enough for
  the phone to poll.
* **Pairing codes** are short and human-typable, therefore low entropy. They
  get Argon2id, a short TTL and an attempt counter.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_ph = PasswordHasher()

# Ambiguous characters (0/O, 1/I/L) removed so the code is easy to read off a
# screen and type on a phone.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TOKEN_PREFIX = "lkc"


def new_device_id() -> str:
    return uuid.uuid4().hex


def generate_pairing_code(length: int = 8) -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_pairing_code(code: str) -> str:
    return code.strip().upper().replace(" ", "").replace("-", "")


def hash_pairing_code(code: str) -> str:
    return _ph.hash(normalize_pairing_code(code))


def verify_pairing_code(code: str, code_hash: str) -> bool:
    try:
        return _ph.verify(code_hash, normalize_pairing_code(code))
    except (VerifyMismatchError, VerificationError):
        return False


def generate_device_token(device_id: str, nbytes: int = 32) -> tuple[str, str]:
    """Return ``(token, token_hash)``.

    The token is handed to the device exactly once and never stored in full.
    Its embedded device id lets the server look the record up in O(1).
    """
    secret = secrets.token_urlsafe(nbytes)
    token = f"{TOKEN_PREFIX}_{device_id}_{secret}"
    return token, hash_token_secret(secret)


def hash_token_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def parse_token(token: str) -> tuple[str, str] | None:
    """Split ``lkc_<device_id>_<secret>`` into ``(device_id, secret)``."""
    if not token or not token.startswith(f"{TOKEN_PREFIX}_"):
        return None
    parts = token.split("_", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def verify_token_secret(secret: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_token_secret(secret), expected_hash)
