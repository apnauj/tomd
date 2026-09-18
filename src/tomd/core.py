"""The one place where a file becomes Markdown.

Everything else in tomd — the CLI, the web server — is a presentation layer over
:func:`convert`. This module must not import either of them.

The contract that matters: :func:`convert` never raises. A batch of forty PDFs
cannot be brought down by the one that is corrupt, so every failure mode is
reported as a :class:`ConversionResult` carrying ``error``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Final

from markitdown import MarkItDown

from tomd import config

logger = logging.getLogger(__name__)

#: Extensions tomd will pick up when walking a directory. Taken from the
#: converters MarkItDown registers, minus the Markdown-ish ones: converting
#: ``notes.md`` would write its output over ``notes.md``.
SUPPORTED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".xls",
        ".csv",
        ".json",
        ".jsonl",
        ".html",
        ".htm",
        ".xml",
        ".epub",
        ".ipynb",
        ".msg",
        ".txt",
        ".text",
        ".zip",
        ".png",
        ".jpg",
        ".jpeg",
        ".mp3",
        ".wav",
        ".m4a",
        ".mp4",
    }
)

#: Environment variable each optional back end needs before it can be used.
ENV_DOCINTEL_ENDPOINT: Final = "AZURE_DOCINTEL_ENDPOINT"
ENV_OPENAI_API_KEY: Final = "OPENAI_API_KEY"

_FENCE: Final = "---"


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Outcome of converting a single file.

    Attributes:
        source: The file that was read.
        markdown: The finished document, front matter included. Empty on failure.
        out_path: Where the document was written, or ``None`` when nothing was
            written (``write=False``, or the conversion failed).
        chars: Character count of the converted body, front matter excluded.
        words: Whitespace-separated word count of the body, front matter excluded.
        cached: Whether the Markdown came from the cache instead of MarkItDown.
        duration_ms: Wall-clock time for the whole operation.
        error: A human-readable reason for failure, or ``None`` on success.
    """

    source: Path
    markdown: str
    out_path: Path | None
    chars: int
    words: int
    cached: bool
    duration_ms: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the conversion succeeded."""
        return self.error is None


def convert(
    path: Path,
    out: Path | None = None,
    use_cache: bool = True,  # noqa: ARG001 - wired up by the cache module
    *,
    frontmatter: bool = True,
    write: bool = True,
    docintel: bool = False,
    describe_images: bool = False,
) -> ConversionResult:
    """Convert one file to Markdown.

    Args:
        path: File to convert.
        out: Explicit destination. When ``None`` the document goes next to the
            source with a ``.md`` suffix, or into ``$TOMD_OUT_DIR`` when that is
            set.
        use_cache: Reserved for the cache layer; every call currently performs a
            fresh conversion.
        frontmatter: Prepend the YAML front matter block.
        write: Write the document to disk. ``False`` is what ``--stdout`` uses.
        docintel: Route the conversion through Azure Document Intelligence.
            Requires ``$AZURE_DOCINTEL_ENDPOINT``.
        describe_images: Ask an LLM to describe images. Requires
            ``$OPENAI_API_KEY``.

    Returns:
        A :class:`ConversionResult`. On any failure — missing file, unsupported
        format, unreadable content, unwritable destination, missing credentials —
        ``error`` is populated and ``markdown`` is empty. No exception ever
        leaves this function.
    """
    started = time.perf_counter()
    try:
        body = _run_markitdown(path, docintel=docintel, describe_images=describe_images)
        document = _with_front_matter(body, path) if frontmatter else body
        out_path = _write_document(document, path, out) if write else None
    except Exception as exc:  # the whole point of this function is to report, not raise
        logger.debug("conversion of %s failed", path, exc_info=True)
        return ConversionResult(
            source=path,
            markdown="",
            out_path=None,
            chars=0,
            words=0,
            cached=False,
            duration_ms=_elapsed_ms(started),
            error=_describe(exc),
        )

    return ConversionResult(
        source=path,
        markdown=document,
        out_path=out_path,
        chars=len(body),
        words=len(body.split()),
        cached=False,
        duration_ms=_elapsed_ms(started),
        error=None,
    )


def iter_supported_files(directory: Path) -> list[Path]:
    """List the convertible files under a directory, recursively.

    Args:
        directory: Directory to walk.

    Returns:
        Sorted paths whose suffix is in :data:`SUPPORTED_EXTENSIONS`. Anything
        else is skipped silently, as are hidden files and directories, so that
        pointing tomd at a project tree does not drag in ``.git`` internals.
    """
    found = [
        item
        for item in sorted(directory.rglob("*"))
        if item.is_file()
        and item.suffix.lower() in SUPPORTED_EXTENSIONS
        and not any(part.startswith(".") for part in item.relative_to(directory).parts)
    ]
    logger.debug("found %d convertible files under %s", len(found), directory)
    return found


def default_out_path(source: Path) -> Path:
    """Return where a converted document goes when no destination is given.

    Args:
        source: The file being converted.

    Returns:
        ``$TOMD_OUT_DIR/<name>.md`` when that variable is set, otherwise the
        source path with a ``.md`` suffix.
    """
    configured = config.out_dir()
    if configured is not None:
        return configured / f"{source.stem}.md"
    return source.with_suffix(".md")


def _run_markitdown(path: Path, *, docintel: bool, describe_images: bool) -> str:
    if not path.exists():
        raise FileNotFoundError(f"no such file: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"{path} is a directory, not a file")

    endpoint = _required_env(ENV_DOCINTEL_ENDPOINT) if docintel else None
    if describe_images:
        _required_env(ENV_OPENAI_API_KEY)
        raise NotImplementedError(
            "--describe-images is not implemented in v1: the flag only checks that "
            f"${ENV_OPENAI_API_KEY} is set"
        )

    converter = _converter(endpoint)
    return str(converter.convert(path).markdown)


@lru_cache(maxsize=4)
def _converter(docintel_endpoint: str | None) -> MarkItDown:
    """Build a MarkItDown instance, reused across calls.

    Constructing one loads the magika detection model, which costs far more than
    a small conversion, so instances are memoised per back end configuration.
    """
    if docintel_endpoint is not None:
        return MarkItDown(enable_plugins=False, docintel_endpoint=docintel_endpoint)
    return MarkItDown(enable_plugins=False)


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"${name} is not set")
    return value


def _with_front_matter(body: str, source: Path) -> str:
    size = source.stat().st_size
    header = "\n".join(
        [
            _FENCE,
            f'source: "{_yaml_escape(str(source.resolve()))}"',
            f"converted_at: {datetime.now(UTC).isoformat(timespec='seconds')}",
            f"size_bytes: {size}",
            f"tool: {config.TOOL_NAME}",
            _FENCE,
            "",
            "",
        ]
    )
    return header + body


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def strip_front_matter(document: str) -> str:
    """Return a document without its leading tomd front matter block.

    Args:
        document: Markdown that may or may not start with a ``---`` block.

    Returns:
        The body alone when a front matter block is present at the very start,
        otherwise the document unchanged.
    """
    if not document.startswith(f"{_FENCE}\n"):
        return document
    closing = document.find(f"\n{_FENCE}\n", len(_FENCE))
    if closing == -1:
        return document
    return document[closing + len(_FENCE) + 2 :].lstrip("\n")


def _write_document(document: str, source: Path, out: Path | None) -> Path:
    out_path = out if out is not None else default_out_path(source)
    if out_path.resolve() == source.resolve():
        raise ValueError(f"destination {out_path} is the source file; pass -o or --stdout instead")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and _is_same_document(out_path, document):
        logger.debug("%s already up to date, leaving it untouched", out_path)
        return out_path

    out_path.write_text(document, encoding="utf-8")
    return out_path


def _is_same_document(out_path: Path, document: str) -> bool:
    """Whether an existing file already holds this conversion.

    The front matter carries a fresh ``converted_at`` on every run, so a byte
    comparison would always differ; the bodies are compared instead, which is
    what "the content is identical" actually means here.
    """
    try:
        existing = out_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return strip_front_matter(existing) == strip_front_matter(document)


def _describe(exc: BaseException) -> str:
    """Flatten an exception into one readable line.

    MarkItDown wraps the real cause in a FileConversionException whose message
    spans several lines; a batch report needs one line per file.
    """
    message = " ".join(str(exc).split()) or exc.__class__.__name__
    if isinstance(exc, FileNotFoundError):
        return message
    return f"{exc.__class__.__name__}: {message}"


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
