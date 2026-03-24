"""REST and WebSocket API endpoints for the gateway.

Read endpoints serve persisted scan data.  Write operations happen via the
gRPC Reporting servicer (engine push model, ADR-020).  The ``WS /ws/session``
endpoint bridges the browser to Primary's FixSession gRPC stream for the
full scan + fix lifecycle (ADR-029).
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Query, WebSocket

from apme_gateway.api.schemas import (
    AiAcceptanceEntry,
    AiModelInfo,
    ComponentHealth,
    FixRateEntry,
    HealthStatus,
    LogEntry,
    PaginatedResponse,
    ProposalDetail,
    ScanDetail,
    ScanSummary,
    SessionDetail,
    SessionSummary,
    TopViolation,
    TrendPoint,
    ViolationDetail,
)
from apme_gateway.db import get_session
from apme_gateway.db import queries as q
from apme_gateway.db.models import Scan

router = APIRouter(prefix="/api/v1")


_UPSTREAM_SERVICES: list[tuple[str, str, str]] = [
    ("Primary Orchestrator", "APME_PRIMARY_ADDRESS", "127.0.0.1:50051"),
    ("Native Validator", "NATIVE_GRPC_ADDRESS", "127.0.0.1:50055"),
    ("OPA Validator", "OPA_GRPC_ADDRESS", "127.0.0.1:50054"),
    ("Ansible Validator", "ANSIBLE_GRPC_ADDRESS", "127.0.0.1:50053"),
    ("Gitleaks Validator", "GITLEAKS_GRPC_ADDRESS", "127.0.0.1:50056"),
    ("Galaxy Proxy", "APME_GALAXY_PROXY_URL", "http://127.0.0.1:8765"),
    ("Abbenay AI", "APME_ABBENAY_ADDR", "127.0.0.1:50057"),
]


async def _probe_grpc(address: str) -> bool:
    """Probe a gRPC service via the standard health check service.

    Returns ``True`` if the health check succeeds **or** the service
    responds with ``UNIMPLEMENTED`` (reachable but no health service).

    Args:
        address: ``host:port`` of the gRPC service.

    Returns:
        True if the service is reachable.
    """
    import grpc.aio

    channel = grpc.aio.insecure_channel(address)
    try:
        try:
            from grpc_health.v1 import health_pb2, health_pb2_grpc

            stub = health_pb2_grpc.HealthStub(channel)
            await stub.Check(health_pb2.HealthCheckRequest(), timeout=2)
            return True
        except grpc.aio.AioRpcError as e:
            return e.code() == grpc.StatusCode.UNIMPLEMENTED
        except Exception:
            return False
    finally:
        await channel.close(grace=None)


async def _probe_http(url: str) -> bool:
    """Probe an HTTP service via a simple GET.

    Args:
        url: Base URL (e.g. ``http://127.0.0.1:8765``).

    Returns:
        True if the service responds with a non-server-error status (< 500).
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(url.rstrip("/") + "/simple/")
            return bool(resp.status_code < 500)
    except Exception:
        return False


async def _check_component(name: str, env_var: str, default: str) -> ComponentHealth:
    """Check a single upstream component.

    Args:
        name: Display name for the component.
        env_var: Environment variable holding the address.
        default: Default address if env var is not set.

    Returns:
        ComponentHealth with probed status.
    """
    address = os.environ.get(env_var, "").strip() or default
    if address.startswith("http"):
        ok = await _probe_http(address)
    else:
        ok = await _probe_grpc(address)
    return ComponentHealth(
        name=name,
        status="ok" if ok else "unavailable",
        address=address,
    )


@router.get("/health")  # type: ignore[untyped-decorator]
async def health() -> HealthStatus:
    """Check gateway health including database and upstream services.

    Returns:
        HealthStatus with overall, database, and per-component statuses.
    """
    db_ok = True
    try:
        async with get_session() as db:
            await q.session_count(db)
    except Exception:
        db_ok = False

    components = await asyncio.gather(
        *(_check_component(name, env_var, default) for name, env_var, default in _UPSTREAM_SERVICES)
    )
    component_list = list(components)

    all_ok = db_ok and all(c.status == "ok" for c in component_list)

    return HealthStatus(
        status="ok" if all_ok else "degraded",
        database="ok" if db_ok else "unavailable",
        components=component_list,
    )


@router.get("/ai/models")  # type: ignore[untyped-decorator]
async def list_ai_models() -> list[AiModelInfo]:
    """Return AI models available from the Abbenay daemon via Primary.

    Calls the Primary's ``ListAIModels`` gRPC method and translates the
    response to JSON.  Returns an empty list when Primary or Abbenay is
    unreachable (graceful degradation).

    Returns:
        List of available AI models.
    """
    import grpc.aio  # noqa: PLC0415

    from apme.v1 import primary_pb2, primary_pb2_grpc  # noqa: PLC0415

    primary_addr = os.environ.get("APME_PRIMARY_ADDRESS", "").strip() or "127.0.0.1:50051"
    channel = grpc.aio.insecure_channel(primary_addr)
    try:
        stub = primary_pb2_grpc.PrimaryStub(channel)  # type: ignore[no-untyped-call]
        resp = await stub.ListAIModels(primary_pb2.ListAIModelsRequest(), timeout=5)
        return [AiModelInfo(id=m.id, provider=m.provider, name=m.name) for m in resp.models]
    except Exception:
        return []
    finally:
        await channel.close(grace=None)


@router.get("/sessions")  # type: ignore[untyped-decorator]
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    """List sessions ordered by most recently seen.

    Args:
        limit: Page size.
        offset: Row offset.

    Returns:
        Paginated list of sessions.
    """
    async with get_session() as db:
        total = await q.session_count(db)
        rows = await q.list_sessions(db, limit=limit, offset=offset)
    items = [
        SessionSummary(
            session_id=s.session_id,
            project_path=s.project_path,
            first_seen=s.first_seen,
            last_seen=s.last_seen,
        )
        for s in rows
    ]
    return PaginatedResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/sessions/{session_id}")  # type: ignore[untyped-decorator]
async def get_session_detail(session_id: str) -> SessionDetail:
    """Fetch a session and its scans.

    Args:
        session_id: Deterministic session hash.

    Returns:
        Session with embedded scan list.

    Raises:
        HTTPException: 404 if session not found.
    """
    async with get_session() as db:
        sess = await q.get_session(db, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(
        session_id=sess.session_id,
        project_path=sess.project_path,
        first_seen=sess.first_seen,
        last_seen=sess.last_seen,
        scans=[_scan_to_summary(s) for s in sess.scans],
    )


@router.get("/scans")  # type: ignore[untyped-decorator]
async def list_scans(
    session_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    """List scans, optionally filtered by session.

    Args:
        session_id: Optional session filter.
        limit: Page size.
        offset: Row offset.

    Returns:
        Paginated list of scans.
    """
    async with get_session() as db:
        total = await q.scan_count(db, session_id=session_id)
        rows = await q.list_scans(db, session_id=session_id, limit=limit, offset=offset)
    items = [_scan_to_summary(s) for s in rows]
    return PaginatedResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/scans/{scan_id}")  # type: ignore[untyped-decorator]
async def get_scan_detail(scan_id: str) -> ScanDetail:
    """Fetch a scan with violations, proposals, and logs.

    Args:
        scan_id: UUID of the scan.

    Returns:
        Full scan detail.

    Raises:
        HTTPException: 404 if scan not found.
    """
    async with get_session() as db:
        scan = await q.get_scan(db, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return ScanDetail(
        scan_id=scan.scan_id,
        session_id=scan.session_id,
        project_path=scan.project_path,
        source=scan.source,
        created_at=scan.created_at,
        scan_type=scan.scan_type,
        total_violations=scan.total_violations,
        auto_fixable=scan.auto_fixable,
        ai_candidate=scan.ai_candidate,
        manual_review=scan.manual_review,
        fixed_count=scan.fixed_count,
        diagnostics_json=scan.diagnostics_json,
        violations=[
            ViolationDetail(
                id=v.id,
                rule_id=v.rule_id,
                level=v.level,
                message=v.message,
                file=v.file,
                line=v.line,
                path=v.path,
                remediation_class=v.remediation_class,
                scope=v.scope,
            )
            for v in scan.violations
        ],
        proposals=[
            ProposalDetail(
                id=p.id,
                proposal_id=p.proposal_id,
                rule_id=p.rule_id,
                file=p.file,
                tier=p.tier,
                confidence=p.confidence,
                status=p.status,
            )
            for p in scan.proposals
        ],
        logs=[
            LogEntry(
                id=lg.id,
                message=lg.message,
                phase=lg.phase,
                progress=lg.progress,
                level=lg.level,
            )
            for lg in scan.logs
        ],
    )


@router.delete("/scans/{scan_id}", status_code=204)  # type: ignore[untyped-decorator]
async def delete_scan(scan_id: str) -> None:
    """Delete a scan and its related data.

    Args:
        scan_id: UUID of the scan to delete.

    Raises:
        HTTPException: 404 if scan not found.
    """
    async with get_session() as db:
        deleted = await q.delete_scan(db, scan_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scan not found")


@router.get("/violations/top")  # type: ignore[untyped-decorator]
async def top_violations(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[TopViolation]:
    """Return the most frequently violated rules across all scans.

    Args:
        limit: Maximum number of rules to return.

    Returns:
        List of rules sorted by violation count descending.
    """
    async with get_session() as db:
        rows = await q.top_violations(db, limit=limit)
    return [TopViolation(rule_id=rule_id, count=count) for rule_id, count in rows]


@router.get("/sessions/{session_id}/trend")  # type: ignore[untyped-decorator]
async def session_trend_endpoint(session_id: str) -> list[TrendPoint]:
    """Return violation trend for a session over time.

    Args:
        session_id: Deterministic session hash.

    Returns:
        List of trend data points.

    Raises:
        HTTPException: 404 if session not found.
    """
    async with get_session() as db:
        sess = await q.get_session(db, session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found")
        scans = await q.session_trend(db, session_id)
    return [
        TrendPoint(
            scan_id=s.scan_id,
            created_at=s.created_at,
            total_violations=s.total_violations,
            auto_fixable=s.auto_fixable,
            scan_type=s.scan_type,
        )
        for s in scans
    ]


@router.get("/stats/fix-rates")  # type: ignore[untyped-decorator]
async def fix_rates_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[FixRateEntry]:
    """Return most frequently violated rules in fix scans.

    Args:
        limit: Maximum number of rules to return.

    Returns:
        List of rules sorted by fix count descending.
    """
    async with get_session() as db:
        rows = await q.fix_rates(db, limit=limit)
    return [FixRateEntry(rule_id=rule_id, fix_count=count) for rule_id, count in rows]


@router.get("/stats/ai-acceptance")  # type: ignore[untyped-decorator]
async def ai_acceptance_endpoint() -> list[AiAcceptanceEntry]:
    """Return per-rule AI proposal acceptance statistics.

    Returns:
        List of rules with approval/rejection counts and confidence.
    """
    async with get_session() as db:
        rows = await q.ai_acceptance(db)
    return [
        AiAcceptanceEntry(
            rule_id=rule_id,
            approved=approved,
            rejected=rejected,
            pending=pending,
            avg_confidence=round(avg_conf, 3),
        )
        for rule_id, approved, rejected, pending, avg_conf in rows
    ]


def _scan_to_summary(scan: Scan) -> ScanSummary:
    """Convert an ORM Scan to a ScanSummary response model.

    Args:
        scan: ORM Scan instance.

    Returns:
        Pydantic ScanSummary.
    """
    return ScanSummary(
        scan_id=scan.scan_id,
        session_id=scan.session_id,
        project_path=scan.project_path,
        source=scan.source,
        created_at=scan.created_at,
        scan_type=scan.scan_type,
        total_violations=scan.total_violations,
        auto_fixable=scan.auto_fixable,
        ai_candidate=scan.ai_candidate,
        manual_review=scan.manual_review,
        fixed_count=scan.fixed_count,
    )


# ── Session WebSocket (ADR-028 / ADR-029) ────────────────────────────


@router.websocket("/ws/session")  # type: ignore[untyped-decorator]
async def session_ws(
    websocket: WebSocket,
    resume: str | None = None,
    scan_id: str | None = None,
) -> None:
    """Bidirectional WebSocket bridge to Primary's FixSession gRPC stream.

    Handles the full scan + fix lifecycle: file upload, real-time progress,
    Tier 1 auto-fix results, AI proposal delivery, interactive approval,
    and final session results — all over a single connection.

    Pass ``?resume=<session_id>&scan_id=<scan_id>`` to reconnect to an
    existing session (e.g. after a dropped WebSocket during proposal review).

    Args:
        websocket: Incoming WebSocket connection.
        resume: Optional session ID to resume instead of starting fresh.
        scan_id: Original scan_id to preserve on reconnect.
    """
    from apme_gateway.config import load_config
    from apme_gateway.session_client import handle_session

    await websocket.accept()

    cfg = load_config()
    await handle_session(
        websocket,
        cfg.primary_address,
        resume_session_id=resume,
        resume_scan_id=scan_id if resume else None,
    )
