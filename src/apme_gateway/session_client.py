"""Gateway session client — WebSocket-to-FixSession gRPC bridge.

Replaces the SSE-based scan_client with a bidirectional WebSocket
transport that maps onto Primary's FixSession gRPC stream (ADR-028/029).
Supports both scan-only (enable_ai=false) and interactive fix sessions
with AI proposal approval.

Protocol (browser -> gateway, JSON over WS)::

    {"type": "start",      "options": {...}}
    {"type": "file",       "path": "...", "content": "<base64>"}
    {"type": "files_done"}
    {"type": "approve",    "approved_ids": ["id1", ...]}
    {"type": "extend"}
    {"type": "close"}

Protocol (gateway -> browser, JSON over WS)::

    {"type": "session_created", "session_id": "...", "ttl_seconds": N}
    {"type": "progress",        "phase": "...", "message": "...", "level": N}
    {"type": "tier1_complete",   ...}
    {"type": "proposals",        "proposals": [...], "tier": N}
    {"type": "approval_ack",     "applied_count": N, "status": "..."}
    {"type": "result",           ...}
    {"type": "error",            "message": "..."}
    {"type": "closed"}
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import grpc
import grpc.aio
from fastapi import WebSocket, WebSocketDisconnect
from google.protobuf.json_format import MessageToDict

from apme.v1 import primary_pb2_grpc
from apme.v1.primary_pb2 import (
    ApprovalRequest,
    CloseRequest,
    ExtendRequest,
    FixOptions,
    ScanChunk,
    SessionCommand,
)
from apme_engine.daemon.chunked_fs import yield_scan_chunks

logger = logging.getLogger(__name__)

_SESSION_TIMEOUT_S = 600

_STATUS_NAMES: dict[int, str] = {
    0: "SESSION_STATUS_UNSPECIFIED",
    1: "AWAITING_APPROVAL",
    2: "PROCESSING",
    3: "COMPLETE",
}


def _sanitize_path(relative_path: str) -> str:
    """Sanitize a user-provided relative path to prevent directory traversal.

    Args:
        relative_path: Raw path from the upload filename.

    Returns:
        Sanitized relative path string.

    Raises:
        ValueError: If the path contains ``..`` components.
    """
    cleaned = PurePosixPath(relative_path.replace("\\", "/"))
    parts = [p for p in cleaned.parts if p not in ("/", "\\")]
    if ".." in parts:
        raise ValueError(f"Path traversal detected: {relative_path!r}")
    return str(PurePosixPath(*parts)) if parts else "unnamed"


def _status_name(status: int) -> str:
    """Convert SessionStatus enum int to its proto name.

    Args:
        status: Integer value of the SessionStatus enum.

    Returns:
        Human-readable status name.
    """
    return _STATUS_NAMES.get(status, "UNKNOWN")


async def _collect_uploads(ws: WebSocket, temp_dir: Path) -> dict[str, Any]:
    """Read start/file/files_done messages and write files to *temp_dir*.

    Args:
        ws: Active WebSocket connection.
        temp_dir: Directory to write uploaded files into.

    Returns:
        Options dict from the ``start`` message.

    Raises:
        ValueError: If no files were received before ``files_done``.
    """
    options: dict[str, Any] = {}
    files_received = 0

    while True:
        msg = await ws.receive_json()
        msg_type = msg.get("type")

        if msg_type == "start":
            options = msg.get("options", {})

        elif msg_type == "file":
            safe = _sanitize_path(msg["path"])
            try:
                content = base64.b64decode(msg["content"], validate=True)
            except Exception:
                await ws.send_json(
                    {"type": "error", "message": f"Invalid base64 content for {safe}"}
                )
                continue
            dest = temp_dir / safe
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            files_received += 1

        elif msg_type == "files_done":
            break

        else:
            await ws.send_json({"type": "error", "message": f"Unexpected message during upload: {msg_type}"})

    if files_received == 0:
        raise ValueError("No files received")

    return options


async def _ws_command_reader(
    ws: WebSocket,
    queue: asyncio.Queue[SessionCommand | None],
    done: asyncio.Event,
) -> None:
    """Read interactive commands from the WebSocket and enqueue for gRPC.

    Args:
        ws: Active WebSocket connection.
        queue: Queue feeding the gRPC command stream.
        done: Event signalling the session is finished.
    """
    try:
        while not done.is_set():
            msg = await ws.receive_json()
            msg_type = msg.get("type")

            if msg_type == "approve":
                ids = msg.get("approved_ids", [])
                await queue.put(SessionCommand(approve=ApprovalRequest(approved_ids=ids)))
            elif msg_type == "extend":
                await queue.put(SessionCommand(extend=ExtendRequest()))
            elif msg_type == "close":
                await queue.put(SessionCommand(close=CloseRequest()))
                break
            else:
                logger.warning("Ignoring unknown WS command: %s", msg_type)
    except WebSocketDisconnect:
        await queue.put(SessionCommand(close=CloseRequest()))
    finally:
        await queue.put(None)


async def _command_stream(
    chunks: Iterator[ScanChunk],
    queue: asyncio.Queue[SessionCommand | None],
) -> AsyncIterator[SessionCommand]:
    """Yield upload chunks then queued interactive commands.

    Args:
        chunks: ScanChunk upload messages (consumed lazily).
        queue: Queue of interactive commands from the WebSocket reader.

    Yields:
        SessionCommand: Messages for the gRPC FixSession stream.
    """
    for chunk in chunks:
        yield SessionCommand(upload=chunk)

    while True:
        cmd = await queue.get()
        if cmd is None:
            break
        yield cmd


async def _forward_events(
    response_stream: Any,
    ws: WebSocket,
    scan_id: str,
    done: asyncio.Event,
) -> None:
    """Read SessionEvents from gRPC and forward as JSON to the WebSocket.

    Args:
        response_stream: Async iterator of gRPC SessionEvent messages.
        ws: Active WebSocket connection.
        scan_id: Scan UUID for inclusion in result messages.
        done: Event to set when the session closes.
    """
    async for event in response_stream:
        oneof = event.WhichOneof("event")

        if oneof == "created":
            await ws.send_json(
                {
                    "type": "session_created",
                    "session_id": event.created.session_id,
                    "scan_id": scan_id,
                    "ttl_seconds": event.created.ttl_seconds,
                }
            )

        elif oneof == "progress":
            p = event.progress
            await ws.send_json(
                {
                    "type": "progress",
                    "phase": p.phase,
                    "message": p.message,
                    "level": p.level,
                }
            )

        elif oneof == "tier1_complete":
            t1 = event.tier1_complete
            await ws.send_json(
                {
                    "type": "tier1_complete",
                    "idempotency_ok": t1.idempotency_ok,
                    "patches": [
                        {
                            "file": p.path,
                            "diff": p.diff,
                            "applied_rules": list(p.applied_rules),
                        }
                        for p in t1.applied_patches
                    ],
                    "format_diffs": [{"file": d.path, "diff": d.diff} for d in t1.format_diffs],
                    "report": MessageToDict(t1.report) if t1.HasField("report") else None,
                }
            )

        elif oneof == "proposals":
            pr = event.proposals
            await ws.send_json(
                {
                    "type": "proposals",
                    "tier": pr.tier,
                    "status": _status_name(pr.status),
                    "proposals": [
                        {
                            "id": p.id,
                            "file": p.file,
                            "rule_id": p.rule_id,
                            "line_start": p.line_start,
                            "line_end": p.line_end,
                            "before_text": p.before_text,
                            "after_text": p.after_text,
                            "diff_hunk": p.diff_hunk,
                            "confidence": p.confidence,
                            "explanation": p.explanation,
                            "tier": p.tier,
                        }
                        for p in pr.proposals
                    ],
                }
            )

        elif oneof == "approval_ack":
            ack = event.approval_ack
            await ws.send_json(
                {
                    "type": "approval_ack",
                    "applied_count": ack.applied_count,
                    "status": _status_name(ack.status),
                    "ttl_seconds": ack.ttl_seconds,
                }
            )

        elif oneof == "result":
            r = event.result
            await ws.send_json(
                {
                    "type": "result",
                    "scan_id": scan_id,
                    "patches": [
                        {
                            "file": p.path,
                            "diff": p.diff,
                            "applied_rules": list(p.applied_rules),
                        }
                        for p in r.patches
                    ],
                    "report": MessageToDict(r.report) if r.HasField("report") else None,
                    "remaining_violations": [
                        {
                            "rule_id": v.rule_id,
                            "level": v.level,
                            "message": v.message,
                            "file": v.file,
                        }
                        for v in r.remaining_violations
                    ],
                }
            )

        elif oneof == "expiring":
            await ws.send_json(
                {
                    "type": "expiring",
                    "ttl_seconds": event.expiring.ttl_seconds,
                }
            )

        elif oneof == "closed":
            await ws.send_json({"type": "closed"})
            done.set()
            break


async def handle_session(
    ws: WebSocket,
    primary_address: str,
    timeout: int = _SESSION_TIMEOUT_S,
) -> None:
    """Bridge a WebSocket connection to a Primary FixSession gRPC stream.

    Orchestrates the full lifecycle: file upload collection, gRPC
    FixSession initiation, bidirectional event forwarding, and cleanup.

    Args:
        ws: Accepted FastAPI WebSocket.
        primary_address: gRPC address of the Primary orchestrator.
        timeout: gRPC call timeout in seconds.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="apme-gw-session-"))
    try:
        options = await _collect_uploads(ws, temp_dir)

        ansible_version: str = options.get("ansible_version", "")
        collections: list[str] = options.get("collections", [])
        enable_ai: bool = options.get("enable_ai", True)

        scan_id = str(uuid.uuid4())

        def _chunks_with_fix_options() -> Iterator[ScanChunk]:
            chunk_iter = yield_scan_chunks(
                temp_dir,
                scan_id=scan_id,
                project_root_name="upload",
                ansible_core_version=ansible_version or None,
                collection_specs=collections or None,
            )
            first_chunk = next(chunk_iter, None)
            if first_chunk is None:
                return
            fix_opts = FixOptions(
                ansible_core_version=ansible_version,
                collection_specs=collections or [],
                enable_ai=enable_ai,
            )
            first_chunk.fix_options.CopyFrom(fix_opts)  # type: ignore[union-attr]
            yield first_chunk
            yield from chunk_iter

        command_queue: asyncio.Queue[SessionCommand | None] = asyncio.Queue()
        done = asyncio.Event()

        channel = grpc.aio.insecure_channel(primary_address)
        try:
            stub = primary_pb2_grpc.PrimaryStub(channel)  # type: ignore[no-untyped-call]

            async def _cmd_iter() -> AsyncIterator[SessionCommand]:
                async for cmd in _command_stream(_chunks_with_fix_options(), command_queue):
                    yield cmd

            response_stream = stub.FixSession(_cmd_iter(), timeout=timeout)

            reader_task = asyncio.create_task(_ws_command_reader(ws, command_queue, done))

            try:
                await _forward_events(response_stream, ws, scan_id, done)
            except grpc.aio.AioRpcError as e:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"Engine error: {e.details()}",
                    }
                )
            finally:
                done.set()
                reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await reader_task
        finally:
            await channel.close(grace=None)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during session")
    except ValueError as exc:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": str(exc)})
    except Exception as exc:
        logger.exception("Session failed: %s", exc)
        with contextlib.suppress(Exception):
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Session failed — check gateway logs",
                }
            )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
