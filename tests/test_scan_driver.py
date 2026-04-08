"""Unit tests for the gateway project scan driver (ADR-037)."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apme.v1 import primary_pb2
from apme_gateway.scan.driver import (
    clone_repo,
    derive_session_id,
    fetch_remote_head,
    get_clone_head,
    run_project_scan,
)


def test_derive_session_id_deterministic() -> None:
    """Same project ID always produces the same session ID."""
    sid1 = derive_session_id("project-abc")
    sid2 = derive_session_id("project-abc")
    assert sid1 == sid2
    assert len(sid1) == 16


def test_derive_session_id_different_projects() -> None:
    """Different project IDs produce different session IDs."""
    sid1 = derive_session_id("project-a")
    sid2 = derive_session_id("project-b")
    assert sid1 != sid2


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_clone_repo_success() -> None:
    """Verify clone_repo succeeds when git returns 0."""
    with patch("apme_gateway.scan.driver.asyncio.get_running_loop") as mock_loop:
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        mock_loop.return_value.run_in_executor = AsyncMock(return_value=result)

        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "repo")
            await clone_repo("https://github.com/test/repo.git", "main", dest)


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_clone_repo_failure() -> None:
    """Verify clone_repo raises RuntimeError when git fails."""
    with patch("apme_gateway.scan.driver.asyncio.get_running_loop") as mock_loop:
        result = MagicMock()
        result.returncode = 128
        result.stderr = "fatal: repository not found"
        mock_loop.return_value.run_in_executor = AsyncMock(return_value=result)

        with tempfile.TemporaryDirectory() as td:
            dest = os.path.join(td, "repo")
            with pytest.raises(RuntimeError, match="git clone failed"):
                await clone_repo("https://github.com/bad/repo.git", "main", dest)


async def _async_iter(
    items: list[object],
) -> AsyncIterator[object]:
    """Wrap items into an async iterator for mocking gRPC streams.

    Args:
        items: Objects to yield.

    Yields:
        object: Each item in sequence.
    """
    for item in items:
        yield item


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_run_project_scan_full_flow() -> None:
    """Verify run_project_scan clones, chunks, and streams FixSession (check mode)."""
    mock_chunks = [primary_pb2.ScanChunk(last=True, scan_id="test-scan")]

    progress_events: list[object] = []

    async def track_progress(event: object) -> None:
        progress_events.append(event)

    with (
        patch("apme_gateway.scan.driver.clone_repo", new_callable=AsyncMock) as mock_clone,
        patch("apme_gateway.scan.driver.get_clone_head", return_value="abc123def456" * 4),
        patch("apme_gateway.scan.driver.yield_scan_chunks", return_value=mock_chunks),
        patch("apme_gateway.scan.driver.grpc.aio.insecure_channel") as mock_channel_cls,
    ):
        mock_report = MagicMock()
        mock_report.fixed = 0
        mock_report.remaining_ai = 0
        mock_report.remaining_manual = 0

        mock_result = MagicMock()
        mock_result.report = mock_report
        mock_result.remaining_violations = []

        mock_event = MagicMock()
        mock_event.WhichOneof.return_value = "result"
        mock_event.result = mock_result

        mock_stub = MagicMock()
        mock_stub.FixSession.return_value = _async_iter([mock_event])

        mock_channel = MagicMock()
        mock_channel.close = AsyncMock()
        mock_channel_cls.return_value = mock_channel

        with patch(
            "apme_gateway.scan.driver.primary_pb2_grpc.PrimaryStub",
            return_value=mock_stub,
        ):
            scan_id, result, commit_sha = await run_project_scan(
                project_id="test-proj",
                repo_url="https://github.com/test/repo.git",
                branch="main",
                primary_address="127.0.0.1:50051",
                progress_callback=track_progress,
            )

        mock_clone.assert_called_once()
        assert scan_id is not None
        assert len(scan_id) == 32
        assert result is not None
        assert commit_sha == "abc123def456" * 4


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_fetch_remote_head_success() -> None:
    """Verify fetch_remote_head returns SHA from ls-remote output."""
    fake_sha = "a" * 40
    with patch("apme_gateway.scan.driver.asyncio.get_running_loop") as mock_loop:
        result = MagicMock()
        result.returncode = 0
        result.stdout = f"{fake_sha}\trefs/heads/main\n"
        mock_loop.return_value.run_in_executor = AsyncMock(return_value=result)

        sha = await fetch_remote_head("https://github.com/test/repo.git", "main")
        assert sha == fake_sha


@pytest.mark.asyncio  # type: ignore[untyped-decorator]
async def test_fetch_remote_head_non_https_returns_none() -> None:
    """Verify non-https URLs are rejected."""
    sha = await fetch_remote_head("ssh://git@github.com/test/repo.git", "main")
    assert sha is None


def test_get_clone_head_returns_sha() -> None:
    """Verify get_clone_head reads HEAD from a real git init."""
    with tempfile.TemporaryDirectory() as td:
        import subprocess

        subprocess.run(["git", "init", td], check=True, capture_output=True)  # noqa: S603, S607
        subprocess.run(  # noqa: S603, S607
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@test",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            check=True,
            capture_output=True,
            cwd=td,
        )
        sha = get_clone_head(td)
        assert sha is not None
        assert len(sha) == 40


def test_get_clone_head_invalid_dir_returns_none() -> None:
    """Verify get_clone_head returns None for a non-git directory."""
    with tempfile.TemporaryDirectory() as td:
        sha = get_clone_head(td)
        assert sha is None
