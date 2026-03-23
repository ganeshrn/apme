"""Playwright-based browser tests for the APME Executive Dashboard.

These tests verify layout, navigation, and theme toggling against a live
gateway + UI stack.  Marked ``ui`` so they are skipped in both the normal
unit-test run and the daemon integration run.

Requires:
    pytest-playwright (``pip install pytest-playwright``)
    A running UI on ``APME_UI_URL`` (default ``http://localhost:8081``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("pytest_playwright", reason="pytest-playwright not installed")

if TYPE_CHECKING:
    from playwright.sync_api import Page

from playwright.sync_api import expect  # noqa: E402

pytestmark = pytest.mark.ui

_BASE = os.environ.get("APME_UI_URL", "http://localhost:8081")


@pytest.fixture()  # type: ignore[untyped-decorator]
def dashboard(page: Page) -> Page:
    """Navigate to the dashboard and wait for the sidebar to appear.

    Args:
        page: Playwright page fixture.

    Returns:
        Page positioned on the dashboard.
    """
    page.goto(_BASE, wait_until="networkidle")
    page.wait_for_selector(".apme-sidebar", timeout=10_000)
    return page


def test_page_title(dashboard: Page) -> None:
    """Dashboard page title contains APME.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    expect(dashboard).to_have_title("APME Dashboard")


def test_sidebar_nav_items(dashboard: Page) -> None:
    """Sidebar contains expected navigation links.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    expected = ["New Scan", "Dashboard", "Scans", "Top Violations", "Fix Tracker", "AI Metrics", "Health"]
    items = dashboard.locator(".apme-nav .apme-nav-item")
    expect(items).to_have_count(len(expected))
    for i, label in enumerate(expected):
        expect(items.nth(i)).to_contain_text(label)


def test_metric_cards_visible(dashboard: Page) -> None:
    """Dashboard shows metric cards.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    cards = dashboard.locator(".apme-metric-card")
    expect(cards).to_have_count(6)


def test_navigate_to_scans(dashboard: Page) -> None:
    """Clicking Scans in sidebar navigates to /scans.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.click("text=Scans")
    dashboard.wait_for_url(f"{_BASE}/scans", timeout=5_000)
    expect(dashboard.locator(".apme-page-title")).to_have_text("All Scans")


def test_navigate_to_health(dashboard: Page) -> None:
    """Clicking Health in sidebar navigates to /health.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.click("text=Health")
    dashboard.wait_for_url(f"{_BASE}/health", timeout=5_000)
    expect(dashboard.locator(".apme-page-title")).to_have_text("System Health")


def test_navigate_to_violations(dashboard: Page) -> None:
    """Clicking Top Violations in sidebar navigates to /violations.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.click("text=Top Violations")
    dashboard.wait_for_url(f"{_BASE}/violations", timeout=5_000)
    expect(dashboard.locator(".apme-page-title")).to_have_text("Top Violations")


def test_navigate_to_fix_tracker(dashboard: Page) -> None:
    """Clicking Fix Tracker in sidebar navigates to /fix-tracker.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.click("text=Fix Tracker")
    dashboard.wait_for_url(f"{_BASE}/fix-tracker", timeout=5_000)
    expect(dashboard.locator(".apme-page-title")).to_have_text("Fix Tracker")


def test_navigate_to_ai_metrics(dashboard: Page) -> None:
    """Clicking AI Metrics in sidebar navigates to /ai-metrics.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.click("text=AI Metrics")
    dashboard.wait_for_url(f"{_BASE}/ai-metrics", timeout=5_000)
    expect(dashboard.locator(".apme-page-title")).to_have_text("AI Metrics")


def test_theme_toggle(dashboard: Page) -> None:
    """Theme toggle switches data-theme attribute between dark and light.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    html = dashboard.locator("html")
    expect(html).to_have_attribute("data-theme", "dark")

    dashboard.click(".apme-theme-btn")
    expect(html).to_have_attribute("data-theme", "light")

    dashboard.click(".apme-theme-btn")
    expect(html).to_have_attribute("data-theme", "dark")


def test_scans_page_has_table(dashboard: Page) -> None:
    """Scans page renders a data table (or an empty state).

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.click("text=Scans")
    dashboard.wait_for_url(f"{_BASE}/scans", timeout=5_000)
    table_or_empty = dashboard.locator(".apme-data-table, .apme-empty")
    expect(table_or_empty.first).to_be_visible()


def test_health_shows_status(dashboard: Page) -> None:
    """Health page displays gateway status rows.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.click("text=Health")
    dashboard.wait_for_url(f"{_BASE}/health", timeout=5_000)
    dashboard.wait_for_selector(".apme-data-table, .apme-empty", timeout=10_000)
    status = dashboard.locator(".apme-data-table td")
    if status.count() >= 2:
        expect(status.first).to_have_text("Gateway")


