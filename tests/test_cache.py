"""Tests for the content-addressed cache."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.conftest import SENTINEL
from tomd import cache, config, core


class RecordingConverter:
    """Stand-in for MarkItDown that records every conversion it is asked for."""

    def __init__(self, markdown: str = "# converted by the stub\n") -> None:
        self.markdown = markdown
        self.calls: list[Path] = []

    def convert(self, source: Path) -> SimpleNamespace:
        """Record the call and hand back a MarkItDown-shaped result."""
        self.calls.append(source)
        return SimpleNamespace(markdown=self.markdown)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingConverter:
    """Replace the real MarkItDown instance with a recording stub."""
    stub = RecordingConverter()
    monkeypatch.setattr(core, "_converter", lambda _endpoint: stub)
    return stub


def test_identical_content_under_different_names_shares_one_entry(
    workdir: Path, recorder: RecordingConverter
) -> None:
    # Arrange
    first = workdir / "invoice.csv"
    second = workdir / "a-totally-different-name.csv"
    first.write_text("item,quantity\nwidget,3\n", encoding="utf-8")
    second.write_bytes(first.read_bytes())

    # Act
    core.convert(first)
    result = core.convert(second)

    # Assert
    assert result.cached is True
    assert len(recorder.calls) == 1
    assert cache.info().entries == 1


def test_editing_a_file_creates_a_second_entry(workdir: Path, recorder: RecordingConverter) -> None:
    # Arrange
    source = workdir / "notes.csv"
    source.write_text("item,quantity\nwidget,3\n", encoding="utf-8")
    core.convert(source)

    # Act
    source.write_text("item,quantity\nwidget,4\n", encoding="utf-8")
    result = core.convert(source)

    # Assert
    assert result.cached is False
    assert len(recorder.calls) == 2
    assert cache.info().entries == 2


def test_second_conversion_is_served_from_cache_without_calling_markitdown(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    first = core.convert(sample_pdf)
    assert first.cached is False

    def explode(_endpoint: str | None) -> Any:
        raise AssertionError("MarkItDown must not be invoked on a cache hit")

    monkeypatch.setattr(core, "_converter", explode)

    # Act
    second = core.convert(sample_pdf)

    # Assert
    assert second.cached is True
    assert SENTINEL in second.markdown


def test_no_cache_forces_a_fresh_conversion(workdir: Path, recorder: RecordingConverter) -> None:
    # Arrange
    source = workdir / "data.csv"
    source.write_text("item\nwidget\n", encoding="utf-8")
    core.convert(source)

    # Act
    result = core.convert(source, use_cache=False)

    # Assert
    assert result.cached is False
    assert len(recorder.calls) == 2


def test_no_cache_does_not_store_the_result(workdir: Path, recorder: RecordingConverter) -> None:
    # Arrange
    source = workdir / "data.csv"
    source.write_text("item\nwidget\n", encoding="utf-8")

    # Act
    core.convert(source, use_cache=False)

    # Assert
    assert cache.info().entries == 0
    assert len(recorder.calls) == 1


def test_clear_empties_the_cache_directory(sample_pdf: Path, isolated_cache: Path) -> None:
    # Arrange
    core.convert(sample_pdf)
    assert cache.info().entries == 1

    # Act
    removed = cache.clear()

    # Assert
    assert removed == 1
    assert cache.info().entries == 0
    assert list(isolated_cache.rglob("*")) == []


def test_clear_on_a_missing_cache_reports_nothing_removed() -> None:
    # Arrange / Act
    removed = cache.clear()

    # Assert
    assert removed == 0
    assert cache.info().entries == 0


def test_info_reports_entry_count_and_disk_size(sample_files: dict[str, Path]) -> None:
    # Arrange
    core.convert(sample_files["sample.csv"])
    core.convert(sample_files["sample.docx"])

    # Act
    summary = cache.info()

    # Assert
    assert summary.entries == 2
    assert summary.bytes > 0
    assert summary.path == config.cache_dir()


def test_file_digest_depends_on_content_not_on_name(workdir: Path) -> None:
    # Arrange
    first = workdir / "one.txt"
    second = workdir / "two.txt"
    third = workdir / "three.txt"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytes")
    third.write_bytes(b"other bytes")

    # Act
    digests = [cache.file_digest(p) for p in (first, second, third)]

    # Assert
    assert digests[0] == digests[1]
    assert digests[0] != digests[2]
    assert len(digests[0]) == 64


def test_store_writes_a_readable_meta_file(workdir: Path) -> None:
    # Arrange
    source = workdir / "thing.csv"
    source.write_text("item\nwidget\n", encoding="utf-8")
    digest = cache.file_digest(source)

    # Act
    entry = cache.store(digest, "# body\n", source=source)

    # Assert
    meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
    assert meta["digest"] == digest
    assert meta["source"] == str(source)
    assert meta["source_bytes"] == source.stat().st_size
    assert meta["markdown_chars"] == len("# body\n")


def test_load_treats_a_damaged_entry_as_a_miss(workdir: Path) -> None:
    # Arrange
    source = workdir / "thing.csv"
    source.write_text("item\nwidget\n", encoding="utf-8")
    digest = cache.file_digest(source)
    entry = cache.store(digest, "# body\n", source=source)
    (entry / "document.md").unlink()

    # Act
    loaded = cache.load(digest)

    # Assert
    assert loaded is None


def test_optional_backends_do_not_share_entries_with_offline_conversions(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, recorder: RecordingConverter
) -> None:
    # Arrange
    source = workdir / "scan.csv"
    source.write_text("item\nwidget\n", encoding="utf-8")
    monkeypatch.setenv("AZURE_DOCINTEL_ENDPOINT", "https://example.invalid")
    core.convert(source)

    # Act
    result = core.convert(source, docintel=True)

    # Assert
    assert result.cached is False
    assert len(recorder.calls) == 2
    assert cache.info().entries == 2


def test_cached_markdown_still_gets_fresh_front_matter(sample_pdf: Path) -> None:
    # Arrange
    core.convert(sample_pdf)

    # Act
    second = core.convert(sample_pdf, frontmatter=False)

    # Assert
    assert second.cached is True
    assert not second.markdown.startswith("---")
    assert SENTINEL in second.markdown
