"""Command line entry point.

This module is presentation only: it resolves what the user pointed at, calls
:func:`tomd.core.convert` once per file and renders the outcome. No conversion
logic lives here.

Two rules shape the output. With ``--json`` nothing but JSON reaches stdout, so
a pipeline can read it; status and logs go to stderr. And when stdout is not a
terminal, rich is told to drop colour, so redirected output stays plain text.
"""

from __future__ import annotations

import glob
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from typer.core import TyperGroup

from tomd import cache as cache_store
from tomd import core

if TYPE_CHECKING:
    # typer vendors its own copy of click, so the context TyperGroup.parse_args
    # receives is NOT click.Context. Overriding it correctly means naming
    # typer's type, which only exists on this private path.
    from typer._click.core import Context as ClickContext

logger = logging.getLogger("tomd")

#: Arguments that belong to the group itself and must not be read as files.
_GROUP_FLAGS = frozenset({"--help", "-h", "--version", "-V"})

_GLOB_CHARACTERS = ("*", "?", "[")


class _ConvertByDefault(TyperGroup):
    """Let ``tomd file.pdf`` work without naming the ``convert`` subcommand."""

    def parse_args(self, ctx: ClickContext, args: list[str]) -> list[str]:
        """Insert ``convert`` when the first argument is not a known command.

        Args:
            ctx: Click context for the group.
            args: Raw arguments, minus the program name.

        Returns:
            The remaining arguments, as Click's own implementation returns them.
        """
        if args and args[0] not in self.commands and args[0] not in _GROUP_FLAGS:
            args = ["convert", *args]
        return super().parse_args(ctx, args)


app = typer.Typer(
    cls=_ConvertByDefault,
    help="Convert documents, images and audio to Markdown.",
    add_completion=False,
    no_args_is_help=True,
)


@dataclass(slots=True)
class _Tally:
    """Running totals for the closing summary."""

    converted: int = 0
    cached: int = 0
    failed: int = 0

    def line(self) -> str:
        """Render the summary line."""
        return f"{self.converted} converted, {self.cached} cached, {self.failed} failed"


def _version(show: bool) -> None:
    if show:
        # Imported here so the metadata lookup stays off the conversion path.
        from tomd import __version__

        print(f"tomd {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", "-V", callback=_version, is_eager=True, help="Print the version."
        ),
    ] = False,
) -> None:
    """Convert documents, images and audio to Markdown."""


@app.command()
def convert(
    paths: Annotated[
        list[str],
        typer.Argument(metavar="PATH...", help="Files, directories or glob patterns."),
    ],
    recursive: Annotated[
        bool, typer.Option("--recursive", "-r", help="Walk directories for supported files.")
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write to this path. Only valid for a single file."),
    ] = None,
    to_stdout: Annotated[
        bool, typer.Option("--stdout", help="Write the Markdown to stdout instead of to disk.")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit one JSON object per file on stdout.")
    ] = False,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Convert again even if the content is cached.")
    ] = False,
    no_frontmatter: Annotated[
        bool, typer.Option("--no-frontmatter", help="Omit the YAML front matter block.")
    ] = False,
    docintel: Annotated[
        bool, typer.Option("--docintel", help="Use Azure Document Intelligence.")
    ] = False,
    describe_images: Annotated[
        bool, typer.Option("--describe-images", help="Describe images with an LLM.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Log what is happening.")
    ] = False,
) -> None:
    """Convert one or more files.

    Args:
        paths: What to convert. Directories need ``-r``; globs are expanded here
            as well as by the shell, so quoted patterns still work.
        recursive: Walk directories instead of rejecting them.
        out: Explicit destination for a single file.
        to_stdout: Print the Markdown rather than writing files.
        as_json: One JSON object per line on stdout, and nothing else.
        no_cache: Bypass the cache in both directions.
        no_frontmatter: Drop the YAML header.
        docintel: Route through Document Intelligence.
        describe_images: Ask an LLM to describe images.
        verbose: Raise the log level to INFO.

    Raises:
        typer.Exit: With code 1 when any file failed, 2 for an unusable
            combination of options.
    """
    _configure_logging(verbose)
    status = _console(stderr=as_json or to_stdout)
    errors = _console(stderr=True)

    if out is not None and to_stdout:
        errors.print("[red]--out and --stdout cannot be combined.[/red]")
        raise typer.Exit(code=2)

    targets, rejected = _resolve(paths, recursive=recursive)
    if out is not None and len(targets) > 1:
        errors.print("[red]--out takes a single file; drop it to convert many.[/red]")
        raise typer.Exit(code=2)

    tally = _Tally(failed=len(rejected))
    for message in rejected:
        _report_failure(message, as_json=as_json, console=status)

    claimed: dict[Path, Path] = {}
    for target in targets:
        collision = _claim(target, out=out, writing=not to_stdout, claimed=claimed)
        if collision is not None:
            tally.failed += 1
            _report_failure(collision, as_json=as_json, console=status)
            continue

        result = core.convert(
            target,
            out=out,
            use_cache=not no_cache,
            frontmatter=not no_frontmatter,
            write=not to_stdout,
            docintel=docintel,
            describe_images=describe_images,
        )
        _tally(result, tally)

        if as_json:
            print(json.dumps(_as_record(result), ensure_ascii=False))
        else:
            if to_stdout and result.ok:
                print(result.markdown, end="" if result.markdown.endswith("\n") else "\n")
            status.print(_render(result))

    if not as_json and len(targets) + len(rejected) > 1:
        status.print(f"[dim]{tally.line()}[/dim]")

    if tally.failed:
        raise typer.Exit(code=1)