# ── New Scan (Operator UI) ───────────────────────────────────────────


@pytest.fixture()  # type: ignore[untyped-decorator]
def new_scan_page(page: Page) -> Page:
    """Navigate to the New Scan page and wait for the form.

    Args:
        page: Playwright page fixture.

    Returns:
        Page positioned on /new-scan.
    """
    page.goto(f"{_BASE}/new-scan", wait_until="networkidle")
    page.wait_for_selector(".apme-page-title", timeout=10_000)
    return page


def test_navigate_to_new_scan(dashboard: Page) -> None:
    """Clicking New Scan in sidebar navigates to /new-scan.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.click("text=New Scan")
    dashboard.wait_for_url(f"{_BASE}/new-scan", timeout=5_000)
    expect(dashboard.locator(".apme-page-title")).to_have_text("New Scan")


def test_new_scan_page_title(new_scan_page: Page) -> None:
    """New Scan page displays the correct title.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    expect(new_scan_page.locator(".apme-page-title")).to_have_text("New Scan")


def test_new_scan_tabs(new_scan_page: Page) -> None:
    """New Scan page has Upload and Project tabs, with Project disabled.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    tabs = new_scan_page.locator(".apme-tab")
    expect(tabs).to_have_count(2)
    expect(tabs.nth(0)).to_have_text("Upload Files")
    expect(tabs.nth(1)).to_have_text("Project (SCM)")
    expect(tabs.nth(1)).to_be_disabled()


def test_new_scan_drop_zone_visible(new_scan_page: Page) -> None:
    """Upload tab shows the drag-and-drop zone.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    drop_zone = new_scan_page.locator(".apme-drop-zone")
    expect(drop_zone).to_be_visible()
    expect(drop_zone).to_contain_text("Drop Ansible files here")


def test_new_scan_directory_button(new_scan_page: Page) -> None:
    """Select Directory button is visible.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    btn = new_scan_page.locator("button:has-text('Select Directory')")
    expect(btn).to_be_visible()


def test_new_scan_start_disabled_without_files(new_scan_page: Page) -> None:
    """Start Scan button is disabled when no files are selected.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    btn = new_scan_page.locator("button:has-text('Start Scan')")
    expect(btn).to_be_disabled()


def test_new_scan_advanced_options(new_scan_page: Page) -> None:
    """Advanced Options panel expands to show version and collections inputs.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    new_scan_page.click("text=Advanced Options")
    expect(new_scan_page.locator("#ansible-version")).to_be_visible()
    expect(new_scan_page.locator("#collections")).to_be_visible()


def test_new_scan_file_upload_enables_start(new_scan_page: Page) -> None:
    """Uploading a file via the hidden input enables the Start Scan button.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    file_input = new_scan_page.locator(".apme-scan-form input[type='file'][multiple]")
    file_input.set_input_files(
        {
            "name": "playbook.yml",
            "mimeType": "text/yaml",
            "buffer": b"---\n- hosts: all\n  tasks: []\n",
        }
    )

    expect(new_scan_page.locator(".apme-file-list")).to_be_visible()
    expect(new_scan_page.locator(".apme-file-item")).to_have_count(1)
    expect(new_scan_page.locator(".apme-file-name")).to_contain_text("playbook.yml")

    btn = new_scan_page.locator("button:has-text('Start Scan')")
    expect(btn).to_be_enabled()


def test_new_scan_file_remove(new_scan_page: Page) -> None:
    """Removing a file from the list updates the count.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    file_input = new_scan_page.locator(".apme-scan-form input[type='file'][multiple]")
    file_input.set_input_files(
        [
            {
                "name": "a.yml",
                "mimeType": "text/yaml",
                "buffer": b"---\n",
            },
            {
                "name": "b.yml",
                "mimeType": "text/yaml",
                "buffer": b"---\n",
            },
        ]
    )

    expect(new_scan_page.locator(".apme-file-item")).to_have_count(2)

    new_scan_page.locator(".apme-file-remove").first.click()
    expect(new_scan_page.locator(".apme-file-item")).to_have_count(1)
