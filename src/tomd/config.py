"""Every tunable value of tomd, in one place.

Settings that may change per invocation are exposed as functions rather than
module constants: the environment is read at call time so that a test (or a
shell that exports a variable mid-session) sees the change without having to
reload the module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

#: Interface the web UI binds to. Deliberately not configurable: tomd converts
#: whatever it is handed, with no authentication, so it must stay loopback-only.
WEB_HOST: Final = "127.0.0.1"

#: Default TCP port for ``tomd serve``.
DEFAULT_PORT: Final = 8765

#: Default per-file upload ceiling for the web UI, in bytes.
DEFAULT_MAX_UPLOAD_BYTES: Final = 100 * 1024 * 1024

#: Marker written into the YAML front matter of every generated document.
TOOL_NAME: Final = "tomd"

#: Environment variable names, gathered so they can be documented and tested.
ENV_CACHE_DIR: Final = "TOMD_CACHE_DIR"
ENV_OUT_DIR: Final = "TOMD_OUT_DIR"
ENV_PORT: Final = "TOMD_PORT"
ENV_MAX_UPLOAD_BYTES: Final = "TOMD_MAX_UPLOAD_BYTES"


def cache_dir() -> Path:
    """Return the directory holding cached conversions.

    Returns:
        ``$TOMD_CACHE_DIR`` when set, otherwise ``~/.cache/tomd``. The path is
        expanded but not created; the cache layer creates it on first write.
    """
    raw = os.environ.get(ENV_CACHE_DIR)
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / TOOL_NAME


def out_dir() -> Path | None:
    """Return the directory that converted Markdown is redirected to.

    Returns:
        ``$TOMD_OUT_DIR`` as a path when set, otherwise ``None``, meaning each
        document is written next to its source file.
    """
    raw = os.environ.get(ENV_OUT_DIR)
    if raw:
        return Path(raw).expanduser()
    return None


def port() -> int:
    """Return the port ``tomd serve`` listens on.

    Returns:
        ``$TOMD_PORT`` when it holds a valid integer, otherwise
        :data:`DEFAULT_PORT`. An unparseable value falls back to the default
        rather than raising, so a stale export cannot break the CLI.
    """
    return _int_from_env(ENV_PORT, DEFAULT_PORT)


def max_upload_bytes() -> int:
    """Return the per-file upload ceiling enforced by the web UI.

    Returns:
        ``$TOMD_MAX_UPLOAD_BYTES`` when it holds a valid integer, otherwise
        :data:`DEFAULT_MAX_UPLOAD_BYTES`.
    """
    return _int_from_env(ENV_MAX_UPLOAD_BYTES, DEFAULT_MAX_UPLOAD_BYTES)


def _int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
