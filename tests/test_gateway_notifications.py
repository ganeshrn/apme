"""Unit tests for the notification system (generator, REST endpoints, SSE hub)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from apme_gateway.app import create_app
from apme_gateway.db import close_db, get_session, init_db
from apme_gateway.db.models import Scan, Session, Violation
from apme_gateway.notifications import (
    _broadcast,
    broadcast_notifications,
    generate_notifications,
    subscribe,
    unsubscribe,
)


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


async def _seed_session_and_scan(
    *,
    scan_id: str = "scan-1",
    session_id: str = "sess-1",
    project_path: str = "/proj",
    scan_type: str = "check",
    total_violations: int = 3,
    fixed_count: int = 0,
    project_id: str | None = None,
) -> Scan:
    """Insert a session and scan for testing.

    Args:
        scan_id: Scan UUID.
        session_id: Session hash.
        project_path: Filesystem path.
        scan_type: Either check or remediate.
        total_violations: Violation count.
        fixed_count: Number of fixed violations.
        project_id: Optional project FK.

    Returns:
        The created Scan row.
    """
    async with get_session() as db:
        db.add(Session(session_id=session_id, project_path=project_path, first_seen="t0", last_seen="t1"))
        scan = Scan(
            scan_id=scan_id,
            session_id=session_id,
            project_id=project_id,
            project_path=project_path,
            source="cli",
            created_at="2026-01-01T00:00:00Z",
            scan_type=scan_type,
            total_violations=total_violations,
            fixed_count=fixed_count,
        )
        db.add(scan)
        await db.commit()
        return scan


# ---------------------------------------------------------------------------
# Notification generator tests
# ---------------------------------------------------------------------------


class TestGenerateNotifications:
    """Tests for generate_notifications()."""

    async def test_scan_complete_notification_created(self) -> None:
        """A scan_complete notification is always generated."""
        await _seed_session_and_scan()
        async with get_session() as db:
            from sqlalchemy import select

            scan = (await db.execute(select(Scan).where(Scan.scan_id == "scan-1"))).scalar_one()
            payloads = await generate_notifications(db, scan, [])
            await db.commit()

        assert len(payloads) == 1
        assert payloads[0]["type"] == "scan_complete"
        assert payloads[0]["variant"] == "info"
        assert "3 violations" in payloads[0]["message"]

    async def test_remediate_scan_notification(self) -> None:
        """Remediation scans include fixed count and correct remaining in the message."""
        await _seed_session_and_scan(scan_type="remediate", fixed_count=5, total_violations=7)
        async with get_session() as db:
            from sqlalchemy import select

            scan = (await db.execute(select(Scan).where(Scan.scan_id == "scan-1"))).scalar_one()
            payloads = await generate_notifications(db, scan, [])
            await db.commit()

        assert payloads[0]["type"] == "scan_complete"
        assert payloads[0]["title"] == "Remediation Complete"
        assert "5 findings resolved" in payloads[0]["message"]
        assert "2 remaining" in payloads[0]["message"]
        assert payloads[0]["variant"] == "success"

    async def test_zero_violation_check_is_success(self) -> None:
        """A clean check with zero violations uses success variant."""
        await _seed_session_and_scan(total_violations=0)
        async with get_session() as db:
            from sqlalchemy import select

            scan = (await db.execute(select(Scan).where(Scan.scan_id == "scan-1"))).scalar_one()
            payloads = await generate_notifications(db, scan, [])
            await db.commit()

        assert payloads[0]["variant"] == "success"

    async def test_secrets_detected_notification(self) -> None:
        """SEC:* violations trigger a separate danger notification."""
        await _seed_session_and_scan()
        sec_violations = [
            Violation(scan_id="scan-1", rule_id="SEC:aws-access-key", level="error", message="", file="creds.yml"),
            Violation(scan_id="scan-1", rule_id="SEC:private-key", level="error", message="", file="keys.pem"),
        ]
        async with get_session() as db:
            from sqlalchemy import select

            scan = (await db.execute(select(Scan).where(Scan.scan_id == "scan-1"))).scalar_one()
            payloads = await generate_notifications(db, scan, sec_violations)
            await db.commit()

        assert len(payloads) == 2
        sec_payload = payloads[1]
        assert sec_payload["type"] == "secrets_detected"
        assert sec_payload["variant"] == "danger"
        assert sec_payload["title"] == "Secrets Detected"
        assert "2 secret(s)" in sec_payload["message"]

    async def test_no_secrets_notification_for_non_sec_rules(self) -> None:
        """Non-SEC violations should not trigger a secrets notification."""
        await _seed_session_and_scan()
        violations = [
            Violation(scan_id="scan-1", rule_id="L001", level="error", message="", file="a.yml"),
        ]
        async with get_session() as db:
            from sqlalchemy import select

            scan = (await db.execute(select(Scan).where(Scan.scan_id == "scan-1"))).scalar_one()
            payloads = await generate_notifications(db, scan, violations)
            await db.commit()

        assert len(payloads) == 1
        assert payloads[0]["type"] == "scan_complete"

    async def test_health_drop_notification(self) -> None:
        """A health score drop >= 10 triggers a warning notification."""
        await _seed_session_and_scan()
        async with get_session() as db:
            from sqlalchemy import select

            scan = (await db.execute(select(Scan).where(Scan.scan_id == "scan-1"))).scalar_one()
            payloads = await generate_notifications(
                db,
                scan,
                [],
                old_health_score=80,
                new_health_score=65,
            )
            await db.commit()

        assert len(payloads) == 2
        health_payload = payloads[1]
        assert health_payload["type"] == "health_changed"
        assert health_payload["variant"] == "warning"
        assert "80" in health_payload["message"]
        assert "65" in health_payload["message"]

    async def test_small_health_drop_no_notification(self) -> None:
        """A health score drop < 10 does not trigger a notification."""
        await _seed_session_and_scan()
        async with get_session() as db:
            from sqlalchemy import select

            scan = (await db.execute(select(Scan).where(Scan.scan_id == "scan-1"))).scalar_one()
            payloads = await generate_notifications(
                db,
                scan,
                [],
                old_health_score=80,
                new_health_score=75,
            )
            await db.commit()

        assert len(payloads) == 1  # only scan_complete


# ---------------------------------------------------------------------------
# SSE hub tests
# ---------------------------------------------------------------------------


class TestSSEHub:
    """Tests for the SSE subscribe/broadcast/unsubscribe mechanism."""

    def test_subscribe_and_broadcast(self) -> None:
        """Broadcast delivers to all subscribers."""
        q1 = subscribe()
        q2 = subscribe()
        try:
            _broadcast({"test": 1})
            assert q1.get_nowait() == {"test": 1}
            assert q2.get_nowait() == {"test": 1}
        finally:
            unsubscribe(q1)
            unsubscribe(q2)

    def test_unsubscribe_stops_delivery(self) -> None:
        """Unsubscribed queues don't receive further broadcasts."""
        q = subscribe()
        unsubscribe(q)
        _broadcast({"test": 2})
        assert q.empty()

    def test_double_unsubscribe_is_safe(self) -> None:
        """Unsubscribing twice does not raise."""
        q = subscribe()
        unsubscribe(q)
        unsubscribe(q)


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------


