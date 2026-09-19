"""Local web UI for tomd.

A thin HTTP layer over :func:`tomd.core.convert`: it receives uploads, writes
them to a temporary directory, converts them and throws the temporary files
away. No state survives a request, which is why the page has no history.

The server binds to loopback only and mounts no CORS middleware. tomd converts
whatever it is given without authentication, so it must not be reachable from
outside the machine.
"""

from __future__ import annotations

import io
import logging
import shutil
import tempfile
import webbrowser
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Final

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from tomd import config, core

logger = logging.getLogger(__name__)

STATIC_DIR: Final = Path(__file__).parent / "static"
INDEX_FILE: Final = STATIC_DIR / "index.html"
_UPLOAD_CHUNK: Final = 1024 * 1024


class ConversionPayload(BaseModel):
    """What the page receives for a single converted upload."""

    name: str
    markdown: str
    words: int
    chars: int
    cached: bool
    duration_ms: float
    error: str | None = None


class BundleDocument(BaseModel):
    """One document the page wants included in a zip."""

    name: str = Field(min_length=1, max_length=255)
    markdown: str


class BundleRequest(BaseModel):
    """Request body for the zip endpoint."""

    documents: list[BundleDocument] = Field(min_length=1)


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Returns:
        An app exposing the single page, the conversion endpoint and the zip
        endpoint. Built by a factory rather than at import time so tests can
        hold an independent instance.
    """
    app = FastAPI(title="tomd", docs_url=None, redoc_url=None)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        """Serve the single page."""
        return FileResponse(INDEX_FILE, media_type="text/html")

    @app.get("/api/limits")
    async def limits() -> dict[str, int]:
        """Report the upload ceiling so the page can reject files before sending."""
        return {"max_upload_bytes": config.max_upload_bytes()}

    @app.post("/api/convert")
    async def convert_upload(
        file: Annotated[UploadFile, File()],
    ) -> ConversionPayload:
        """Convert one uploaded file.

        Args:
            file: The upload. Its name is used only for the display label and
                the suffix; it never becomes a path on disk as given.

        Returns:
            A :class:`ConversionPayload`. A file that fails to convert is a 200
            with ``error`` set, not an HTTP error: the page lists it as a failed
            row beside the successful ones.

        Raises:
            HTTPException: 413 when the upload exceeds the configured ceiling.
        """
        display_name = Path(file.filename or "upload").name
        limit = config.max_upload_bytes()

        with _temporary_copy(file, display_name, limit) as staged:
            result = core.convert(staged, write=False, frontmatter=True, source_label=display_name)

        return ConversionPayload(
            name=display_name,
            markdown=result.markdown,
            words=result.words,
            chars=result.chars,
            cached=result.cached,
            duration_ms=result.duration_ms,
            error=result.error,
        )

    @app.post("/api/bundle")
    async def bundle(request: BundleRequest) -> Response:
        """Zip several converted documents for a single download.

        Args:
            request: The documents the page currently shows.

        Returns:
            A ``application/zip`` response built in memory. Names are flattened
            to their basename so a crafted name cannot escape the archive root.
        """
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for index_, document in enumerate(request.documents):
                safe = Path(document.name).name or f"document-{index_}.md"
                archive.writestr(safe, document.markdown)

        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="tomd-documents.zip"'},
        )

    return app


@contextmanager
def _temporary_copy(file: UploadFile, display_name: str, limit: int) -> Iterator[Path]:
    """Stage an upload on disk, and delete it however the request ends.

    The upload is copied in chunks and abandoned the moment it crosses the
    ceiling, so an oversized file is never fully written.
    """
    directory = Path(tempfile.mkdtemp(prefix="tomd-upload-"))
    try:
        staged = directory / display_name
        written = 0
        with staged.open("wb") as handle:
            while chunk := file.file.read(_UPLOAD_CHUNK):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"{display_name} is larger than the "
                            f"{limit // (1024 * 1024)} MB upload limit"
                        ),
                    )
                handle.write(chunk)
        yield staged
    finally:
        shutil.rmtree(directory, ignore_errors=True)


app = create_app()


def serve(port: int | None = None, *, open_browser: bool = True) -> None:
    """Run the web UI until interrupted.

    Args:
        port: TCP port; defaults to ``$TOMD_PORT`` or 8765.
        open_browser: Point the default browser at the page once it is up.
    """
    chosen = port if port is not None else config.port()
    url = f"http://{config.WEB_HOST}:{chosen}"
    if open_browser:
        webbrowser.open(url)
    logger.info("serving tomd at %s", url)
    uvicorn.run(app, host=config.WEB_HOST, port=chosen, log_level="warning")
