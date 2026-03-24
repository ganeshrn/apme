# REQ-008: ROI Dashboard Component

## Metadata

- **Phase**: PHASE-003 - Enterprise Dashboard
- **Status**: Draft
- **Created**: 2026-03-24

## Overview

A dedicated ROI (Return on Investment) dashboard component that quantifies the value APME delivers. Tracks metrics including total errors resolved, estimated hours saved, compliance improvement over time, and cost avoidance. Provides executive-facing visualizations for justifying continued investment in automation modernization.

## User Stories

**As a Product Manager**, I want to see "Total Errors Resolved" and "Hours Saved" metrics so that I can demonstrate APME's value to leadership.

**As a VP of Engineering**, I want ROI trend charts so that I can track modernization progress across quarters.

**As an Automation Architect**, I want per-project ROI breakdowns so that I can identify which projects benefit most from APME.

**As a Finance Stakeholder**, I want cost avoidance estimates so that I can justify the TCO of APME tooling.

## Acceptance Criteria

### Total Errors Resolved Metric
- **GIVEN** historical scan data across all projects
- **WHEN** the ROI dashboard loads
- **THEN** it displays total violations detected and total violations resolved (remediated or acknowledged)

### Hours Saved Calculation
- **GIVEN** configurable time-per-fix estimates (e.g., FQCN fix = 5min, deprecated module = 30min)
- **WHEN** remediation has been applied
- **THEN** the dashboard calculates and displays estimated hours saved

### Compliance Score Over Time
- **GIVEN** periodic scan data for a project
- **WHEN** the trend chart is rendered
- **THEN** it shows compliance score (violations/files ratio) trending over time

### Per-Project ROI Breakdown
- **GIVEN** multiple projects with scan history
- **WHEN** the breakdown view is accessed
- **THEN** each project shows its own errors resolved, hours saved, and compliance trend

### Executive Summary Export
- **GIVEN** the ROI dashboard
- **WHEN** an export is requested
- **THEN** a PDF or CSV report is generated with all ROI metrics and charts

### Configurable Time Estimates
- **GIVEN** an admin in the ROI settings
- **WHEN** they adjust time-per-fix estimates by rule category
- **THEN** hours-saved calculations update retroactively

## Inputs / Outputs

### Inputs

| Name | Type | Description | Required |
|------|------|-------------|----------|
| time_range | date_range | Period for ROI calculation | Yes |
| project_filter | string[] | Specific projects to include | No |
| time_estimates | map[category, minutes] | Estimated manual fix time per category | No (defaults provided) |

### Outputs

| Name | Type | Description |
|------|------|-------------|
| total_violations_detected | int | Cumulative violations found |
| total_violations_resolved | int | Violations remediated or acknowledged |
| estimated_hours_saved | float | Based on time_estimates × resolved count |
| compliance_trend | list[DataPoint] | Compliance score over time |
| per_project_roi | list[ProjectROI] | Per-project breakdown |

## Behavior

### Happy Path

1. User navigates to ROI dashboard (tab in main dashboard or standalone view)
2. Dashboard queries scan history for the selected time range
3. Metrics are calculated:
   - **Errors Resolved** = violations in first scan − violations in latest scan + new violations resolved
   - **Hours Saved** = Σ (resolved violations × time_estimate for rule category)
   - **Compliance Score** = 1 − (active violations / total files scanned)
   - **Cost Avoidance** = hours_saved × configurable hourly rate
4. Visualizations rendered: KPI cards, trend line chart, per-project bar chart
5. User can drill down into any metric for detail

### Default Time Estimates

| Category | Default Estimate | Rationale |
|----------|-----------------|-----------|
| L (Lint) | 5 minutes | Simple syntax fixes |
| M (Modernize) | 15 minutes | Module migration research + fix |
| R (Risk) | 30 minutes | Architecture review + fix |
| P (Policy) | 20 minutes | Policy compliance remediation |
| SEC (Secrets) | 45 minutes | Secret rotation + remediation |

### Edge Cases

| Case | Handling |
|------|----------|
| No scan history | Show "No data yet" with prompt to run first scan |
| Single scan only | Show current state; trend chart shows single point |
| Time estimates set to 0 | Hours saved shows 0; metric card grayed out |
| Project deleted but history exists | Include in historical data; mark as archived |

### Error Conditions

| Error | Cause | Response |
|-------|-------|----------|
| Scan history unavailable | DB connection issue | Show cached last-known values with staleness indicator |
| Invalid time range | End before start | Validation error; default to last 30 days |

## Dependencies

### Internal

- REQ-001: Core Scanning Engine (scan results data)
- REQ-002: Automated Remediation (remediation data for "resolved" count)
- REQ-005: Rule Rating & Severity (rule categories for time estimates)
- REQ-009: Project-Centric UI (project-level aggregation)

### External

- Charting library (e.g., Chart.js, Recharts, or Plotly)
- PDF generation library for executive reports

## Non-Functional Requirements

- **Performance**: Dashboard must load within 3 seconds for up to 100 projects
- **Accuracy**: Hours-saved calculation must be auditable (show formula and inputs)
- **Responsiveness**: Charts must be interactive (hover, zoom, filter)
- **Accessibility**: Charts must include alt text and data tables for screen readers

## Open Questions

- [ ] Should we track actual time spent on manual fixes (stopwatch feature) vs. estimates only?
- [ ] Should ROI data be exportable via API for external BI tools?
- [ ] Do we need role-based views (exec summary vs. engineer detail)?
- [ ] Should cost avoidance include avoided outage estimates (risk-based)?

## References

- REQ-004: Enterprise Integration (dashboard context)
- PHASE-003: Enterprise Dashboard (phase goal: ROI metrics)

---

## Change History

| Date | Author | Change |
|------|--------|--------|
| 2026-03-24 | APME Team | Initial draft |
