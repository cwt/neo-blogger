"""Argon2id hashing for passwords and security answers (spec §15.1, §8).

Parameters are the argon2-cffi defaults (recorded inside the hash string
itself); plaintext secrets are never stored or logged.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

__all__ = ["hash_secret", "normalize_answer", "verify_secret"]

_hasher = PasswordHasher()


def hash_secret(secret: str) -> str:
    """Hash a secret with Argon2id."""
    return _hasher.hash(secret)


def verify_secret(stored_hash: str, secret: str) -> bool:
    """Verify a secret against a stored hash; any failure is plain ``False``.

    Argument order matches the underlying library: stored hash first.
    """
    try:
        return _hasher.verify(stored_hash, secret)
    except VerifyMismatchError, VerificationError, InvalidHashError:
        return False


def normalize_answer(answer: str) -> str:
    """Normalize a security answer: trimmed and lowercased (spec §4.1)."""
    return answer.strip().lower()
