"""Unit tests for the gateway scan initiation endpoint (POST /api/v1/scans)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from apme_gateway.app import create_app
from apme_gateway.db import close_db, init_db


@pytest.fixture(autouse=True)  # type: ignore[untyped-decorator]
async def _db(tmp_path: Path) -> AsyncIterator[None]:
    """Initialise a fresh DB per test.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Yields:
        None: Test runs between setup and teardown.
    """
    await init_db(str(tmp_path / "test.db"))
    yield
    await close_db()


@pytest.fixture  # type: ignore[untyped-decorator]
async def client() -> AsyncIterator[AsyncClient]:
    """Build an async test client for the gateway app.

    Yields:
        AsyncClient: Client bound to the ASGI app.
    """
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_progress_event(phase: str = "primary", message: str = "test", level: int = 2) -> MagicMock:
    """Build a mock ScanEvent with a progress payload.

    Args:
        phase: Progress phase name.
        message: Progress message text.
        level: Log level.

    Returns:
        Mock ScanEvent with progress fields.
    """
    event = MagicMock()
    event.WhichOneof.return_value = "progress"
    event.progress.phase = phase
    event.progress.message = message
    event.progress.level = level
    return event


def _make_result_event(
    scan_id: str = "scan-123",
    total_violations: int = 5,
    session_id: str = "sess-1",
) -> MagicMock:
    """Build a mock ScanEvent with a result payload.

    Args:
        scan_id: Scan UUID.
        total_violations: Total violation count from diagnostics.
        session_id: Session identifier.

    Returns:
        Mock ScanEvent with result fields.
    """
    event = MagicMock()
    event.WhichOneof.return_value = "result"
    event.result.scan_id = scan_id
    event.result.HasField.return_value = True
    event.result.diagnostics.total_violations = total_violations
    event.result.session_id = session_id
    event.result.violations = []
    return event


async def _mock_stream(*events: MagicMock) -> AsyncIterator[MagicMock]:
    """Yield mock events as an async iterator.

    Args:
        *events: Mock ScanEvent objects to yield.

    Yields:
        MagicMock: Each mock event in sequence.
    """
    for e in events:
        yield e
        await asyncio.sleep(0)


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_scan_streams_progress_and_result(client: AsyncClient) -> None:
    """POST /scans returns SSE stream with progress and result events.

    Args:
        client: Async test client.
    """
    progress = _make_progress_event("primary", "Scan: start", 2)
    result = _make_result_event("scan-abc", 42, "sess-1")
    mock_stream = _mock_stream(progress, result)

    with patch("apme_gateway.scan_client.grpc.aio.insecure_channel") as mock_channel_fn:
        mock_channel = AsyncMock()
        mock_channel_fn.return_value = mock_channel
        mock_stub = MagicMock()
        mock_stub.ScanStream.return_value = mock_stream
        with patch("apme_gateway.scan_client.primary_pb2_grpc.PrimaryStub", return_value=mock_stub):
            resp = await client.post(
                "/api/v1/scans",
                files=[("files", ("playbook.yml", b"---\n- hosts: all\n", "text/yaml"))],
            )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    body = resp.text
    assert "event: progress" in body
    assert '"phase":"primary"' in body or '"phase": "primary"' in body
    assert "event: result" in body
    assert "scan-abc" in body


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_scan_grpc_error_yields_error_event(client: AsyncClient) -> None:
    """When Primary is unreachable, the endpoint yields an SSE error event.

    Args:
        client: Async test client.
    """
    import grpc.aio

    with patch("apme_gateway.scan_client.grpc.aio.insecure_channel") as mock_channel_fn:
        mock_channel = AsyncMock()
        mock_channel_fn.return_value = mock_channel
        mock_stub = MagicMock()
        rpc_error = grpc.aio.AioRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
            details="Connection refused",
            debug_error_string=None,
        )
        mock_stub.ScanStream.side_effect = rpc_error
        with patch("apme_gateway.scan_client.primary_pb2_grpc.PrimaryStub", return_value=mock_stub):
            resp = await client.post(
                "/api/v1/scans",
                files=[("files", ("test.yml", b"---\n", "text/yaml"))],
            )

    assert resp.status_code == 200
    body = resp.text
    assert "event: error" in body
    assert "Connection refused" in body


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_scan_no_files_returns_422(client: AsyncClient) -> None:
    """POST /scans without files returns 422 validation error.

    Args:
        client: Async test client.
    """
    resp = await client.post("/api/v1/scans")
    assert resp.status_code == 422


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_scan_temp_dir_cleaned_up(tmp_path: Path) -> None:
    """Temp directory is removed after scan completes.

    Args:
        tmp_path: Pytest-provided temporary directory.
    """
    from apme_gateway.scan_client import UploadedFile, run_scan_stream

    result = _make_result_event("scan-cleanup", 0, "sess-1")
    mock_stream = _mock_stream(result)

    import tempfile as _tempfile

    created_dirs: list[Path] = []
    original_mkdtemp = _tempfile.mkdtemp

    def tracking_mkdtemp(**kwargs: str) -> str:
        d: str = original_mkdtemp(**kwargs)
        created_dirs.append(Path(d))
        return d

    with (
        patch("apme_gateway.scan_client.grpc.aio.insecure_channel") as mock_channel_fn,
        patch("apme_gateway.scan_client.tempfile.mkdtemp", side_effect=tracking_mkdtemp),
    ):
        mock_channel = AsyncMock()
        mock_channel_fn.return_value = mock_channel
        mock_stub = MagicMock()
        mock_stub.ScanStream.return_value = mock_stream
        with patch("apme_gateway.scan_client.primary_pb2_grpc.PrimaryStub", return_value=mock_stub):
            events = []
            async for event in run_scan_stream(
                [UploadedFile(relative_path="test.yml", content=b"---\n")],
                "localhost:50051",
            ):
                events.append(event)

    assert len(created_dirs) == 1
    assert not created_dirs[0].exists(), "Temp dir should be cleaned up"
