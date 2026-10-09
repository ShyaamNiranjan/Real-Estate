import hashlib
import hmac
import secrets
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

_hasher = PasswordHasher()
# Verified against when the account doesn't exist, so a wrong email costs the same time as a
# wrong password.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def keyed(purpose: str, value: str) -> str:
    """Server-keyed hash: stable for lookups (rate limits, IPs), useless without SECRET_KEY."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def code_hash(code_id: UUID, code: str) -> bytes:
    return bytes.fromhex(keyed("email-code", f"{code_id}:{code}"))


def csrf_token(session_id: UUID) -> str:
    return keyed("csrf", str(session_id))


def same(a: str | bytes, b: str | bytes) -> bool:
    return hmac.compare_digest(a, b)
