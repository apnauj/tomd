"""Tests for the command line layer.

core.convert is mocked throughout: what is under test here is argument
resolution, output formatting and exit codes, not conversion.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tomd import cache as cache_store
from tomd import cli, core

ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture
def runner() -> CliRunner:
    """Return a Click runner that keeps stdout and stderr apart."""
    return CliRunner()


def _result(
    source: Path,
    *,
    words: int = 12,
    cached: bool = False,
    error: str | None = None,
) -> core.ConversionResult:
    """Build a ConversionResult without going near MarkItDown."""
    return core.ConversionResult(
        source=source,
        markdown="" if error else "---\ntool: tomd\n---\n\n# converted\n",
        out_path=None if error else source.with_suffix(".md"),
        chars=0 if error else 40,
        words=0 if error else words,
        cached=cached,
        duration_ms=4.2,
        error=error,
    )


@pytest.fixture
def fake_convert(monkeypatch: pytest.MonkeyPatch) -> Callable[..., core.ConversionResult]:
    """Replace core.convert with a stub that succeeds for every file."""

    def stub(path: Path, **_kwargs: object) -> core.ConversionResult:
        return _result(path)

    monkeypatch.setattr(core, "convert", stub)
    return stub


@pytest.fixture
def one_bad_apple(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace core.convert with a stub that fails only on 'broken.pdf'."""

    def stub(path: Path, **_kwargs: object) -> core.ConversionResult:
        if path.name == "broken.pdf":
            return _result(path, error="PDFSyntaxError: No /Root object")
        return _result(path)

    monkeypatch.setattr(core, "convert", stub)


@pytest.fixture
def documents(tmp_path: Path) -> list[Path]:
    """Create three convertible files with distinct names."""
    names = ["first.pdf", "second.docx", "third.csv"]
    made = []
    for name in names:
        target = tmp_path / name
        target.write_bytes(b"pretend this is a document")
        made.append(target)
    return made


@pytest.mark.usefixtures("fake_convert")
def test_json_output_is_parseable_and_alone_on_stdout(
    runner: CliRunner, documents: list[Path]
) -> None:
    # Arrange
    arguments = [str(path) for path in documents] + ["--json"]

    # Act
    result = runner.invoke(cli.app, arguments)

    # Assert
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    records = [json.loads(line) for line in lines]
    assert len(records) == 3
    assert [record["source"] for record in records] == [str(p) for p in documents]
    assert all(record["ok"] for record in records)


@pytest.mark.usefixtures("fake_convert")
def test_json_output_carries_no_summary_line(runner: CliRunner, documents: list[Path]) -> None:
    # Arrange
    arguments = [str(path) for path in documents] + ["--json"]

    # Act
    result = runner.invoke(cli.app, arguments)

    # Assert
    assert "converted" not in result.stdout
    assert "✓" not in result.stdout


@pytest.mark.usefixtures("one_bad_apple")
def test_a_failed_file_exits_one_while_the_rest_are_converted(
    runner: CliRunner, tmp_path: Path
) -> None:
    # Arrange
    good = tmp_path / "fine.pdf"
    bad = tmp_path / "broken.pdf"
    for path in (good, bad):
        path.write_bytes(b"x")

    # Act
    result = runner.invoke(cli.app, [str(good), str(bad)])

    # Assert
    assert result.exit_code == 1
    assert "✓" in result.stdout
    assert "✗" in result.stdout
    assert "PDFSyntaxError" in result.stdout


@pytest.mark.usefixtures("fake_convert")
def test_a_clean_batch_exits_zero(runner: CliRunner, documents: list[Path]) -> None:
    # Arrange
    arguments = [str(path) for path in documents]

    # Act
    result = runner.invoke(cli.app, arguments)

    # Assert
    assert result.exit_code == 0


