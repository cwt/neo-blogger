"""Tests for hashing, sessions, and CSRF primitives (tech-req §8)."""

from neoblogger.app.security.csrf import new_csrf_token, tokens_match
from neoblogger.app.security.hashing import (
    hash_secret,
    normalize_answer,
    verify_secret,
)
from neoblogger.app.security.sessions import (
    SESSION_LIFETIME_SECONDS,
    SessionCodec,
    SessionData,
)


def test_hash_and_verify_roundtrip() -> None:
    secret_hash = hash_secret("correct horse battery staple")
    assert secret_hash.startswith("$argon2id$")
    assert verify_secret("correct horse battery staple", secret_hash) is True


def test_verify_rejects_wrong_secret() -> None:
    secret_hash = hash_secret("right")
    assert verify_secret("wrong", secret_hash) is False


def test_verify_rejects_malformed_hash() -> None:
    assert verify_secret("anything", "not-a-hash") is False


def test_hashes_are_salted() -> None:
    assert hash_secret("same") != hash_secret("same")


def test_security_answer_normalized() -> None:
    answer_hash = hash_secret(normalize_answer("  Snowball II "))
    assert verify_secret(normalize_answer("snowball ii"), answer_hash) is True
    assert verify_secret("Snowball II", answer_hash) is False


def test_session_roundtrip() -> None:
    codec = SessionCodec("secret-key-for-tests-0123456789abcdef")
    cookie = codec.dump(SessionData(member_id="abc123", csrf_token="tok"))
    session = codec.load(cookie)
    assert session is not None
    assert session.member_id == "abc123"
    assert session.csrf_token == "tok"


def test_session_rejects_tampered_cookie() -> None:
    codec = SessionCodec("secret-key-for-tests-0123456789abcdef")
    cookie = codec.dump(SessionData(member_id="abc123", csrf_token="tok"))
    tampered = cookie[:-4] + "AAAA"
    assert codec.load(tampered) is None


def test_session_rejects_expired_cookie() -> None:
    codec = SessionCodec("secret-key-for-tests-0123456789abcdef")
    cookie = codec.dump(SessionData(member_id="abc123", csrf_token="tok"))
    # itsdangerous compares age > max_age; a fresh cookie has age 0, so a
    # negative max-age deterministically forces expiry.
    assert codec.load(cookie, max_age=-1) is None


def test_session_rejects_garbage() -> None:
    codec = SessionCodec("secret-key-for-tests-0123456789abcdef")
    assert codec.load("garbage") is None


def test_session_rejects_wrong_payload_shape() -> None:
    codec = SessionCodec("secret-key-for-tests-0123456789abcdef")
    forged = codec._serializer.dumps({"member_id": "abc123"})
    assert codec.load(str(forged)) is None


def test_session_lifetime_is_24_hours() -> None:
    assert SESSION_LIFETIME_SECONDS == 86_400


def test_csrf_tokens() -> None:
    first = new_csrf_token()
    second = new_csrf_token()
    assert first != second
    assert tokens_match(first, first) is True
    assert tokens_match(first, second) is False
    assert tokens_match("", first) is False
