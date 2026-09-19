"""Fixtures shared by the whole suite.

The isolation rule enforced here: a test run never reads or writes the real
``~/.cache/tomd`` and never drops a ``.md`` next to the committed fixtures.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from tomd import config

FIXTURE_DIR = Path(__file__).parent / "fixtures"

#: Text present in every non-corrupt fixture, so a test can prove that the
#: Markdown really came from the source document.
SENTINEL = "Chorizo de Zacatecas"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the cache at a throwaway directory for every test.

    Autouse on purpose: forgetting it in a single test would let that test write
    into the developer's real cache.

    Returns:
        The temporary cache directory.
    """
    cache = tmp_path / "cache"
    monkeypatch.setenv(config.ENV_CACHE_DIR, str(cache))
    monkeypatch.delenv(config.ENV_OUT_DIR, raising=False)
    return cache


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Return an empty directory for a test to write conversions into."""
    work = tmp_path / "work"
    work.mkdir()
    return work


@pytest.fixture
def sample_files(workdir: Path) -> dict[str, Path]:
    """Copy the committed fixtures into a writable directory.

    Conversions write a sibling ``.md``, so tests operate on copies; the
    originals under ``tests/fixtures`` stay pristine.

    Returns:
        Mapping of fixture file name to its copy.
    """
    copies = {}
    for source in sorted(FIXTURE_DIR.iterdir()):
        if source.is_file():
            target = workdir / source.name
            shutil.copy2(source, target)
            copies[source.name] = target
    return copies


@pytest.fixture
def sample_pdf(sample_files: dict[str, Path]) -> Path:
    """Return a writable copy of the PDF fixture."""
    return sample_files["sample.pdf"]


@pytest.fixture
def corrupt_pdf(sample_files: dict[str, Path]) -> Path:
    """Return a writable copy of the deliberately broken PDF fixture."""
    return sample_files["corrupt.pdf"]


@pytest.fixture
def no_optional_backends(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Unset the credentials that the optional back ends look for."""
    monkeypatch.delenv("AZURE_DOCINTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield
