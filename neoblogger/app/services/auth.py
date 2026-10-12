"""Auth pages: registration, sign-in, sign-out, recovery (spec §4)."""

from ..security.csrf import new_csrf_token
from ..security.sessions import SessionCodec, SessionData

__all__ = ["AuthError", "AuthService"]


class AuthError(Exception):
    """An authentication flow failure with a user-facing message."""


class AuthService:
    """Session-cookie issuance and validation around :class:`AccountService`."""

    def __init__(self, codec: SessionCodec) -> None:
        self._codec = codec

    def start_session(
        self, member_id: str, session_version: int = 1
    ) -> tuple[str, str]:
        """Create a session; returns (cookie value, csrf token)."""
        token = new_csrf_token()
        cookie = self._codec.dump(
            SessionData(
                member_id=member_id,
                csrf_token=token,
                session_version=session_version,
            )
        )
        return cookie, token

    def resolve(self, cookie: str | None) -> SessionData | None:
        """Resolve a session cookie; ``None`` when absent or invalid."""
        if not cookie:
            return None
        return self._codec.load(cookie)

    def refresh(self, session: SessionData) -> str:
        """Re-sign the payload for sliding expiry (spec §4.3)."""
        return self._codec.dump(session)
