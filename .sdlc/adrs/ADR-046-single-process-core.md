# ADR-046: Single-Process Core Architecture

## Status

Proposed

## Date

2026-03-30

## Context

APME currently deploys as 6-8 containers in a Podman pod (ADR-004), with gRPC communication between all services (ADR-001). This architecture was appropriate when APME was a standalone tool. The deployment landscape has since expanded to include:

1. **RHEL bootc appliance** — a single-VM appliance running the Ansible self-service portal as Podman Quadlet systemd services. Adding 7 containers for APME (Primary, Native, OPA, Ansible, Gitleaks, Galaxy Proxy, Gateway) to a single-node appliance that already runs 3 containers (portal, PostgreSQL, devtools) is disproportionate. Total memory for APME alone: ~3.5GB (7 × 512MB). Total pre-pulled images: ~2GB added to the bootc image.

2. **OpenShift sidecar** — the portal runs in a RHDH pod. APME should fit as one sidecar container, like the existing ansible-devtools-server on port 8000. Adding 7 containers to the RHDH pod is not viable.

3. **CI/CD pipelines** — GitHub Actions, Tekton, Jenkins need a single container that runs `apme check .` and exits. Pod orchestration in a CI step is unjustifiable overhead.

4. **Developer workstation** — `pip install apme && apme check .` already works via daemon mode (ADR-024), which runs Primary + Native + OPA + Ansible + Galaxy Proxy in a single process. This proves the architecture can function in-process.

### The daemon mode precedent

ADR-024 implemented daemon mode: all core services run in one process on the developer's machine. Native rules are called in-process. OPA binary is invoked as a subprocess. The Ansible validator runs in-process with subprocess calls to `ansible-doc`. Galaxy Proxy runs as an in-process HTTP server.

This already demonstrates that the multi-container architecture is a deployment choice, not an architectural requirement. The services share no mutable state between them — each receives a `ValidateRequest` and returns a `ValidateResponse`. The Validator Protocol can be satisfied by a function call as easily as a gRPC call.

### What the multi-container model costs

Per ARCHITECTURE.md, the current model requires:
- 5 Containerfiles + build scripts
- Proto compilation and stub generation (`scripts/gen_grpc.sh`)
- `jsonpickle.encode()` for scandata serialization (fragile, version-coupled)
- `json.dumps()` for hierarchy_payload serialization
- Session volume mounts (`/sessions`) for venv sharing between Primary and Ansible
- Health check coordination across 5+ containers
- Port allocation and management (50051, 50053, 50054, 50055, 50056, 8765)

Per DATA_FLOW.md, serialization boundaries exist solely because data crosses process boundaries:
- hierarchy_payload: Python dict → `json.dumps()` → bytes → gRPC → bytes → `json.loads()` → Python dict
- scandata: SingleScan object → `jsonpickle.encode()` → bytes → gRPC → bytes → `jsonpickle.decode()` → SingleScan object

In a single-process model, these serialization round-trips disappear. The engine produces a Python object; validators consume it directly.

### Decision drivers

- Bootc appliance: 1 container is acceptable, 7 is not
- OpenShift sidecar: 1 container is a natural fit, 7 containers in the RHDH pod is not
- CI/CD: single container image with CLI entrypoint
- Daemon mode (ADR-024) proves single-process viability
- jsonpickle serialization is the most fragile boundary — removing it improves reliability
- OPA and Gitleaks are external binaries — subprocess is the natural interface, not gRPC wrapping
- Abbenay AI is a genuinely external service — gRPC to it is correct and unchanged

## Decision

**APME's core will run as a single process.** The engine, native rules, formatter, and remediation engine execute in-process. OPA and Gitleaks run as subprocesses within the same process (no gRPC wrapping). External services (Abbenay AI, PostgreSQL) retain their network protocols (gRPC, SQL).

### Architecture

```
┌──────────────────────────────────────────────────────┐
│  apme (single process)                               │
│                                                      │
│  Engine (parse → annotate → hierarchy)               │
│    │                                                 │
│    ├── Native rules (in-process, library call)       │
│    ├── OPA rules (subprocess: opa eval, batch)       │
│    ├── Gitleaks (subprocess: gitleaks detect)         │
│    └── Ansible checks (in-process + optional         │
│        ansible-doc subprocess)                       │
│                                                      │
│  Remediation (Tier 1 transforms in-process)          │
│  Formatter (in-process)                              │
│  Server layer (optional: FastAPI REST API)           │
│                                                      │
│  External (network):                                 │
│  └── Abbenay AI (:50057, gRPC — unchanged)           │
└──────────────────────────────────────────────────────┘
```

