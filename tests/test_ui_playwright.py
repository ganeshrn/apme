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
import re
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
    """Navigate to the dashboard and wait for the sidebar nav to appear.

    Args:
        page: Playwright page fixture.

    Returns:
        Page positioned on the dashboard.
    """
    page.goto(_BASE, wait_until="networkidle")
    page.wait_for_selector("[data-testid='page-navigation']", timeout=10_000)
    return page


def test_page_title(dashboard: Page) -> None:
    """Dashboard page title contains APME.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    expect(dashboard).to_have_title(re.compile(r"Dashboard"))


def test_sidebar_nav_items(dashboard: Page) -> None:
    """Sidebar contains expected navigation links.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    expected = [
        "Dashboard",
        "New Scan",
        "Scans",
        "Sessions",
        "Top Violations",
        "Fix Tracker",
        "AI Metrics",
        "Health",
        "Settings",
    ]
    nav = dashboard.locator("[data-testid='page-navigation']")
    for label in expected:
        expect(nav.locator(f".pf-v6-c-nav__item >> text='{label}'").first).to_be_visible()


def test_dashboard_metric_cards_visible(dashboard: Page) -> None:
    """Dashboard shows metric count cards.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    cards = dashboard.locator(".pf-v6-c-card")
    expect(cards.first).to_be_attached()
    assert cards.count() >= 6, f"Expected >=6 dashboard cards, got {cards.count()}"


def test_navigate_to_scans(dashboard: Page) -> None:
    """Clicking Scans in sidebar navigates to /scans.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='scans']").click()
    dashboard.wait_for_url(f"{_BASE}/scans", timeout=5_000)
    expect(dashboard.locator("[data-testid='page-title']")).to_have_text("All Scans")


def test_navigate_to_health(dashboard: Page) -> None:
    """Clicking Health in sidebar navigates to /health.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='health']").click()
    dashboard.wait_for_url(f"{_BASE}/health", timeout=5_000)
    expect(dashboard.locator("[data-testid='page-title']")).to_have_text("System Health")


def test_navigate_to_violations(dashboard: Page) -> None:
    """Clicking Top Violations in sidebar navigates to /violations.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='violations']").click()
    dashboard.wait_for_url(f"{_BASE}/violations", timeout=5_000)
    expect(dashboard.locator("[data-testid='page-title']")).to_have_text("Top Violations")


def test_navigate_to_fix_tracker(dashboard: Page) -> None:
    """Clicking Fix Tracker in sidebar navigates to /fix-tracker.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='fix-tracker']").click()
    dashboard.wait_for_url(f"{_BASE}/fix-tracker", timeout=5_000)
    expect(dashboard.locator("[data-testid='page-title']")).to_have_text("Fix Tracker")


def test_navigate_to_ai_metrics(dashboard: Page) -> None:
    """Clicking AI Metrics in sidebar navigates to /ai-metrics.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='ai-metrics']").click()
    dashboard.wait_for_url(f"{_BASE}/ai-metrics", timeout=5_000)
    expect(dashboard.locator("[data-testid='page-title']")).to_have_text("AI Metrics")


def test_theme_toggle(dashboard: Page) -> None:
    """Theme toggle switches between dark and light via pf-v6-theme-dark class.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    html = dashboard.locator("html")

    theme_btn = dashboard.locator("[data-testid='settings-icon'], [data-testid='theme-icon']").first
    expect(theme_btn).to_be_visible()

    initial_is_dark = html.evaluate("el => el.classList.contains('pf-v6-theme-dark')")
    theme_btn.click()

    after_toggle = html.evaluate("el => el.classList.contains('pf-v6-theme-dark')")
    assert initial_is_dark != after_toggle, "Theme class should change after toggle click"

    new_btn = dashboard.locator("[data-testid='settings-icon'], [data-testid='theme-icon']").first
    new_btn.click()

    after_revert = html.evaluate("el => el.classList.contains('pf-v6-theme-dark')")
    assert initial_is_dark == after_revert, "Theme class should revert after second toggle"


def test_scans_page_has_table(dashboard: Page) -> None:
    """Scans page renders a PF6 data table (or an empty-state message).

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='scans']").click()
    dashboard.wait_for_url(f"{_BASE}/scans", timeout=5_000)
    table_or_empty = dashboard.locator(".pf-v6-c-table, div:has-text('No scans recorded')")
    expect(table_or_empty.first).to_be_visible()


