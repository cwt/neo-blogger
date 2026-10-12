"""Security response headers, set on every response (spec §15.4, tech-req §12)."""

__all__ = ["security_headers"]


def security_headers(*, https: bool, nonce: str | None = None) -> dict[str, str]:
    """The header table for every response; HSTS only in production."""
    script_src = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
    csp = (
        f"default-src 'self'; script-src {script_src}; style-src 'self'; "
        "img-src 'self' data: blob: https:; object-src 'none'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    headers: dict[str, str] = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if https:
        headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
    return headers
