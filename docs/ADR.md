# Architecture Decision Records

ADRs are now maintained as individual files in [`.sdlc/adrs/`](../.sdlc/adrs/).

| ADR | Date | Summary |
|-----|------|---------|
| [ADR-001](../.sdlc/adrs/ADR-001-grpc-communication.md) | 2026-02 | gRPC for inter-service communication |
| [ADR-002](../.sdlc/adrs/ADR-002-opa-rego-policy.md) | 2026-02 | OPA/Rego for declarative policy rules |
| [ADR-003](../.sdlc/adrs/ADR-003-vendor-ari-engine.md) | 2026-02 | Vendor ARI engine, full integration |
| [ADR-004](../.sdlc/adrs/ADR-004-podman-pod-deployment.md) | 2026-02 | Podman pod as deployment unit |
| [ADR-005](../.sdlc/adrs/ADR-005-no-service-discovery.md) | 2026-02 | Reject etcd/service discovery |
| [ADR-006](../.sdlc/adrs/ADR-006-ephemeral-venvs.md) | 2026-03 | Ephemeral per-request venvs |
| [ADR-007](../.sdlc/adrs/ADR-007-async-grpc-servers.md) | 2026-03 | Fully async gRPC servers (grpc.aio) |
| [ADR-008](../.sdlc/adrs/ADR-008-rule-id-conventions.md) | 2026-02 | Rule ID conventions (L/M/R/P) |
| [ADR-009](../.sdlc/adrs/ADR-009-remediation-engine.md) | 2026-03 | Separate remediation engine |
| [ADR-010](../.sdlc/adrs/ADR-010-gitleaks-validator.md) | 2026-03 | Gitleaks as gRPC validator |
| [ADR-011](../.sdlc/adrs/ADR-011-yaml-formatter-prepass.md) | 2026-03 | YAML formatter as Phase 1 pre-pass |
| [ADR-012](../.sdlc/adrs/ADR-012-scale-pods-not-services.md) | 2026-02 | Scale pods, not services |
| [ADR-013](../.sdlc/adrs/ADR-013-structured-diagnostics.md) | 2026-03 | Structured diagnostics in gRPC contract |
| [ADR-014](../.sdlc/adrs/ADR-014-ruff-prek-hooks.md) | 2026-03 | Ruff linter and prek pre-commit hooks |
| [ADR-015](../.sdlc/adrs/ADR-015-github-actions-prek.md) | 2026-03 | GitHub Actions CI with prek |
| [ADR-016](../.sdlc/adrs/ADR-016-single-branch-main.md) | 2026-03 | Single-branch `main` strategy |
| [ADR-017](../.sdlc/adrs/ADR-017-trust-and-verify-agent-sdlc.md) | 2026-03 | Trust-and-verify model for agent SDLC invocation |
