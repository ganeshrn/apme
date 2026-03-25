"""REST and WebSocket API endpoints for the gateway (ADR-029, ADR-037).

Read endpoints serve persisted scan data.  Write operations happen via the
gRPC Reporting servicer (engine push model, ADR-020).  The ``WS /ws/session``
endpoint bridges the browser to Primary's FixSession gRPC stream for the
playground scan + fix lifecycle (ADR-029).  Project operations use the new
``WS /projects/{id}/ws/operate`` endpoint (ADR-037).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid

from fastapi import APIRouter, HTTPException, Query, WebSocket
from starlette.websockets import WebSocketDisconnect  # type: ignore[import-not-found]

from apme_gateway.api.schemas import (
    AiAcceptanceEntry,
    AiModelInfo,
    ComponentHealth,
    CreateProjectRequest,
    DashboardSummary,
    FixRateEntry,
    HealthStatus,
    LogEntry,
    PaginatedResponse,
    ProjectDetail,
    ProjectRanking,
    ProjectSummary,
    ProposalDetail,
    ScanDetail,
    ScanSummary,
    SessionDetail,
    SessionSummary,
    TopViolation,
    TrendPoint,
    UpdateProjectRequest,
    ViolationDetail,
)
from apme_gateway.db import get_session
from apme_gateway.db import queries as q
from apme_gateway.db.models import Scan

logger = logging.getLogger(__name__)

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


# ── Project CRUD (ADR-037) ───────────────────────────────────────────


@router.post("/projects", status_code=201)  # type: ignore[untyped-decorator]
async def create_project(body: CreateProjectRequest) -> ProjectSummary:
    """Create a new project.

    Args:
        body: Project creation payload.

    Returns:
        Newly created project summary.
    """
    project_id = uuid.uuid4().hex
    async with get_session() as db:
        proj = await q.create_project(
            db,
            project_id=project_id,
            name=body.name,
            repo_url=body.repo_url,
            branch=body.branch,
        )
    return ProjectSummary(
        id=proj.id,
        name=proj.name,
        repo_url=proj.repo_url,
        branch=proj.branch,
        created_at=proj.created_at,
        health_score=proj.health_score,
    )


@router.get("/projects")  # type: ignore[untyped-decorator]
async def list_projects(
    sort_by: str = Query(default="created_at"),
    order: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    """List all projects with summary data.

    Args:
        sort_by: Column to sort by.
        order: Sort direction (asc or desc).
        limit: Page size.
        offset: Page offset.

    Returns:
        Paginated list of project summaries.
    """
    async with get_session() as db:
        projects = await q.list_projects(
            db,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            order=order,
        )
        total = await q.project_count(db)
        items: list[ProjectSummary] = []
        for proj in projects:
            scan_cnt = await q.project_scan_count(db, proj.id)
            trend_scans = await q.project_trend(db, proj.id, limit=5)
            last_scan_at = trend_scans[-1].created_at if trend_scans else None
            vt = _compute_violation_trend(trend_scans)
            violations = await q.project_violations(db, proj.id)
            items.append(
                ProjectSummary(
                    id=proj.id,
                    name=proj.name,
                    repo_url=proj.repo_url,
                    branch=proj.branch,
                    created_at=proj.created_at,
                    health_score=proj.health_score,
                    total_violations=len(violations),
                    violation_trend=vt,
                    scan_count=scan_cnt,
                    last_scanned_at=last_scan_at,
                )
            )
    return PaginatedResponse(total=total, limit=limit, offset=offset, items=items)


def _compute_violation_trend(scans: list[Scan]) -> str:
    """Derive a trend direction from recent scan violation counts.

    Args:
        scans: Recent Scan ORM objects ordered oldest-first (asc).

    Returns:
        One of ``"improving"``, ``"declining"``, or ``"stable"``.
    """
    if len(scans) < 2:
        return "stable"
    counts = [s.total_violations for s in scans]
    if counts[-1] < counts[0]:
        return "improving"
    if counts[-1] > counts[0]:
        return "declining"
    return "stable"


@router.get("/projects/{project_id}")  # type: ignore[untyped-decorator]
async def get_project_detail(project_id: str) -> ProjectDetail:
    """Fetch a project with latest scan info.

    Args:
        project_id: Project UUID.

    Returns:
        Full project detail.

    Raises:
        HTTPException: 404 if project not found.
    """
    async with get_session() as db:
        proj = await q.get_project(db, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        violations = await q.project_violations(db, project_id)
        trend = await q.project_trend(db, project_id, limit=5)
        scan_cnt = await q.project_scan_count(db, project_id)
        scans = await q.project_scans(db, project_id, limit=1)
        latest = scans[0] if scans else None
        severity: dict[str, int] = {}
        for v in violations:
            severity[v.level] = severity.get(v.level, 0) + 1
    latest_summary = _scan_to_summary(latest) if latest else None
    vt = _compute_violation_trend(trend)
    last_scan_at = trend[-1].created_at if trend else None
    return ProjectDetail(
        id=proj.id,
        name=proj.name,
        repo_url=proj.repo_url,
        branch=proj.branch,
        created_at=proj.created_at,
        health_score=proj.health_score,
        total_violations=len(violations),
        violation_trend=vt,
        scan_count=scan_cnt,
        last_scanned_at=last_scan_at,
        latest_scan=latest_summary,
        severity_breakdown=severity,
    )


@router.patch("/projects/{project_id}")  # type: ignore[untyped-decorator]
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
) -> ProjectSummary:
    """Update project metadata.

    Args:
        project_id: Project UUID.
        body: Fields to update.

    Returns:
        Updated project summary.

    Raises:
        HTTPException: 400 if no fields provided, 404 if not found.
    """
    updates: dict[str, str] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.repo_url is not None:
        updates["repo_url"] = body.repo_url
    if body.branch is not None:
        updates["branch"] = body.branch
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    async with get_session() as db:
        proj = await q.update_project(db, project_id, **updates)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
    return ProjectSummary(
        id=proj.id,
        name=proj.name,
        repo_url=proj.repo_url,
        branch=proj.branch,
        created_at=proj.created_at,
        health_score=proj.health_score,
    )


@router.delete("/projects/{project_id}", status_code=204)  # type: ignore[untyped-decorator]
async def delete_project_endpoint(project_id: str) -> None:
    """Delete a project and cascade to its scans.

    Args:
        project_id: Project UUID.

    Raises:
        HTTPException: 404 if not found.
    """
    async with get_session() as db:
        ok = await q.delete_project(db, project_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Project not found")


# ── Project-scoped endpoints (ADR-037) ───────────────────────────────


@router.get("/projects/{project_id}/scans")  # type: ignore[untyped-decorator]
async def list_project_scans(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse:
    """Return scans belonging to a project.

    Args:
        project_id: Project UUID.
        limit: Page size.
        offset: Page offset.

    Returns:
        Paginated scan summaries.

    Raises:
        HTTPException: 404 if project not found.
    """
    async with get_session() as db:
        proj = await q.get_project(db, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        scans = await q.project_scans(db, project_id, limit=limit, offset=offset)
        total = await q.project_scan_count(db, project_id)
    items = [_scan_to_summary(s) for s in scans]
    return PaginatedResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/projects/{project_id}/violations")  # type: ignore[untyped-decorator]
async def list_project_violations(
    project_id: str,
    severity: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ViolationDetail]:
    """Return violations from the latest scan of a project.

    Args:
        project_id: Project UUID.
        severity: Optional severity filter.
        rule_id: Optional rule_id filter.
        limit: Maximum rows.
        offset: Rows to skip.

    Returns:
        List of violation details.

    Raises:
        HTTPException: 404 if project not found.
    """
    async with get_session() as db:
        proj = await q.get_project(db, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        violations = await q.project_violations(
            db,
            project_id,
            severity=severity,
            rule_id=rule_id,
            limit=limit,
            offset=offset,
        )
    return [
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
        for v in violations
    ]


@router.get("/projects/{project_id}/trend")  # type: ignore[untyped-decorator]
async def project_trend_endpoint(
    project_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[TrendPoint]:
    """Return violation trend for a project over time.

    Args:
        project_id: Project UUID.
        limit: Max number of data points.

    Returns:
        List of trend points ordered newest-first.

    Raises:
        HTTPException: 404 if project not found.
    """
    async with get_session() as db:
        proj = await q.get_project(db, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        trend = await q.project_trend(db, project_id, limit=limit)
    return [
        TrendPoint(
            scan_id=t.scan_id,
            created_at=t.created_at,
            total_violations=t.total_violations,
            auto_fixable=t.auto_fixable,
            scan_type=t.scan_type,
        )
        for t in trend
    ]


# ── Dashboard (ADR-037) ─────────────────────────────────────────────


@router.get("/dashboard/summary")  # type: ignore[untyped-decorator]
async def dashboard_summary_endpoint() -> DashboardSummary:
    """Return cross-project aggregate statistics.

    Returns:
        Dashboard summary with totals and averages.
    """
    async with get_session() as db:
        summary = await q.dashboard_summary(db)
    return DashboardSummary(**summary)


@router.get("/dashboard/rankings")  # type: ignore[untyped-decorator]
async def dashboard_rankings(
    sort_by: str = Query(default="health_score"),
    order: str = Query(default="desc"),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[ProjectRanking]:
    """Return ranked projects for dashboard tables.

    Args:
        sort_by: Ranking criterion.
        order: Sort direction.
        limit: Max results.

    Returns:
        Ranked list of projects.
    """
    async with get_session() as db:
        rankings = await q.project_rankings(db, sort_by=sort_by, order=order, limit=limit)
    return [ProjectRanking(**r) for r in rankings]


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


# ── Project WebSocket (ADR-037) ──────────────────────────────────────


@router.websocket("/projects/{project_id}/ws/operate")  # type: ignore[untyped-decorator]
async def project_operate_ws(
    websocket: WebSocket,
    project_id: str,
) -> None:
    """Bidirectional WebSocket for project scan/fix operations (ADR-037).

    The client sends ``{"action": "scan"|"fix", "options": {...}}`` to start
    an operation.  The gateway clones the repo, drives Primary via gRPC, and
    streams progress back over the WebSocket.

    Args:
        websocket: Incoming WebSocket connection.
        project_id: Target project UUID.
    """
    from apme_gateway.config import load_config
    from apme_gateway.scan.driver import run_project_fix, run_project_scan

    await websocket.accept()

    try:
        msg = await websocket.receive_json()
        is_fix = bool(msg.get("fix", False)) or msg.get("action") == "fix"
        options: dict[str, object] = msg.get("options", {})

        async with get_session() as db:
            proj = await q.get_project(db, project_id)
        if not proj:
            await websocket.send_json({"type": "error", "message": "Project not found"})
            return

        cfg = load_config()

        op_scan_id = uuid.uuid4().hex
        started_sent = False

        async def _progress_cb(event: object) -> None:
            """Translate gRPC protobuf events into typed WebSocket messages.

            Uses ``WhichOneof`` (SessionEvent for fix) or ``HasField``
            (ScanEvent for scan) to detect the event kind and emit the
            structured messages the frontend hooks expect.

            Args:
                event: gRPC ScanEvent or SessionEvent protobuf.
            """
            nonlocal started_sent

            kind = None
            with contextlib.suppress(Exception):
                kind = event.WhichOneof("event")  # type: ignore[attr-defined]

            async def _ensure_started() -> None:
                nonlocal started_sent
                if not started_sent:
                    started_sent = True
                    await websocket.send_json({"type": "started", "scan_id": op_scan_id})

            if kind == "progress":
                await _ensure_started()
                prog = event.progress  # type: ignore[attr-defined]
                await websocket.send_json(
                    {
                        "type": "progress",
                        "phase": prog.phase or "processing",
                        "message": prog.message or "",
                    }
                )
            elif kind == "proposals":
                await _ensure_started()
                props = event.proposals  # type: ignore[attr-defined]
                items = [
                    {
                        "id": p.id,
                        "rule_id": p.rule_id,
                        "file": p.file,
                        "tier": p.tier,
                        "confidence": p.confidence,
                        "explanation": p.explanation,
                        "diff_hunk": p.diff_hunk,
                    }
                    for p in props.proposals
                ]
                await websocket.send_json({"type": "proposals", "proposals": items})
            elif kind == "approval_ack":
                await websocket.send_json({"type": "approval_ack"})
            elif kind == "result":
                await _ensure_started()
                res = event.result  # type: ignore[attr-defined]
                summary = getattr(res, "summary", None)
                if summary is not None:
                    # ScanEvent.result → ScanResponse (has ScanSummary)
                    await websocket.send_json(
                        {
                            "type": "result",
                            "total_violations": summary.total,
                            "auto_fixable": summary.auto_fixable,
                            "ai_candidate": summary.ai_candidate,
                            "manual_review": summary.manual_review,
                        }
                    )
                else:
                    # SessionEvent.result → SessionResult (has FixReport)
                    report = getattr(res, "report", None)
                    remaining = getattr(res, "remaining_violations", [])
                    total = len(remaining) + (report.fixed if report else 0)
                    await websocket.send_json(
                        {
                            "type": "result",
                            "total_violations": total,
                            "auto_fixable": 0,
                            "ai_candidate": report.remaining_ai if report else 0,
                            "manual_review": report.remaining_manual if report else 0,
                            "fixed_count": report.fixed if report else 0,
                        }
                    )

        raw_specs = options.get("collection_specs", [])
        specs = [str(s) for s in raw_specs] if isinstance(raw_specs, list) else []

        await websocket.send_json({"type": "cloning"})

        completed_scan_id: str | None = None

        if is_fix:
            approval_queue: asyncio.Queue[list[str]] = asyncio.Queue()
            fix_result: tuple[str, object] | None = None

            async def _run_fix() -> tuple[str, object]:
                return await run_project_fix(
                    project_id=proj.id,
                    repo_url=proj.repo_url,
                    branch=proj.branch,
                    primary_address=cfg.primary_address,
                    ansible_version=str(options.get("ansible_version", "")),
                    collection_specs=specs,
                    enable_ai=bool(options.get("enable_ai", True)),
                    ai_model=str(options.get("ai_model", "")),
                    progress_callback=_progress_cb,
                    approval_queue=approval_queue,
                    scan_id=op_scan_id,
                )

            fix_task = asyncio.create_task(_run_fix())
            try:
                while not fix_task.done():
                    try:
                        client_msg = await asyncio.wait_for(
                            websocket.receive_json(),
                            timeout=1.0,
                        )
                    except TimeoutError:
                        continue

                    msg_type = client_msg.get("type", "")
                    if msg_type == "approve":
                        ids = client_msg.get("approved_ids", [])
                        approved = [str(i) for i in ids] if isinstance(ids, list) else []
                        await approval_queue.put(approved)
                    elif msg_type == "cancel":
                        fix_task.cancel()
                        break
            finally:
                if not fix_task.done():
                    fix_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    fix_result = await fix_task

            if fix_result is not None:
                completed_scan_id = fix_result[0]
        else:
            scan_id, _result = await run_project_scan(
                project_id=proj.id,
                repo_url=proj.repo_url,
                branch=proj.branch,
                primary_address=cfg.primary_address,
                ansible_version=str(options.get("ansible_version", "")),
                collection_specs=specs,
                progress_callback=_progress_cb,
                scan_id=op_scan_id,
            )
            completed_scan_id = scan_id

        if completed_scan_id:
            async with get_session() as db:
                await q.link_scan_to_project(db, completed_scan_id, proj.id, trigger="ui")
                await q.update_project_health(db, proj.id)

        await websocket.send_json({"type": "closed"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for project %s", project_id)
    except Exception:
        logger.exception("Error during project operation for %s", project_id)
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": "Internal server error"})
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()


# ── Playground WebSocket (ADR-028 / ADR-029) ─────────────────────────


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