@app.command()
def serve(
    port: Annotated[
        int | None, typer.Option("--port", "-p", help="Port to listen on. Defaults to 8765.")
    ] = None,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not open a browser window.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Log what is happening.")
    ] = False,
) -> None:
    """Serve the web UI on localhost.

    Args:
        port: TCP port; ``$TOMD_PORT`` or 8765 when omitted.
        no_browser: Skip opening the browser.
        verbose: Raise the log level to INFO.
    """
    _configure_logging(verbose)
    # Imported here rather than at module scope: fastapi and uvicorn add real
    # import time, and `tomd file.pdf` should not pay for a server it never runs.
    from tomd import web

    web.serve(port, open_browser=not no_browser)


@app.command("cache")
def cache_command(
    info: Annotated[
        bool, typer.Option("--info", help="Show entry count and size on disk.")
    ] = False,
    clear: Annotated[bool, typer.Option("--clear", help="Delete every cached conversion.")] = False,
) -> None:
    """Inspect or empty the conversion cache.

    Args:
        info: Report what the cache holds. This is also the default.
        clear: Remove every entry.
    """
    console = _console()
    if clear:
        removed = cache_store.clear()
        console.print(f"Cleared {removed} cache {_plural(removed, 'entry', 'entries')}.")
        if not info:
            return

    summary = cache_store.info()
    console.print(
        f"{summary.entries} {_plural(summary.entries, 'entry', 'entries')}, "
        f"{_human_bytes(summary.bytes)} in {summary.path}"
    )


def _resolve(paths: list[str], *, recursive: bool) -> tuple[list[Path], list[str]]:
    """Turn command line arguments into files to convert.

    Args:
        paths: Raw arguments: files, directories or glob patterns.
        recursive: Whether directories may be walked.

    Returns:
        The files to convert, and a message for every argument that could not
        be used. Unsupported files inside a walked directory are skipped in
        silence; an argument named explicitly is never skipped silently.
    """
    targets: list[Path] = []
    rejected: list[str] = []

    for raw in paths:
        candidate = Path(raw)
        if any(character in raw for character in _GLOB_CHARACTERS) and not candidate.exists():
            matches = [Path(match) for match in sorted(glob.glob(raw))]  # noqa: PTH207
            if not matches:
                rejected.append(f"{raw}: no files match this pattern")
            targets.extend(match for match in matches if match.is_file())
            continue

        if candidate.is_dir():
            if not recursive:
                rejected.append(f"{raw}: is a directory, pass -r to walk it")
                continue
            targets.extend(core.iter_supported_files(candidate))
            continue

        targets.append(candidate)

    return targets, rejected


def _claim(
    target: Path, *, out: Path | None, writing: bool, claimed: dict[Path, Path]
) -> str | None:
    """Reserve a destination, refusing one that this run already wrote.

    ``report.pdf`` and ``report.docx`` in one directory both want ``report.md``.
    Converting them in the same run would leave whichever finished last and
    silently lose the other, so the second is reported as a failure instead.

    Args:
        target: File about to be converted.
        out: Explicit destination, if the user gave one.
        writing: Whether this run writes files at all.
        claimed: Destinations already taken, mapped to the file that took them.

    Returns:
        ``None`` when the destination is free, otherwise a message naming the
        clash.
    """
    if not writing:
        return None

    destination = out if out is not None else core.default_out_path(target)
    previous = claimed.get(destination)
    if previous is not None:
        return (
            f"{target}: would overwrite {destination}, already written from {previous.name} "
            f"in this run; use -o or $TOMD_OUT_DIR"
        )

    claimed[destination] = target
    return None


def _tally(result: core.ConversionResult, tally: _Tally) -> None:
    if not result.ok:
        tally.failed += 1
    elif result.cached:
        tally.cached += 1
    else:
        tally.converted += 1


def _render(result: core.ConversionResult) -> str:
    if not result.ok:
        return f"[red]✗[/red] {result.source} [red]{result.error}[/red]"
    detail = "cached" if result.cached else f"{result.duration_ms / 1000:.2f}s"
    return f"[green]✓[/green] {result.source} [dim]{result.words} words · {detail}[/dim]"


def _report_failure(message: str, *, as_json: bool, console: Console) -> None:
    if as_json:
        argument, _, reason = message.partition(": ")
        print(json.dumps({"source": argument, "ok": False, "error": reason}, ensure_ascii=False))
    else:
        console.print(f"[red]✗[/red] {message}")


def _as_record(result: core.ConversionResult) -> dict[str, object]:
    return {
        "source": str(result.source),
        "out_path": str(result.out_path) if result.out_path else None,
        "ok": result.ok,
        "cached": result.cached,
        "chars": result.chars,
        "words": result.words,
        "duration_ms": result.duration_ms,
        "error": result.error,
    }


def _console(*, stderr: bool = False) -> Console:
    """Build a console that stays readable in a pipe.

    Soft wrapping leaves line breaking to the terminal: rich would otherwise
    hard-wrap a long path and strand the status mark on a line of its own. Rich
    drops colour by itself when the stream is not a terminal.
    """
    return Console(stderr=stderr, soft_wrap=True)


def _configure_logging(verbose: bool) -> None:
    """Send logs to stderr, so they never contaminate stdout."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


if __name__ == "__main__":  # pragma: no cover
    app()
