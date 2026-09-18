"""Tests for the settings layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from tomd import __version__, config


def test_cache_dir_defaults_to_xdg_style_home_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv(config.ENV_CACHE_DIR, raising=False)

    # Act
    result = config.cache_dir()

    # Assert
    assert result == Path.home() / ".cache" / "tomd"


def test_cache_dir_honours_environment_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setenv(config.ENV_CACHE_DIR, str(tmp_path / "elsewhere"))

    # Act
    result = config.cache_dir()

    # Assert
    assert result == tmp_path / "elsewhere"


def test_out_dir_is_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv(config.ENV_OUT_DIR, raising=False)

    # Act
    result = config.out_dir()

    # Assert
    assert result is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("9999", 9999), ("not-a-number", config.DEFAULT_PORT), ("", config.DEFAULT_PORT)],
)
def test_port_parses_environment_and_falls_back_on_garbage(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: int
) -> None:
    # Arrange
    monkeypatch.setenv(config.ENV_PORT, raw)

    # Act
    result = config.port()

    # Assert
    assert result == expected


def test_web_host_is_loopback_only() -> None:
    # Arrange / Act
    host = config.WEB_HOST

    # Assert
    assert host == "127.0.0.1"


def test_package_exposes_a_version_string() -> None:
    # Arrange / Act
    parts = __version__.split(".")

    # Assert
    assert len(parts) >= 3
    assert parts[0].isdigit()
