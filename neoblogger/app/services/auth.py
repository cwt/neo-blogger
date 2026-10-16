"""Auth pages: registration, sign-in, sign-out, recovery (spec §4)."""

from ..security.csrf import new_csrf_token
from ..security.sessions import SessionCodec, SessionData

__all__ = ["AuthService"]


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

    def refresh(self, session: SessionData) -> str:
        """Re-sign the payload for sliding expiry (spec §4.3)."""
        return self._codec.dump(session)
