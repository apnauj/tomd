"""Tests for the conversion layer."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tests.conftest import SENTINEL
from tomd import core


@pytest.mark.parametrize(
    "fixture_name",
    ["sample.pdf", "sample.docx", "sample.xlsx", "sample.csv"],
)
def test_convert_produces_markdown_containing_the_source_text(
    sample_files: dict[str, Path], fixture_name: str
) -> None:
    # Arrange
    source = sample_files[fixture_name]

    # Act
    result = core.convert(source)

    # Assert
    assert result.error is None
    assert SENTINEL in result.markdown
    assert result.words > 0
    assert result.out_path == source.with_suffix(".md")
    assert SENTINEL in source.with_suffix(".md").read_text(encoding="utf-8")


def test_convert_returns_error_result_when_file_is_corrupt(corrupt_pdf: Path) -> None:
    # Arrange
    destination = corrupt_pdf.with_suffix(".md")

    # Act
    result = core.convert(corrupt_pdf)

    # Assert
    assert result.error is not None
    assert result.markdown == ""
    assert result.out_path is None
    assert not destination.exists()


def test_convert_reports_missing_file_instead_of_raising(workdir: Path) -> None:
    # Arrange
    missing = workdir / "nope.pdf"

    # Act
    result = core.convert(missing)

    # Assert
    assert result.error is not None
    assert "no such file" in result.error
    assert result.ok is False


def test_convert_reports_a_directory_instead_of_raising(workdir: Path) -> None:
    # Arrange
    directory = workdir / "subdir"
    directory.mkdir()

    # Act
    result = core.convert(directory)

    # Assert
    assert result.error is not None
    assert "is a directory" in result.error


def test_convert_prepends_front_matter_with_the_expected_fields(sample_pdf: Path) -> None:
    # Arrange
    expected_size = sample_pdf.stat().st_size

    # Act
    result = core.convert(sample_pdf)

    # Assert
    header = result.markdown.split("---\n")[1]
    assert f'source: "{sample_pdf.resolve()}"' in header
    assert f"size_bytes: {expected_size}" in header
    assert "tool: tomd" in header
    assert "converted_at: 20" in header


def test_convert_omits_front_matter_when_asked(sample_pdf: Path) -> None:
    # Arrange / Act
    result = core.convert(sample_pdf, frontmatter=False)

    # Assert
    assert not result.markdown.startswith("---")
    assert "tool: tomd" not in result.markdown
    assert SENTINEL in result.markdown


def test_convert_counts_body_only_ignoring_front_matter(sample_csv_pair: tuple[Path, Path]) -> None:
    # Arrange
    with_header, without_header = sample_csv_pair

    # Act
    framed = core.convert(with_header)
    bare = core.convert(without_header, frontmatter=False)

    # Assert
    assert framed.chars == bare.chars
    assert framed.words == bare.words
    assert len(framed.markdown) > len(bare.markdown)


@pytest.fixture
def sample_csv_pair(sample_files: dict[str, Path], workdir: Path) -> tuple[Path, Path]:
    """Return two identical CSV copies, so counts can be compared independently."""
    original = sample_files["sample.csv"]
    twin = workdir / "twin.csv"
    twin.write_bytes(original.read_bytes())
    return original, twin


def test_convert_writes_into_tomd_out_dir_when_set(
    sample_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    redirected = tmp_path / "elsewhere"
    monkeypatch.setenv("TOMD_OUT_DIR", str(redirected))

    # Act
    result = core.convert(sample_pdf)

    # Assert
    assert result.out_path == redirected / "sample.md"
    assert (redirected / "sample.md").exists()
    assert not sample_pdf.with_suffix(".md").exists()


def test_convert_honours_an_explicit_destination(sample_pdf: Path, tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "nested" / "chosen.md"

    # Act
    result = core.convert(sample_pdf, out=destination)

    # Assert
    assert result.out_path == destination
    assert SENTINEL in destination.read_text(encoding="utf-8")


def test_convert_leaves_an_identical_destination_untouched(sample_pdf: Path) -> None:
    # Arrange
    first = core.convert(sample_pdf)
    assert first.out_path is not None
    stale_mtime = time.time() - 120
    os.utime(first.out_path, (stale_mtime, stale_mtime))
    before = first.out_path.stat().st_mtime

    # Act
    core.convert(sample_pdf)

    # Assert
    assert first.out_path.stat().st_mtime == before


def test_convert_rewrites_when_the_body_changed(sample_pdf: Path) -> None:
    # Arrange
    first = core.convert(sample_pdf)
    assert first.out_path is not None
    first.out_path.write_text("---\ntool: tomd\n---\n\nstale body\n", encoding="utf-8")

    # Act
    core.convert(sample_pdf)

    # Assert
    assert SENTINEL in first.out_path.read_text(encoding="utf-8")


def test_convert_refuses_to_overwrite_its_own_source(workdir: Path) -> None:
    # Arrange
    markdown_source = workdir / "notes.md"
    markdown_source.write_text("# notes\n", encoding="utf-8")

    # Act
    result = core.convert(markdown_source)

    # Assert
    assert result.error is not None
    assert "is the source file" in result.error


def test_convert_writes_nothing_when_write_is_disabled(sample_pdf: Path) -> None:
    # Arrange / Act
    result = core.convert(sample_pdf, write=False)

    # Assert
    assert result.out_path is None
    assert not sample_pdf.with_suffix(".md").exists()
    assert SENTINEL in result.markdown


@pytest.mark.usefixtures("no_optional_backends")
@pytest.mark.parametrize(
    ("docintel", "describe_images", "expected_variable"),
    [
        (True, False, "AZURE_DOCINTEL_ENDPOINT"),
        (False, True, "OPENAI_API_KEY"),
    ],
)
def test_optional_backends_name_the_missing_variable(
    sample_pdf: Path, docintel: bool, describe_images: bool, expected_variable: str
) -> None:
    # Arrange / Act
    result = core.convert(sample_pdf, docintel=docintel, describe_images=describe_images)

    # Assert
    assert result.error is not None
    assert expected_variable in result.error


def test_iter_supported_files_filters_by_extension_and_skips_hidden(workdir: Path) -> None:
    # Arrange
    (workdir / "a.pdf").write_bytes(b"x")
    (workdir / "b.docx").write_bytes(b"x")
    (workdir / "notes.md").write_text("x", encoding="utf-8")
    (workdir / "binary.bin").write_bytes(b"x")
    hidden = workdir / ".git"
    hidden.mkdir()
    (hidden / "c.pdf").write_bytes(b"x")
    nested = workdir / "deep"
    nested.mkdir()
    (nested / "d.csv").write_text("x", encoding="utf-8")

    # Act
    found = core.iter_supported_files(workdir)

    # Assert
    assert [p.name for p in found] == ["a.pdf", "b.docx", "d.csv"]


def test_strip_front_matter_returns_body_and_leaves_plain_text_alone() -> None:
    # Arrange
    framed = "---\ntool: tomd\n---\n\n# Title\n\nbody\n"
    plain = "# Title\n\nbody\n"

    # Act
    stripped = core.strip_front_matter(framed)

    # Assert
    assert stripped == plain
    assert core.strip_front_matter(plain) == plain


def test_duration_is_recorded_for_failures_too(workdir: Path) -> None:
    # Arrange
    missing = workdir / "gone.pdf"

    # Act
    result = core.convert(missing)

    # Assert
    assert result.duration_ms >= 0
    assert result.cached is False
