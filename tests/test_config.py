"""Unit tests for TOML configuration loading (tech-req §14)."""

from pathlib import Path

import pytest

from neoblogger.app.config import ConfigurationError, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEOBLOGGER_CONFIG", raising=False)


def test_defaults_from_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text("# intentionally empty\n", encoding="utf-8")
    config = load_config(str(path))
    app = config.application
    assert app.secret_key == ""
    assert app.bind == "0.0.0.0"
    assert app.port == 8000
    assert app.https is False
    assert config.database.path == "neo-blogger.db"
    assert config.caching.enabled is False
    assert config.caching.timeout_seconds == 300
    assert config.posts.per_page == 10
    assert config.posts.max_per_page == 50
    assert config.uploads.max_body_bytes == 16_777_216
    assert config.proxy.trusted_proxies == ["127.0.0.1", "::1"]


def test_missing_file_is_a_fault(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_config(str(tmp_path / "missing.toml"))


def test_documented_keys_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text(
        "\n".join(
            [
                "[application]",
                'secret_key = "abcdefghijklmnopqrstuvwxyz012345"',
                "port = 9000",
                'site_title = "My Blog"',
                "https = true",
                "[database]",
                'path = "/var/lib/neoblogger/data.db"',
                "[caching]",
                "enabled = true",
                'storage = "file"',
                "max_size_mb = 25",
                "[posts]",
                "per_page = 20",
                "max_per_page = 60",
                "[uploads]",
                "max_body_bytes = 8388608",
                "[proxy]",
                'trusted_proxies = ["10.0.0.1"]',
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(str(path))
    assert config.application.secret_key == "abcdefghijklmnopqrstuvwxyz012345"
    assert config.application.port == 9000
    assert config.application.site_title == "My Blog"
    assert config.application.https is True
    assert config.database.path == "/var/lib/neoblogger/data.db"
    assert config.caching.enabled is True
    assert config.caching.storage == "file"
    assert config.caching.max_size_mb == 25
    assert config.posts.per_page == 20
    assert config.posts.max_per_page == 60
    assert config.uploads.max_body_bytes == 8388608
    assert config.proxy.trusted_proxies == ["10.0.0.1"]


def test_wrong_typed_value_degrades_to_default(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text(
        "[posts]\nper_page = {x = 1}\nmax_per_page = 25\n", encoding="utf-8"
    )
    config = load_config(str(path))
    assert config.posts.per_page == 10
    assert config.posts.max_per_page == 25


def test_unknown_top_level_section_is_a_fault(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text("[nonsense]\nkey = 1\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(str(path))


def test_unknown_section_key_is_a_fault(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text("[posts]\nbogus = 2\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(str(path))


def test_invalid_toml_is_a_fault(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text("[application\nbroken", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(str(path))


def test_production_refuses_missing_secret(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text("[application]\nhttps = true\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(str(path))


def test_production_refuses_weak_secret(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text(
        '[application]\nhttps = true\nsecret_key = "short"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigurationError):
        load_config(str(path))


def test_production_accepts_strong_secret(tmp_path: Path) -> None:
    path = tmp_path / "neo-blogger.toml"
    path.write_text(
        '[application]\nhttps = true\nsecret_key = "' + "a" * 32 + '"\n',
        encoding="utf-8",
    )
    config = load_config(str(path))
    assert config.application.https is True