async def _seed_notification(
    *,
    type: str = "scan_complete",
    title: str = "Test",
    message: str = "msg",
    variant: str = "info",
    read: bool = False,
) -> int:
    """Insert a notification row and return its ID.

    Args:
        type: Event category.
        title: Headline text.
        message: Body text.
        variant: Alert variant.
        read: Initial read state.

    Returns:
        The notification primary key.
    """
    async with get_session() as db:
        from apme_gateway.db.queries import insert_notification

        n = await insert_notification(
            db,
            type=type,
            title=title,
            message=message,
            variant=variant,
        )
        if read:
            n.read = True
        await db.commit()
        return int(n.id)


class TestNotificationEndpoints:
    """Tests for the notification REST endpoints."""

    async def test_list_empty(self, client: AsyncClient) -> None:
        """Listing with no notifications returns empty list.

        Args:
            client: Async HTTP test client.
        """
        resp = await client.get("/api/v1/notifications")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    async def test_list_returns_notifications(self, client: AsyncClient) -> None:
        """Notifications are returned newest-first.

        Args:
            client: Async HTTP test client.
        """
        await _seed_notification(title="First")
        await _seed_notification(title="Second")
        resp = await client.get("/api/v1/notifications")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["items"][0]["title"] == "Second"
        assert body["items"][1]["title"] == "First"

    async def test_list_unread_only(self, client: AsyncClient) -> None:
        """unread_only=true filters out read notifications.

        Args:
            client: Async HTTP test client.
        """
        await _seed_notification(title="Unread")
        await _seed_notification(title="Read", read=True)
        resp = await client.get("/api/v1/notifications?unread_only=true")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "Unread"

    async def test_mark_read(self, client: AsyncClient) -> None:
        """PATCH /notifications/{id}/read marks notification as read.

        Args:
            client: Async HTTP test client.
        """
        nid = await _seed_notification()
        resp = await client.patch(f"/api/v1/notifications/{nid}/read")
        assert resp.status_code == 200

        resp2 = await client.get("/api/v1/notifications?unread_only=true")
        assert resp2.json()["total"] == 0

    async def test_mark_read_404(self, client: AsyncClient) -> None:
        """Marking a non-existent notification returns 404.

        Args:
            client: Async HTTP test client.
        """
        resp = await client.patch("/api/v1/notifications/9999/read")
        assert resp.status_code == 404

    async def test_mark_all_read(self, client: AsyncClient) -> None:
        """POST /notifications/read-all marks all as read.

        Args:
            client: Async HTTP test client.
        """
        await _seed_notification(title="A")
        await _seed_notification(title="B")
        resp = await client.post("/api/v1/notifications/read-all")
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2

        resp2 = await client.get("/api/v1/notifications?unread_only=true")
        assert resp2.json()["total"] == 0

    async def test_delete_notification(self, client: AsyncClient) -> None:
        """DELETE /notifications/{id} removes the notification.

        Args:
            client: Async HTTP test client.
        """
        nid = await _seed_notification()
        resp = await client.delete(f"/api/v1/notifications/{nid}")
        assert resp.status_code == 204

        resp2 = await client.get("/api/v1/notifications")
        assert resp2.json()["total"] == 0

    async def test_delete_404(self, client: AsyncClient) -> None:
        """Deleting a non-existent notification returns 404.

        Args:
            client: Async HTTP test client.
        """
        resp = await client.delete("/api/v1/notifications/9999")
        assert resp.status_code == 404

    async def test_notification_schema_fields(self, client: AsyncClient) -> None:
        """Verify the response schema includes all expected fields.

        Args:
            client: Async HTTP test client.
        """
        await _seed_notification(
            type="secrets_detected",
            title="Secrets",
            message="Found 3",
            variant="danger",
        )
        resp = await client.get("/api/v1/notifications")
        item = resp.json()["items"][0]
        assert item["type"] == "secrets_detected"
        assert item["title"] == "Secrets"
        assert item["message"] == "Found 3"
        assert item["variant"] == "danger"
        assert item["read"] is False
        assert "created_at" in item
        assert "id" in item

    async def test_sse_stream_delivers_notification(self) -> None:
        """The SSE event stream generator yields broadcast payloads as ``data:`` lines."""
        import asyncio
        import json

        from apme_gateway.notifications import sse_event_stream

        q = subscribe()
        stream = sse_event_stream(q)
        try:
            payload = {"id": 1, "type": "scan_complete", "title": "Test"}
            _broadcast(payload)
            chunk = await asyncio.wait_for(anext(stream), timeout=2.0)
            data = json.loads(chunk.removeprefix("data: ").strip())
            assert data["type"] == "scan_complete"
            assert data["title"] == "Test"
        finally:
            unsubscribe(q)
            await stream.aclose()  # type: ignore[attr-defined]

    async def test_sse_endpoint_delivers_event(self, client: AsyncClient) -> None:
        """The /notifications/stream endpoint returns SSE headers and broadcast payloads.

        Args:
            client: Async HTTP test client.
        """
        import asyncio
        import json

        payload = {"id": 1, "type": "scan_complete", "title": "SSE Test"}

        async def _consume() -> tuple[dict[str, str], str | None]:
            """Open the SSE stream, broadcast a payload, return headers and first data line.

            Returns:
                Tuple of response headers and the first ``data:`` line (or None).
            """
            async with client.stream("GET", "/api/v1/notifications/stream") as resp:
                headers = dict(resp.headers)
                _broadcast(payload)
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        return headers, line
            return headers, None

        task = asyncio.create_task(_consume())
        try:
            headers, data_line = await asyncio.wait_for(task, timeout=5.0)
        except asyncio.TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            pytest.fail("Timed out waiting for SSE data event")

        assert headers.get("content-type", "").startswith("text/event-stream")
        assert headers.get("cache-control") == "no-cache"
        assert headers.get("x-accel-buffering") == "no"
        assert data_line is not None
        data = json.loads(data_line.removeprefix("data: ").strip())
        assert data["type"] == "scan_complete"
        assert data["title"] == "SSE Test"