def test_health_shows_status(dashboard: Page) -> None:
    """Health page displays gateway status rows.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='health']").click()
    dashboard.wait_for_url(f"{_BASE}/health", timeout=5_000)
    dashboard.wait_for_selector(".pf-v6-c-table, div:has-text('Unable to reach')", timeout=10_000)
    status = dashboard.locator(".pf-v6-c-table td")
    if status.count() >= 2:
        expect(status.first).to_have_text("Gateway")


# -- New Scan (Operator UI) ---------------------------------------------------


@pytest.fixture()  # type: ignore[untyped-decorator]
def new_scan_page(page: Page) -> Page:
    """Navigate to the New Scan page and wait for the page header.

    Args:
        page: Playwright page fixture.

    Returns:
        Page positioned on /new-scan.
    """
    page.goto(f"{_BASE}/new-scan", wait_until="networkidle")
    page.wait_for_selector("[data-testid='page-title']", timeout=10_000)
    return page


def test_navigate_to_new_scan(dashboard: Page) -> None:
    """Clicking New Scan in sidebar navigates to /new-scan.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='new-scan']").click()
    dashboard.wait_for_url(f"{_BASE}/new-scan", timeout=5_000)
    expect(dashboard.locator("[data-testid='page-title']")).to_have_text("New Scan")


def test_new_scan_page_title(new_scan_page: Page) -> None:
    """New Scan page displays the correct title.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    expect(new_scan_page.locator("[data-testid='page-title']")).to_have_text("New Scan")


def test_new_scan_drop_zone_visible(new_scan_page: Page) -> None:
    """Upload section shows the drag-and-drop zone.

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
    """Advanced Options panel expands to show version, collections, and AI toggle.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    new_scan_page.click("text=Advanced Options")
    expect(new_scan_page.locator("#ansible-version")).to_be_visible()
    expect(new_scan_page.locator("#collections")).to_be_visible()

    ai_checkbox = new_scan_page.locator("#enable-ai")
    expect(ai_checkbox).to_be_visible()
    expect(ai_checkbox).to_be_checked()


def test_new_scan_file_upload_enables_start(new_scan_page: Page) -> None:
    """Uploading a file via the hidden input enables the Start Scan button.

    Args:
        new_scan_page: Page positioned on /new-scan.
    """
    file_input = new_scan_page.locator(".pf-v6-c-card input[type='file'][multiple]")
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
    file_input = new_scan_page.locator(".pf-v6-c-card input[type='file'][multiple]")
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

    new_scan_page.locator("button[aria-label^='Remove']").first.click()
    expect(new_scan_page.locator(".apme-file-item")).to_have_count(1)


# -- Settings Page -----------------------------------------------------------


@pytest.fixture()  # type: ignore[untyped-decorator]
def settings_page(page: Page) -> Page:
    """Navigate to the Settings page and wait for the page header.

    Args:
        page: Playwright page fixture.

    Returns:
        Page positioned on /settings.
    """
    page.goto(f"{_BASE}/settings", wait_until="networkidle")
    page.wait_for_selector("[data-testid='page-title']", timeout=10_000)
    return page


def test_navigate_to_settings(dashboard: Page) -> None:
    """Clicking Settings in sidebar navigates to /settings.

    Args:
        dashboard: Page positioned on the dashboard.
    """
    dashboard.locator("[data-testid='settings']").click()
    dashboard.wait_for_url(f"{_BASE}/settings", timeout=5_000)
    expect(dashboard.locator("[data-testid='page-title']")).to_have_text("Settings")


def test_settings_page_title(settings_page: Page) -> None:
    """Settings page displays the correct title.

    Args:
        settings_page: Page positioned on /settings.
    """
    expect(settings_page.locator("[data-testid='page-title']")).to_have_text("Settings")


def test_settings_ai_config_heading(settings_page: Page) -> None:
    """Settings page shows the AI Configuration heading.

    Args:
        settings_page: Page positioned on /settings.
    """
    expect(settings_page.locator("h3:has-text('AI Configuration')")).to_be_visible()


def test_settings_model_picker_or_empty(settings_page: Page) -> None:
    """Settings page shows either the model picker or an empty-state message.

    Args:
        settings_page: Page positioned on /settings.
    """
    picker_or_empty = settings_page.locator("#ai-model, div:has-text('No models available')")
    expect(picker_or_empty.first).to_be_visible()


def test_settings_model_selection_persists(settings_page: Page) -> None:
    """Selecting a model persists in localStorage across reload.

    Args:
        settings_page: Page positioned on /settings.
    """
    picker = settings_page.locator("#ai-model")
    if not picker.is_visible():
        pytest.skip("No models available — Abbenay not running")

    options = picker.locator("option")
    if options.count() < 1:
        pytest.skip("No model options in picker")

    first_value = options.first.get_attribute("value") or ""
    picker.select_option(value=first_value)

    stored = settings_page.evaluate("() => localStorage.getItem('apme-ai-model')")
    assert stored == first_value, f"Expected '{first_value}' in localStorage, got '{stored}'"

    settings_page.reload(wait_until="networkidle")
    settings_page.wait_for_selector("#ai-model", timeout=10_000)
    reloaded_value = settings_page.locator("#ai-model").input_value()
    assert reloaded_value == first_value, (
        f"After reload, picker value should be '{first_value}', got '{reloaded_value}'"
    )


def test_settings_info_text(settings_page: Page) -> None:
    """Settings page shows explanatory text about model preference.

    Args:
        settings_page: Page positioned on /settings.
    """
    expect(settings_page.locator("p:has-text('stored in your browser')")).to_be_visible()
