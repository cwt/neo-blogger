"""Signed-cookie sessions (spec §4.3, tech-req §8, Appendix B D4).

The cookie payload identifies the member by stable internal ID; the server
re-resolves the member from storage on every request, so no server-side
session store exists. Lifetime is 24 hours, sliding: the cookie is
re-signed on every authenticated response.
"""

from dataclasses import dataclass

from itsdangerous import BadData, URLSafeTimedSerializer

__all__ = ["SESSION_LIFETIME_SECONDS", "SessionCodec", "SessionData"]

SESSION_LIFETIME_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class SessionData:
    """The authenticated identity carried by the session cookie."""

    member_id: str
    csrf_token: str
    session_version: int = 1


class SessionCodec:
    """Signs and validates session cookies via itsdangerous."""

    def __init__(self, secret_key: str) -> None:
        self._serializer = URLSafeTimedSerializer(
            secret_key, salt="neoblogger.session.v1"
        )

    def dump(self, session: SessionData) -> str:
        """Serialize and sign a session payload."""
        return str(
            self._serializer.dumps(
                {
                    "member_id": session.member_id,
                    "csrf_token": session.csrf_token,
                    "session_version": session.session_version,
                }
            )
        )

    def load(self, cookie: str, *, max_age: float | None = None) -> SessionData | None:
        """Validate a session cookie; ``None`` for any invalid or stale input."""
        lifetime: int | None = (
            SESSION_LIFETIME_SECONDS if max_age is None else int(max_age)
        )
        try:
            payload = self._serializer.loads(cookie, max_age=lifetime)
        except BadData:
            return None
        match payload:
            case {"member_id": str() as member_id, "csrf_token": str() as token}:
                raw_version = payload.get("session_version", 1)
                try:
                    version = int(raw_version)
                except TypeError, ValueError:
                    version = 1
                return SessionData(
                    member_id=member_id,
                    csrf_token=token,
                    session_version=version,
                )
            case _:
                return None
