# tomd

A local wrapper around [MarkItDown](https://github.com/microsoft/markitdown) that
turns PDFs, Office documents, images, audio and HTML into Markdown — from the
terminal, from a small web page, and from Claude Code.

## Install

```bash
uv tool install --with 'markitdown[all]' .
```

`tomd` is then on your `PATH` from any directory.

> The first conversion after installing can take twenty seconds or so on macOS
> while Gatekeeper scans the freshly written native libraries. It is a one-time
> cost per install, not per document.

## Use

```bash
tomd report.pdf                   # writes report.md beside the source
tomd a.pdf b.docx c.xlsx          # several files
tomd papers/ -r                   # walk a directory
tomd report.pdf --stdout          # print instead of writing
tomd report.pdf -o notes/out.md   # explicit destination
tomd '*.pdf' --json               # one JSON object per line, for pipelines
tomd report.pdf --no-cache        # convert again even if cached
tomd report.pdf --no-frontmatter  # skip the YAML header
tomd serve                        # web UI on http://127.0.0.1:8765
tomd cache --info                 # entries and size on disk
tomd cache --clear                # empty it
```

Every converted document starts with a YAML front matter block:

```yaml
---
source: "/Users/you/report.pdf"
converted_at: 2026-09-19T18:49:33+00:00
size_bytes: 1925
tool: tomd
---
```

Exit code is 0 when everything converted and 1 when any file failed. A failure
never stops the batch: the other files still convert, and the failing one gets
its own line with the reason.

### Two things worth knowing

**Conversions are cached by content hash.** The same document under two names is
converted once; editing a file produces a new entry. The cache lives in
`~/.cache/tomd`.

**Two sources cannot share one destination.** `report.pdf` and `report.docx` in
one directory both want `report.md`, so the second is refused rather than
silently overwriting the first. Use `-o`, or `$TOMD_OUT_DIR`.

### Optional back ends

`--docintel` and `--describe-images` only check that their credentials are
present and fail with the name of the missing variable. Neither feature is
implemented in v1.

## Web UI

`tomd serve` opens a single page bound to `127.0.0.1` only, with no
authentication and no CORS: it converts whatever it is handed, so it must not be
reachable from anywhere else. Drop files anywhere on the window, copy or download
each result, or take them all as a zip. Uploads are staged in a temporary
directory and deleted when the request ends; nothing is persisted.

| Flag | Meaning |
| --- | --- |
| `--port` | Port to listen on. Defaults to 8765. |
| `--no-browser` | Do not open a browser window. |

## Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `TOMD_CACHE_DIR` | `~/.cache/tomd` | Where cached conversions live. |
| `TOMD_OUT_DIR` | unset | Write every `.md` here instead of beside the source. |
| `TOMD_PORT` | `8765` | Port for `tomd serve`. |
| `TOMD_MAX_UPLOAD_BYTES` | `104857600` | Per-file upload ceiling for the web UI. |
| `AZURE_DOCINTEL_ENDPOINT` | unset | Required by `--docintel`. |
| `OPENAI_API_KEY` | unset | Required by `--describe-images`. |

The host the web UI binds to is deliberately **not** configurable.

## Development

```bash
uv sync                  # create the environment, dev dependencies included
uv run pytest            # the whole suite
uv run pytest --cov=tomd --cov-report=term-missing
uv run ruff check .      # lint
uv run ruff format .     # format
uv run mypy              # strict type check
```

Install the git hooks once, and ruff, ruff-format and mypy run on every commit:

```bash
uv run pre-commit install
uv run pre-commit run --all-files   # optional: check everything now
```

Tests never touch the real `~/.cache/tomd`: an autouse fixture redirects the
cache into a temporary directory for every test.

## Branching

Gitflow, with merges to `develop` and `main` always made with `--no-ff` so the
history shows where each piece of work began and ended.

| Branch | Comes from | Goes back to | Purpose |
| --- | --- | --- | --- |
| `main` | — | — | Released versions only. Never committed to directly. |
| `develop` | `main` | — | Integration. Never committed to directly. |
| `feature/<name>` | `develop` | `develop` | One block of work. |
| `release/<version>` | `develop` | `main` and `develop` | Version bump and final docs; fixes only. |
| `hotfix/<name>` | `main` | `main` and `develop` | Urgent fix against a release. |

Commits follow [Conventional Commits](https://www.conventionalcommits.org)
(`feat:`, `fix:`, `test:`, `refactor:`, `chore:`, `docs:`), written in English
and in the imperative, with a body explaining *why* when it is not obvious.

## Claude Code

`integrations/claude-code/` holds a skill that teaches Claude Code to run `tomd`
on a binary document instead of trying to read its bytes, plus a block to paste
into `~/.claude/CLAUDE.md`. See the README there.

## Not in v1

Azure Document Intelligence, LLM image descriptions, Docker, authentication, a
database, persistent history in the web UI, and remote URLs.
