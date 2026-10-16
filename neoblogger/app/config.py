"""TOML configuration loading with documented defaults (tech-req §14).

Every omitted key degrades to its documented default, so missing values
never crash boot (§18); a missing or unreadable file is a fault instead.
Load failures and unsafe boot configurations are deliberately distinct
policies, documented on :class:`ConfigurationError`.
"""

import os
import tomllib
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

__all__ = [
    "ApplicationConfig",
    "CacheConfig",
    "ConfigurationError",
    "DatabaseConfig",
    "PostsConfig",
    "ProxyConfig",
    "RuntimeConfig",
    "UploadConfig",
    "load_config",
]


class ConfigurationError(Exception):
    """Raised when booting with the resolved configuration would be unsafe.

    The message distinguishes two deliberate policies (tech-req §14, §3.4):

    - ``Fault``: the file cannot be read or parsed, or it contains unknown
      keys that cannot form the documented shape. Booting cannot proceed
      because proceeding would mean guessing what the file meant. Raised on
      precise load and structure errors only; deliberately not a boot
      strategy on otherwise well-formed files.
    - ``MissingProductionSecret``: the configuration is structurally usable,
      but the production flag is set without a strong secret key (§15.9).
    """

    def __init__(self, message: str, *, fault: bool) -> None:
        super().__init__(message)
        self.is_fault = fault

    @classmethod
    def fault(cls, message: str) -> ConfigurationError:
        return cls(message, fault=True)

    @classmethod
    def missing_production_secret(cls, message: str) -> ConfigurationError:
        return cls(message, fault=False)


class _ScalarSection(BaseModel):
    """Base for flat key-value configuration sections.

    Extra keys are rejected: the file is user input at the boundary, and a
    stray key would make the resolution look like a passing boot while the
    deployment is a mis-configuration. Wrong-typed scalar values degrade:
    the field keeps its documented default instead of crashing boot (§18).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    @classmethod
    def coerce(cls, raw: dict[str, Any], section_name: str) -> Self:
        """Validate ``raw``, degrading wrong-typed fields to defaults."""
        unknown = sorted(set(raw) - set(cls.model_fields))
        if unknown:
            raise ConfigurationError.fault(
                f"[{section_name}] unrecognized key(s): {', '.join(unknown)}"
            )
        try:
            return cls.model_validate(raw)
        except ValidationError:
            pass
        resolved: dict[str, Any] = cls().model_dump()
        for key, value in raw.items():
            field = cls.model_fields[key]
            adapter: TypeAdapter[Any] = TypeAdapter(field.rebuild_annotation())
            try:
                adapter.validate_python(value, strict=True)
            except ValidationError:
                continue
            resolved[key] = value
        return cls.model_validate(resolved)


class CacheConfig(_ScalarSection):
    """Response-cache settings (``[caching]``)."""

    enabled: bool = False
    timeout_seconds: int = Field(default=300, ge=1)
    storage: Literal["memory", "file"] = "memory"
    directory: str = "cache"
    max_size_mb: int = Field(default=100, ge=1)


class PostsConfig(_ScalarSection):
    """Feed pagination settings (``[posts]``)."""

    per_page: int = Field(default=10, ge=1)
    max_per_page: int = Field(default=50, ge=1)


class UploadConfig(_ScalarSection):
    """Upload settings (``[uploads]``)."""

    max_body_bytes: int = Field(default=16_777_216, ge=1)


class ProxyConfig(_ScalarSection):
    """Reverse-proxy trust settings (``[proxy]``, spec §15.8)."""

    trusted_proxies: list[str] = ["127.0.0.1", "::1"]


class DatabaseConfig(_ScalarSection):
    """Engine settings (``[database]``)."""

    path: str = "neo-blogger.db"
    tokenizer: str = ""
    tokenizer_library: str = ""


class ApplicationConfig(_ScalarSection):
    """Core application settings (``[application]``)."""

    secret_key: str = ""
    bind: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    site_title: str = "Neo-Blogger"
    site_author: str = ""
    site_description: str = ""
    base_url: str = ""
    https: bool = False


class RuntimeConfig(BaseModel):
    """Effective configuration: every omitted key holds its default."""

    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    caching: CacheConfig = Field(default_factory=CacheConfig)
    posts: PostsConfig = Field(default_factory=PostsConfig)
    uploads: UploadConfig = Field(default_factory=UploadConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)


def _read_toml(config_path: str) -> dict[str, Any]:
    """Read and parse a TOML file, translating load errors to faults."""
    try:
        with Path(config_path).open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigurationError.fault(
            f"Configuration file not found: {config_path}"
        ) from error
    except (tomllib.TOMLDecodeError, OSError) as error:
        raise ConfigurationError.fault(f"Configuration file error: {error}") from error


def _validate_document(document: dict[str, Any]) -> dict[str, Any]:
    """Check top-level keys and collect the six documented sections."""
    unknown = sorted(set(document) - set(RuntimeConfig.model_fields))
    if unknown:
        raise ConfigurationError.fault("unrecognized section(s): " + ", ".join(unknown))
    sections: dict[str, Any] = {}
    for name, section_type in (
        ("application", ApplicationConfig),
        ("database", DatabaseConfig),
        ("caching", CacheConfig),
        ("posts", PostsConfig),
        ("uploads", UploadConfig),
        ("proxy", ProxyConfig),
    ):
        raw = document.get(name, {})
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ConfigurationError.fault(
                f"[{name}] must be a TOML table of key-value pairs"
            )
        sections[name] = section_type.coerce(raw, name)
    return sections


def _production_gate(config: RuntimeConfig) -> None:
    """Refuse to boot production without a strong secret key (§15.9)."""
    secret = config.application.secret_key.strip()
    if config.application.https:
        if not secret:
            raise ConfigurationError.missing_production_secret(
                "secret_key is required when https = true"
            )
        if len(secret) < 32:
            raise ConfigurationError.missing_production_secret(
                "secret_key must be at least 32 characters when https = true"
            )


def load_config(config_path: str | None = None) -> RuntimeConfig:
    """Resolve the effective configuration, then enforce boot gates.

    The path resolution order is: explicit argument, then the
    ``NEOBLOGGER_CONFIG`` environment variable, then the default file name.
    """
    path = config_path or os.environ.get("NEOBLOGGER_CONFIG") or "neo-blogger.toml"
    document = _read_toml(path)
    sections = _validate_document(document)
    runtime = RuntimeConfig.model_validate(sections)
    _production_gate(runtime)
    return runtime
