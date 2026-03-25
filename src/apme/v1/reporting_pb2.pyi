"""Stub for generated reporting_pb2 (proto types)."""

from collections.abc import Iterable

from apme.v1.common_pb2 import (
    ProgressUpdate,
    ScanSummary,
    Violation,
)
from apme.v1.primary_pb2 import (
    FilePatch,
    FixReport,
    ScanDiagnostics,
)

class ScanCompletedEvent:
    scan_id: str
    session_id: str
    project_path: str
    source: str
    violations: list[Violation]
    diagnostics: ScanDiagnostics
    summary: ScanSummary
    logs: list[ProgressUpdate]
    def __init__(
        self,
        *,
        scan_id: str = ...,
        session_id: str = ...,
        project_path: str = ...,
        source: str = ...,
        violations: Iterable[Violation] | None = ...,
        diagnostics: ScanDiagnostics | None = ...,
        summary: ScanSummary | None = ...,
        logs: Iterable[ProgressUpdate] | None = ...,
    ) -> None: ...

class FixCompletedEvent:
    scan_id: str
    session_id: str
    project_path: str
    source: str
    remaining_violations: list[Violation]
    diagnostics: ScanDiagnostics
    summary: ScanSummary
    report: FixReport
    proposals: list[ProposalOutcome]
    logs: list[ProgressUpdate]
    fixed_violations: list[Violation]
    patches: list[FilePatch]
    def __init__(
        self,
        *,
        scan_id: str = ...,
        session_id: str = ...,
        project_path: str = ...,
        source: str = ...,
        remaining_violations: Iterable[Violation] | None = ...,
        diagnostics: ScanDiagnostics | None = ...,
        summary: ScanSummary | None = ...,
        report: FixReport | None = ...,
        proposals: Iterable[ProposalOutcome] | None = ...,
        logs: Iterable[ProgressUpdate] | None = ...,
        fixed_violations: Iterable[Violation] | None = ...,
        patches: Iterable[FilePatch] | None = ...,
    ) -> None: ...

class ProposalOutcome:
    proposal_id: str
    rule_id: str
    file: str
    tier: int
    confidence: float
    status: str
    def __init__(
        self,
        *,
        proposal_id: str = ...,
        rule_id: str = ...,
        file: str = ...,
        tier: int = ...,
        confidence: float = ...,
        status: str = ...,
    ) -> None: ...

class ReportAck:
    def __init__(self) -> None: ...
