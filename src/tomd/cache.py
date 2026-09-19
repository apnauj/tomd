"""Content-addressed cache of conversion results.

Entries are keyed by the SHA-256 of the file's bytes, never by path or mtime:
the same document downloaded twice under two names is converted once, and
touching a file without changing it does not invalidate anything.

What is cached is the raw Markdown body, without front matter. Front matter
carries a fresh ``converted_at`` on every run and is cheap to rebuild, so
keeping it out of the entry lets ``--no-frontmatter`` and a normal run share
the same cached conversion.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from tomd import config

logger = logging.getLogger(__name__)

_DOCUMENT_NAME: Final = "document.md"
_META_NAME: Final = "meta.json"
_READ_CHUNK: Final = 1024 * 1024

#: Cache variant used when no optional back end is involved.
DEFAULT_VARIANT: Final = "plain"


@dataclass(frozen=True, slots=True)
class CacheInfo:
    """Summary of what the cache currently holds.

    Attributes:
        path: Directory backing the cache.
        entries: Number of stored conversions.
        bytes: Total size on disk, including metadata.
    """

    path: Path
    entries: int
    bytes: int


def file_digest(path: Path) -> str:
    """Return the SHA-256 of a file's contents.

    Args:
        path: File to hash. Read in chunks, so a large video costs no more
            memory than a small text file.

    Returns:
        The digest as a lowercase hex string.

    Raises:
        OSError: If the file cannot be read. Callers in :mod:`tomd.core` turn
            this into a failed ``ConversionResult``.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def load(digest: str, variant: str = DEFAULT_VARIANT) -> str | None:
    """Return a previously cached Markdown body.

    Args:
        digest: Content digest from :func:`file_digest`.
        variant: Which back end produced the entry. Conversions through
            Document Intelligence differ from offline ones, so they are stored
            apart instead of shadowing each other.

    Returns:
        The cached body, or ``None`` on a miss or an unreadable entry. A damaged
        entry is a miss, never an error: the worst case is one extra conversion.
    """
    document = _entry_dir(digest, variant) / _DOCUMENT_NAME
    try:
        body = document.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.debug("cache miss for %s/%s", variant, digest)
        return None
    logger.debug("cache hit for %s/%s", variant, digest)
    return body


def store(digest: str, body: str, *, source: Path, variant: str = DEFAULT_VARIANT) -> Path:
    """Write a conversion into the cache.

    Args:
        digest: Content digest from :func:`file_digest`.
        body: Markdown body to store, without front matter.
        source: File the body came from, recorded in the metadata for humans
            inspecting the cache. It is not part of the key.
        variant: Which back end produced the entry.

    Returns:
        The directory holding the new entry.

    Raises:
        OSError: If the cache directory cannot be written to.
    """
    entry = _entry_dir(digest, variant)
    entry.mkdir(parents=True, exist_ok=True)
    meta = {
        "digest": digest,
        "variant": variant,
        "source": str(source),
        "stored_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_bytes": source.stat().st_size if source.exists() else None,
        "markdown_chars": len(body),
    }
    _write_atomically(entry / _DOCUMENT_NAME, body)
    _write_atomically(entry / _META_NAME, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    return entry


def clear() -> int:
    """Delete every cached conversion.

    Returns:
        How many entries were removed. Zero when the cache does not exist yet.
        The cache directory itself is left in place, empty.
    """
    root = config.cache_dir()
    if not root.exists():
        return 0
    removed = len(_entry_dirs(root))
    shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    logger.info("cleared %d cache entries from %s", removed, root)
    return removed


def info() -> CacheInfo:
    """Summarise the cache without loading any conversion.

    Returns:
        A :class:`CacheInfo`. An absent cache directory reports zero entries
        rather than failing, so ``tomd cache --info`` works on a fresh install.
    """
    root = config.cache_dir()
    if not root.exists():
        return CacheInfo(path=root, entries=0, bytes=0)

    total = sum(item.stat().st_size for item in root.rglob("*") if item.is_file())
    return CacheInfo(path=root, entries=len(_entry_dirs(root)), bytes=total)


def _entry_dirs(root: Path) -> list[Path]:
    # <root>/<variant>/<shard>/<digest>/meta.json
    return [meta.parent for meta in root.glob(f"*/*/*/{_META_NAME}")]


def _entry_dir(digest: str, variant: str) -> Path:
    # Sharded by the first two hex characters: a cache with thousands of entries
    # stays navigable, and directory listings stay cheap.
    return config.cache_dir() / variant / digest[:2] / digest


def _write_atomically(target: Path, content: str) -> None:
    """Write via a temporary sibling, then rename.

    A crash mid-write would otherwise leave a truncated entry behind, and the
    next run would serve it as if it were a complete conversion.
    """
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)
