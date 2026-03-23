"""Gateway scan client — translates uploaded files into a Primary.ScanStream call.

The gateway acts as a "CLI without a terminal" (ADR-029): it writes uploaded
files to a temp directory, constructs ``ScanChunk`` messages via the shared
chunked_fs module, streams them to Primary, and yields SSE-formatted progress
events back to the HTTP caller.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import grpc
import grpc.aio

from apme.v1 import primary_pb2_grpc
from apme_engine.daemon.chunked_fs import yield_scan_chunks


@dataclass
class UploadedFile:
    """A file received from the browser upload.

    Attributes:
        relative_path: Relative path preserving directory structure.
        content: Raw file bytes.
    """

    relative_path: str
    content: bytes


def _sse(event: str, data: dict[str, object]) -> str:
    """Format a single SSE message.

    Args:
        event: SSE event type (progress, result, error).
        data: JSON-serializable payload.

    Returns:
        SSE-formatted string with trailing blank line.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def run_scan_stream(
    files: list[UploadedFile],
    primary_address: str,
    *,
    ansible_version: str = "",
    collections: list[str] | None = None,
    timeout: int = 300,
) -> AsyncIterator[str]:
    """Stream a scan through Primary and yield SSE events.

    Writes uploaded files to a temp directory, constructs ``ScanChunk``
    messages, calls ``Primary.ScanStream``, and yields SSE-formatted
    strings for each ``ScanEvent``.

    Args:
        files: Uploaded files from the browser.
        primary_address: gRPC address of the Primary orchestrator.
        ansible_version: Optional Ansible core version constraint.
        collections: Optional collection specifiers.
        timeout: gRPC call timeout in seconds.

    Yields:
        str: SSE-formatted event strings.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="apme-gw-scan-"))
    try:
        for f in files:
            dest = temp_dir / f.relative_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.content)

        chunks = list(
            yield_scan_chunks(
                temp_dir,
                project_root_name="upload",
                ansible_core_version=ansible_version or None,
                collection_specs=collections,
            )
        )

        channel = grpc.aio.insecure_channel(primary_address)
        try:
            stub = primary_pb2_grpc.PrimaryStub(channel)  # type: ignore[no-untyped-call]
            response_stream = stub.ScanStream(iter(chunks), timeout=timeout)

            scan_id: str | None = None
            async for event in response_stream:
                oneof = event.WhichOneof("event")
                if oneof == "progress":
                    p = event.progress
                    yield _sse(
                        "progress",
                        {"phase": p.phase, "message": p.message, "level": p.level},
                    )
                    await asyncio.sleep(0)
                elif oneof == "result":
                    resp = event.result
                    scan_id = resp.scan_id
                    yield _sse(
                        "result",
                        {
                            "scan_id": resp.scan_id,
                            "total_violations": resp.diagnostics.total_violations
                            if resp.HasField("diagnostics")
                            else len(resp.violations),
                            "session_id": resp.session_id,
                        },
                    )
            if scan_id is None:
                yield _sse("error", {"message": "No scan result received from engine"})
        except grpc.aio.AioRpcError as e:
            yield _sse("error", {"message": f"Engine error: {e.details()}"})
        finally:
            await channel.close(grace=None)
    except Exception as exc:
        yield _sse("error", {"message": str(exc)})
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