### Validator interface preserved

The `Validator` Protocol from DESIGN_VALIDATORS.md is preserved as a Python Protocol (not gRPC service). Each validator implements the same `validate(request) → response` interface. The engine calls validators via `asyncio.gather()` for the same parallel fan-out behavior documented in ARCHITECTURE.md:

```python
native_result, opa_result, gitleaks_result = await asyncio.gather(
    asyncio.to_thread(native_validator.validate, request),   # CPU-bound
    opa_validator.validate(request),                          # subprocess, async
    gitleaks_validator.validate(request),                     # subprocess, async
)
```

Wall-clock time remains `max(native, opa, gitleaks)`, consistent with ARCHITECTURE.md's parallel fan-out guarantee. The Ansible validator's checks are absorbed: M001-M004 use pre-built data files (ADR-048); L057-L059 are optional subprocess calls when ansible-core is available.

### What remains external (gRPC/network)

- **Abbenay AI** — external daemon, gRPC (ADR-025 unchanged)
- **PostgreSQL** — when used for persistence in server mode
- **Future plugin services** — ADR-042's third-party plugins use gRPC (external processes)

gRPC is retained as the **extensibility protocol** for external services, not for internal validator communication.

## Alternatives Considered

### Alternative 1: Keep multi-container architecture, add daemon mode for lightweight deployments

**Pros**: No changes to existing code. Daemon mode already works.

**Cons**: Daemon mode is a second-class path — it lacks Gitleaks, Gateway, and UI. Maintaining two architectures (pod + daemon) doubles the test surface. The pod model doesn't fit bootc or OpenShift sidecar without major compromises.

**Why not chosen**: Two deployment models with different capabilities is worse than one model that works everywhere.

### Alternative 2: Single container with internal gRPC (all services in one container, localhost gRPC)

**Pros**: One container image. gRPC contracts unchanged.

**Cons**: Still has serialization overhead (jsonpickle, JSON round-trips). Still requires port management within the container. More complex than direct function calls for in-process communication.

**Why not chosen**: If everything runs in one process, gRPC between in-process components adds overhead with no benefit. The Validator Protocol can be a Python interface.

## Consequences

### Positive

- One container image serves all deployment targets (bootc, OpenShift sidecar, CI/CD, workstation)
- jsonpickle serialization eliminated (fragile, version-coupled)
- No port allocation for internal services
- No health check coordination between containers
- Reduced memory footprint (~256MB vs ~3.5GB for full pod)
- Reduced container image size (~200MB vs ~2GB for 7 images)
- Faster cold start (1 process vs 7 containers)
- Validator Protocol preserved as testable Python interface

### Negative

- Lose process isolation between validators (a bug in one validator can crash the process)
- OPA binary and Gitleaks binary must be bundled in the container image
- Cannot independently scale individual validators (mitigated: scale by adding worker processes)

### Neutral

- Rule implementations unchanged (same Python code, same Rego files)
- Transform implementations unchanged
- Formatter unchanged
- AI escalation unchanged (Abbenay remains external gRPC)
- gRPC retained for external services and future plugins

## Supersedes

- ADR-001 (gRPC communication) — for internal validator communication only. gRPC retained for external services.
- ADR-004 (Podman pod deployment) — as the sole deployment model. Pod deployment remains available for users who prefer process isolation.
- ADR-005 (No service discovery) — no longer needed when all validators are in-process.

## Related Decisions

- [ADR-024](ADR-024-thin-cli-daemon-mode.md): Daemon mode — the precedent for single-process execution
- [ADR-007](ADR-007-async-grpc-servers.md): Async servers — asyncio.gather() preserved for parallel fan-out
- [ADR-009](ADR-009-remediation-engine.md): Validators read-only — separation of detection and remediation preserved
- [ADR-012](ADR-012-scale-pods-not-services.md): Scale pods — workers are scaled units (one process each)
- [ADR-025](ADR-025-ai-provider-protocol.md): AI provider — Abbenay gRPC unchanged
- [ADR-042](ADR-042-third-party-plugin-services.md): Third-party plugins — gRPC for external plugin services

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-03-30 | Claude (proposal) | Initial proposal based on deployment target analysis |
