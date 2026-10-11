"""Proxy trust: forwarded headers accepted from the adjacent hop only
(spec §15.8, tech-req §4).

Rate-limit keys and canonical URLs use the reconstructed client
address/scheme; untrusted peers never influence them.
"""

from dataclasses import dataclass

__all__ = [
    "ProxyTrust",
    "forwarded_base",
    "forwarded_client",
    "forwarded_host",
    "forwarded_scheme",
]

_DEFAULT_TRUSTED = ("127.0.0.1", "::1")


@dataclass(frozen=True, slots=True)
class ProxyTrust:
    """The allowlist of proxies whose forwarded headers may be trusted."""

    trusted_proxies: tuple[str, ...] = _DEFAULT_TRUSTED

    def trusts(self, peer: str) -> bool:
        """Whether the adjacent hop is a trusted proxy."""
        return peer in self.trusted_proxies


def forwarded_client(peer: str, forwarded_for: str | None, trust: ProxyTrust) -> str:
    """The client address for rate-limit keys.

    Only a trusted adjacent hop's ``X-Forwarded-For`` is honored, and only
    its last entry — the address the adjacent hop itself observed — never a
    client-supplied chain prefix.
    """
    if forwarded_for and trust.trusts(peer):
        entries = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
        if entries:
            return entries[-1]
    return peer


def forwarded_scheme(
    peer: str, request_scheme: str, forwarded_proto: str | None, trust: ProxyTrust
) -> str:
    """The URL scheme for canonical URLs, honoring a trusted proxy only."""
    if forwarded_proto and trust.trusts(peer):
        candidate = forwarded_proto.strip().lower()
        if candidate in ("http", "https"):
            return candidate
    return request_scheme


def forwarded_host(
    peer: str, request_host: str, forwarded_host_header: str | None, trust: ProxyTrust
) -> str:
    """The host for canonical URLs, honoring a trusted proxy only."""
    if forwarded_host_header and trust.trusts(peer):
        candidate = forwarded_host_header.strip()
        if candidate:
            return candidate
    return request_host


def forwarded_base(
    peer: str,
    scheme: str,
    host: str,
    forwarded_proto: str | None,
    forwarded_host_header: str | None,
    url_root: str,
    trust: ProxyTrust,
) -> str:
    """The fallback base URL for canonical links and sitemaps.

    A trusted adjacent hop's forwarded scheme/host win; otherwise the
    request's own URL root is used, so direct deployments are unaffected.
    """
    if trust.trusts(peer) and (forwarded_proto or forwarded_host_header):
        scheme = forwarded_scheme(peer, scheme, forwarded_proto, trust)
        host = forwarded_host(peer, host, forwarded_host_header, trust)
        return f"{scheme}://{host}"
    return url_root.rstrip("/")
