"""Per-session CSRF tokens (spec §15.2, tech-req §8).

Tokens are generated per session, rendered as a hidden input in every
mutating form and as a meta tag for client scripts; validation is a
constant-time comparison enforced on all POST/PUT/DELETE routes.
"""

import secrets

__all__ = ["new_csrf_token", "tokens_match"]


def new_csrf_token() -> str:
    """Generate a random CSRF token."""
    return secrets.token_urlsafe(32)


def tokens_match(candidate: str, expected: str) -> bool:
    """Constant-time token comparison; empty expectation never matches.

    Rejecting an empty ``expected`` closes the vacuous ``"" == ""`` pass
    that would otherwise let a token-less request through.
    """
    if not expected:
        return False
    return secrets.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
