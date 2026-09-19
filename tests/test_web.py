"""Tests for the local web UI."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import SENTINEL
from tomd import config, web


@pytest.fixture
def client() -> TestClient:
    """Return a client over an app instance built for this test."""
    return TestClient(web.create_app())


@pytest.fixture
def temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every temporary file the server makes into an observable directory."""
    root = tmp_path / "server-temp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def test_index_serves_the_single_page(client: TestClient) -> None:
    # Arrange / Act
    response = client.get("/")

    # Assert
    assert response.status_code == 200
    assert "<title>tomd</title>" in response.text
    assert "Drop to convert" in response.text


def test_uploading_a_valid_file_returns_its_markdown(client: TestClient, sample_pdf: Path) -> None:
    # Arrange
    payload = {"file": (sample_pdf.name, sample_pdf.read_bytes(), "application/pdf")}

    # Act
    response = client.post("/api/convert", files=payload)

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert SENTINEL in body["markdown"]
    assert body["words"] > 0
    assert body["name"] == "sample.pdf"


def test_uploading_a_corrupt_file_reports_the_error_without_failing_the_request(
    client: TestClient, corrupt_pdf: Path
) -> None:
    # Arrange
    payload = {"file": (corrupt_pdf.name, corrupt_pdf.read_bytes(), "application/pdf")}

    # Act
    response = client.post("/api/convert", files=payload)

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is not None
    assert body["markdown"] == ""


def test_uploading_beyond_the_limit_is_rejected_with_a_readable_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv(config.ENV_MAX_UPLOAD_BYTES, str(2 * 1024 * 1024))
    oversized = b"x" * (3 * 1024 * 1024)

    # Act
    response = client.post("/api/convert", files={"file": ("huge.txt", oversized, "text/plain")})

    # Assert
    assert response.status_code == 413
    assert "larger than the 2 MB upload limit" in response.json()["detail"]


def test_a_file_at_the_limit_is_still_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv(config.ENV_MAX_UPLOAD_BYTES, str(1024))
    exact = b"item,quantity\n" + b"a,1\n" * 50

    # Act
    response = client.post("/api/convert", files={"file": ("small.csv", exact, "text/csv")})

    # Assert
    assert response.status_code == 200
    assert len(exact) <= 1024


def test_temporary_files_are_removed_after_a_successful_request(
    client: TestClient, sample_pdf: Path, temp_root: Path
) -> None:
    # Arrange
    payload = {"file": (sample_pdf.name, sample_pdf.read_bytes(), "application/pdf")}

    # Act
    response = client.post("/api/convert", files=payload)

    # Assert
    assert response.status_code == 200
    assert list(temp_root.iterdir()) == []


def test_temporary_files_are_removed_after_a_rejected_upload(
    client: TestClient, temp_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv(config.ENV_MAX_UPLOAD_BYTES, "1024")

    # Act
    response = client.post("/api/convert", files={"file": ("huge.txt", b"x" * 4096, "text/plain")})

    # Assert
    assert response.status_code == 413
    assert list(temp_root.iterdir()) == []


def test_limits_endpoint_reports_the_configured_ceiling(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv(config.ENV_MAX_UPLOAD_BYTES, "4096")

    # Act
    response = client.get("/api/limits")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"max_upload_bytes": 4096}


def test_bundle_returns_a_zip_holding_every_document(client: TestClient) -> None:
    # Arrange
    documents = [
        {"name": "first.md", "markdown": "# first\n"},
        {"name": "second.md", "markdown": "# second\n"},
    ]

    # Act
    response = client.post("/api/bundle", json={"documents": documents})

    # Assert
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["first.md", "second.md"]
        assert archive.read("second.md").decode() == "# second\n"


def test_bundle_flattens_names_that_try_to_escape_the_archive(client: TestClient) -> None:
    # Arrange
    documents = [{"name": "../../etc/passwd.md", "markdown": "# nope\n"}]

    # Act
    response = client.post("/api/bundle", json={"documents": documents})

    # Assert
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["passwd.md"]


def test_bundle_rejects_an_empty_request(client: TestClient) -> None:
    # Arrange / Act
    response = client.post("/api/bundle", json={"documents": []})

    # Assert
    assert response.status_code == 422


def test_the_app_mounts_no_cors_middleware() -> None:
    # Arrange
    app = web.create_app()

    # Act
    names = [str(middleware.cls) for middleware in app.user_middleware]

    # Assert
    assert not any("CORSMiddleware" in name for name in names)