# ---------------------------------------------------------------------------
# Broadcast-after-commit tests
# ---------------------------------------------------------------------------


class TestBroadcastNotifications:
    """Tests for the broadcast_notifications helper."""

    def test_broadcast_notifications_delivers_to_subscribers(self) -> None:
        """broadcast_notifications pushes payloads to all SSE subscribers."""
        q = subscribe()
        try:
            payloads = [{"id": 1, "type": "scan_complete"}, {"id": 2, "type": "secrets_detected"}]
            broadcast_notifications(payloads)
            assert q.get_nowait() == payloads[0]
            assert q.get_nowait() == payloads[1]
        finally:
            unsubscribe(q)


# ---------------------------------------------------------------------------
# Edge-case tests for notification generator
# ---------------------------------------------------------------------------


class TestNotificationEdgeCases:
    """Edge-case tests for generate_notifications."""

    async def test_secrets_with_no_file_paths(self) -> None:
        """SEC violations with empty file fields produce a clean message."""
        await _seed_session_and_scan()
        sec_violations = [
            Violation(scan_id="scan-1", rule_id="SEC:generic-secret", level="error", message="", file=""),
        ]
        async with get_session() as db:
            from sqlalchemy import select

            scan = (await db.execute(select(Scan).where(Scan.scan_id == "scan-1"))).scalar_one()
            payloads = await generate_notifications(db, scan, sec_violations)
            await db.commit()

        sec_payload = payloads[1]
        assert sec_payload["type"] == "secrets_detected"
        assert "found in" not in sec_payload["message"]
        assert "1 secret(s) found" in sec_payload["message"]
