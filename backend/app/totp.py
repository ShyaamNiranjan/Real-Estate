"""Time-based one-time codes (RFC 6238, the 6-digit codes authenticator apps show) for staff.

Secrets are stored encrypted (AES-GCM, key derived from SECRET_KEY), so a database leak alone
doesn't give anyone a staff member's second factor."""

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

STEP = 30
DIGITS = 6
ISSUER = "Scrollwalk HQ"


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key() -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=b"staff-totp-secret").derive(
        get_settings().secret_key.encode())


def encrypt(secret: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_key()).encrypt(nonce, secret.encode(), b"totp")


def decrypt(blob: bytes) -> str:
    return AESGCM(_key()).decrypt(blob[:12], blob[12:], b"totp").decode()


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP)


def matching_step(secret: str, code: str, after_step: int, now: float | None = None) -> int | None:
    """The time step the code belongs to (allowing one step of clock drift either way), or None.
    Steps at or before `after_step` are refused, so a code can't be used twice."""
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in (step - 1, step, step + 1):
        if candidate > after_step and hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, email: str) -> str:
    """For the QR code the staff member scans into their authenticator app."""
    return (f"otpauth://totp/{quote(ISSUER)}:{quote(email)}?secret={secret}&issuer={quote(ISSUER)}"
            f"&digits={DIGITS}&period={STEP}")