def test_the_summary_counts_converted_cached_and_failed(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    fresh = tmp_path / "fresh.pdf"
    repeat = tmp_path / "repeat.docx"
    broken = tmp_path / "broken.csv"
    for path in (fresh, repeat, broken):
        path.write_bytes(b"x")

    def stub(path: Path, **_kwargs: object) -> core.ConversionResult:
        if path.name.startswith("repeat"):
            return _result(path, cached=True)
        if path.name.startswith("broken"):
            return _result(path, error="nope")
        return _result(path)

    monkeypatch.setattr(core, "convert", stub)

    # Act
    result = runner.invoke(cli.app, [str(fresh), str(repeat), str(broken)])

    # Assert
    assert "1 converted, 1 cached, 1 failed" in result.stdout


@pytest.mark.usefixtures("fake_convert")
def test_output_is_free_of_ansi_codes_when_stdout_is_not_a_tty(
    runner: CliRunner, documents: list[Path]
) -> None:
    # Arrange
    arguments = [str(path) for path in documents]

    # Act
    result = runner.invoke(cli.app, arguments)

    # Assert
    assert ANSI.search(result.stdout) is None
    assert "✓" in result.stdout


@pytest.mark.usefixtures("fake_convert")
def test_stdout_mode_prints_markdown_and_keeps_status_on_stderr(
    runner: CliRunner, documents: list[Path]
) -> None:
    # Arrange
    target = documents[0]

    # Act
    result = runner.invoke(cli.app, [str(target), "--stdout"])

    # Assert
    assert "# converted" in result.stdout
    assert "✓" not in result.stdout


@pytest.mark.usefixtures("fake_convert")
def test_a_directory_without_recursive_is_rejected(runner: CliRunner, tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "a.pdf").write_bytes(b"x")

    # Act
    result = runner.invoke(cli.app, [str(tmp_path)])

    # Assert
    assert result.exit_code == 1
    assert "pass -r to walk it" in result.stdout


@pytest.mark.usefixtures("fake_convert")
def test_recursive_walks_a_directory_for_supported_files(
    runner: CliRunner, tmp_path: Path, documents: list[Path]
) -> None:
    # Arrange
    (tmp_path / "ignored.bin").write_bytes(b"x")

    # Act
    result = runner.invoke(cli.app, [str(tmp_path), "-r", "--json"])

    # Assert
    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert sorted(Path(r["source"]).name for r in records) == sorted(p.name for p in documents)


@pytest.mark.usefixtures("fake_convert")
@pytest.mark.usefixtures("documents")
def test_a_glob_pattern_is_expanded(runner: CliRunner, tmp_path: Path) -> None:
    # Arrange
    pattern = str(tmp_path / "*.pdf")

    # Act
    result = runner.invoke(cli.app, [pattern, "--json"])

    # Assert
    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert [Path(r["source"]).name for r in records] == ["first.pdf"]


@pytest.mark.usefixtures("fake_convert")
def test_a_pattern_matching_nothing_is_reported_and_fails(
    runner: CliRunner, tmp_path: Path
) -> None:
    # Arrange
    pattern = str(tmp_path / "*.nothing")

    # Act
    result = runner.invoke(cli.app, [pattern])

    # Assert
    assert result.exit_code == 1
    assert "no files match this pattern" in result.stdout


@pytest.mark.usefixtures("fake_convert")
def test_two_sources_wanting_the_same_destination_do_not_overwrite_each_other(
    runner: CliRunner, tmp_path: Path
) -> None:
    # Arrange
    (tmp_path / "report.pdf").write_bytes(b"x")
    (tmp_path / "report.docx").write_bytes(b"x")

    # Act
    result = runner.invoke(cli.app, [str(tmp_path), "-r"])

    # Assert
    assert result.exit_code == 1
    assert "would overwrite" in result.stdout
    assert "1 converted, 0 cached, 1 failed" in result.stdout


@pytest.mark.usefixtures("fake_convert")
def test_out_and_stdout_together_are_refused(runner: CliRunner, documents: list[Path]) -> None:
    # Arrange
    arguments = [str(documents[0]), "--stdout", "-o", "somewhere.md"]

    # Act
    result = runner.invoke(cli.app, arguments)

    # Assert
    assert result.exit_code == 2
    assert "cannot be combined" in result.output


@pytest.mark.usefixtures("fake_convert")
def test_out_with_several_files_is_refused(runner: CliRunner, documents: list[Path]) -> None:
    # Arrange
    arguments = [str(path) for path in documents] + ["-o", "single.md"]

    # Act
    result = runner.invoke(cli.app, arguments)

    # Assert
    assert result.exit_code == 2
    assert "takes a single file" in result.output


def test_flags_reach_core_convert(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    target = tmp_path / "doc.pdf"
    target.write_bytes(b"x")
    seen: dict[str, object] = {}

    def stub(path: Path, **kwargs: object) -> core.ConversionResult:
        seen.update(kwargs)
        return _result(path)

    monkeypatch.setattr(core, "convert", stub)

    # Act
    runner.invoke(cli.app, [str(target), "--no-cache", "--no-frontmatter"])

    # Assert
    assert seen["use_cache"] is False
    assert seen["frontmatter"] is False
    assert seen["write"] is True


def test_cache_info_reports_the_entry_count(runner: CliRunner) -> None:
    # Arrange / Act
    result = runner.invoke(cli.app, ["cache", "--info"])

    # Assert
    assert result.exit_code == 0
    assert "0 entries" in result.stdout


def test_cache_clear_empties_the_directory(runner: CliRunner) -> None:
    # Arrange
    cache_store.store("a" * 64, "# body\n", source=Path("whatever.pdf"))

    # Act
    result = runner.invoke(cli.app, ["cache", "--clear"])

    # Assert
    assert "Cleared 1 cache entry." in result.stdout
    assert cache_store.info().entries == 0


def test_version_flag_prints_the_version(runner: CliRunner) -> None:
    # Arrange / Act
    result = runner.invoke(cli.app, ["--version"])

    # Assert
    assert result.exit_code == 0
    assert result.stdout.startswith("tomd ")
