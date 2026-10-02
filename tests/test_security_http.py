"""Tests for headers, rate limiting, and proxy trust (tech-req §4, §12)."""

from neoblogger.app.security.headers import security_headers
from neoblogger.app.security.proxy import ProxyTrust, forwarded_client, forwarded_scheme
from neoblogger.app.security.ratelimit import FixedWindowRateLimiter


def fake_clock(values: list[float]):
    """A deterministic clock factory stepping through pre-set readings."""
    readings = iter(values)

    def read() -> float:
        return next(readings)

    return read


def test_headers_in_production() -> None:
    headers = security_headers(https=True)
    assert headers["Strict-Transport-Security"] == (
        "max-age=31536000; includeSubDomains; preload"
    )
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-XSS-Protection"] == "1; mode=block"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"


def test_headers_in_development_have_no_hsts() -> None:
    assert "Strict-Transport-Security" not in security_headers(https=False)


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = FixedWindowRateLimiter(max_attempts=3, window_seconds=60.0)
    assert limiter.allow("1.2.3.4", "a@x.io") is True
    assert limiter.allow("1.2.3.4", "a@x.io") is True
    assert limiter.allow("1.2.3.4", "a@x.io") is True
    assert limiter.allow("1.2.3.4", "a@x.io") is False


def test_rate_limiter_keys_are_independent() -> None:
    limiter = FixedWindowRateLimiter(max_attempts=1, window_seconds=60.0)
    assert limiter.allow("1.2.3.4", "a@x.io") is True
    assert limiter.allow("1.2.3.4", "b@x.io") is True
    assert limiter.allow("5.6.7.8", "a@x.io") is True
    assert limiter.allow("1.2.3.4", "a@x.io") is False


def test_rate_limiter_window_resets() -> None:
    clock = fake_clock([0.0, 1.0, 60.0, 60.0])
    limiter = FixedWindowRateLimiter(max_attempts=2, window_seconds=60.0, clock=clock)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True


def test_rate_limiter_sweeps_old_windows() -> None:
    clock = fake_clock([0.0, 0.0, 120.0])
    limiter = FixedWindowRateLimiter(max_attempts=1, window_seconds=60.0, clock=clock)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    assert limiter.allow("k") is True
    assert len(limiter._buckets) == 1


def test_proxy_client_trusted_hop() -> None:
    trust = ProxyTrust()
    client = forwarded_client("127.0.0.1", "203.0.113.7, 198.51.100.9", trust)
    assert client == "198.51.100.9"


def test_proxy_client_untrusted_hop_ignored() -> None:
    trust = ProxyTrust()
    assert forwarded_client("9.9.9.9", "203.0.113.7", trust) == "9.9.9.9"
    assert forwarded_client("127.0.0.1", None, trust) == "127.0.0.1"


def test_proxy_custom_trust_allowlist() -> None:
    trust = ProxyTrust(trusted_proxies=("10.0.0.1",))
    assert forwarded_client("10.0.0.1", "203.0.113.7", trust) == "203.0.113.7"


def test_proxy_scheme() -> None:
    trust = ProxyTrust()
    assert forwarded_scheme("127.0.0.1", "http", "https", trust) == "https"
    assert forwarded_scheme("127.0.0.1", "http", None, trust) == "http"
    assert forwarded_scheme("9.9.9.9", "http", "https", trust) == "http"
    assert forwarded_scheme("127.0.0.1", "http", "ftp", trust) == "http"
