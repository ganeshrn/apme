# ADR-047: Deployment Modes

## Status

Proposed

## Date

2026-03-30

## Context

APME must serve four deployment targets from a single container image:

1. **RHEL bootc appliance** — Podman Quadlet systemd service alongside the Ansible self-service portal. Single-node VM, air-gapped ready, pre-pulled images. Follows the same pattern as `portal-devtools.container` (port 8000). APME runs as `portal-apme.container` with REST API for portal integration.

2. **OpenShift** — sidecar in the RHDH pod (Helm chart `extraContainers`), plus optional KEDA-scaled worker Deployment for batch scanning of cataloged collections (3000+ async).

3. **CI/CD pipelines** — single container, CLI entrypoint, runs `apme check .` and outputs SARIF/JUnit/JSON. Must cold-start in <2 seconds (no venv creation, no service orchestration).

4. **Developer workstation** — `pip install apme && apme check .`. No containers required. Interactive remediation with AI approval flow.

ADR-024 (daemon mode) established the precedent for running APME as a single process. ADR-046 (single-process core) formalizes this as the primary architecture. This ADR defines the entrypoints and deployment patterns.

### Async batch scanning

The portal catalogs Ansible collections via `AnsibleGitContentsProvider` (Git repos) and `PAHCollectionProvider` (Automation Hub). When collections are cataloged, they should be scanned by APME for quality, security, and migration readiness. At scale, this means scanning 3000+ collections asynchronously.

This is a **batch processing** problem, not a real-time problem. Each scan is completely independent. The current architecture has no built-in queue — scaling requires external orchestration regardless of whether APME uses gRPC pods or single processes.

### PostgreSQL as queue

The portal already deploys PostgreSQL (both in bootc and OpenShift). Using `SELECT FOR UPDATE SKIP LOCKED` as a work queue avoids adding Redis, RabbitMQ, or Celery infrastructure. This pattern is battle-tested at scale (Stripe, GitHub).

## Decision

**One container image, four entrypoints.** The same image serves all deployment targets by varying the command:

| Entrypoint | Mode | Use case |
|---|---|---|
| `apme check .` | CLI | Developer workstation, CI/CD |
| `apme fix .` | CLI | Developer workstation, CI/CD |
| `apme format .` | CLI | Developer workstation, CI/CD |
| `apme-server --port 8090` | REST API server | Bootc sidecar, OpenShift sidecar |
| `apme-worker --db postgresql://...` | Queue worker | OpenShift batch scanning |

### Mode 1: CLI

Unchanged from today. `apme check`, `apme fix`, `apme format` with stdout/JSON/SARIF/JUnit output. Process starts, scans, prints results, exits.

### Mode 2: Server (REST API)

FastAPI application providing:

```
POST   /api/v1/scans/async           Queue async scan (returns scan_id)
GET    /api/v1/scans/{scan_id}       Poll status and results
POST   /api/v1/check                  Synchronous check (for small projects)
GET    /api/v1/entities/{ref}/quality Quality summary for catalog entity
WS     /api/v1/scans/{id}/stream     Real-time progress (WebSocket)
GET    /health                        Health check
```

Persistence: PostgreSQL (shared with portal, separate schema) or SQLite (standalone).

This extends Gateway (ADR-029) and implements Public Data API (ADR-038). In bootc/OpenShift sidecar mode, the server IS the gateway — there's no separate Gateway container.

### Mode 3: Worker

Background process that:
1. Connects to PostgreSQL scan_queue table
2. Claims pending jobs (`SELECT FOR UPDATE SKIP LOCKED`)
3. Clones repo, runs `apme.check()` (in-process)
4. Stores results in PostgreSQL
5. Loops to next job

Workers are stateless and horizontally scalable. In OpenShift, KEDA ScaledObject scales workers 0→N based on queue depth, and back to 0 when idle.

### Bootc deployment

One quadlet file:

```ini
[Container]
Image=registry.redhat.io/aap/apme-rhel9:latest
ContainerName=portal-apme
Network=portal-network
PublishPort=127.0.0.1:8090:8090
Exec=apme-server --port 8090 --db postgresql://portal-postgres:5432/apme

[Service]
Restart=always
After=postgres.service
ConditionPathExists=/etc/portal/.setup-complete
```

### OpenShift deployment

Sidecar in RHDH pod (Helm chart values.yaml):

```yaml
extraContainers:
  - name: apme-server
    image: registry.redhat.io/aap/apme-rhel9:latest
    command: ["apme-server", "--port", "8090"]
    ports: [{containerPort: 8090}]
```

Workers for batch scanning (separate Deployment):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: apme-worker
spec:
  replicas: 0  # KEDA controls
  template:
    spec:
      containers:
        - name: worker
          image: registry.redhat.io/aap/apme-rhel9:latest
          command: ["apme-worker", "--db", "postgresql://..."]
```

### Container contents

```
/usr/bin/apme              CLI entrypoint
/usr/bin/apme-server       REST API server (uvicorn + FastAPI)
/usr/bin/apme-worker       Queue worker
/usr/bin/opa               OPA binary (~50MB, static)
/usr/bin/gitleaks          Gitleaks binary (~15MB, static)
/data/ansible-core/        Pre-built module metadata (ADR-048)
/opt/apme/                 Python library + rules + Rego bundle
```

## Alternatives Considered

### Alternative 1: Separate images per deployment target

**Pros**: Smaller images (CLI image doesn't need FastAPI). Targeted optimization.

**Cons**: Multiple build pipelines, multiple registries, version drift between images. More moving parts for users.

**Why not chosen**: One image is simpler to build, test, distribute, and version. The overhead of bundling FastAPI + uvicorn (~5MB) in CLI-only deployments is negligible.

### Alternative 2: Celery + Redis for async scanning

**Pros**: Mature, well-documented, rich ecosystem.

**Cons**: Requires Redis deployment (new infrastructure). Redis persistence needs configuration for durability. Another StatefulSet in OpenShift, another container in bootc.

**Why not chosen**: PostgreSQL is already deployed for the portal. `SELECT FOR UPDATE SKIP LOCKED` provides exactly-once delivery without additional infrastructure.

## Consequences

### Positive

- One container image for all targets
- Bootc: 1 quadlet file instead of 7
- OpenShift: 1 sidecar + optional worker Deployment
- CI/CD: `apme check .` with <2s cold start
- Async batch scanning without new infrastructure (PostgreSQL queue)
- KEDA scales workers to 0 when idle (zero cost)

### Negative

- FastAPI bundled in CLI image (minor size increase)
- Worker mode requires PostgreSQL access
- KEDA dependency for auto-scaling in OpenShift

### Neutral

- CLI behavior unchanged
- AI escalation unchanged (Abbenay external)
- Rule implementations unchanged

## Related Decisions

- [ADR-024](ADR-024-thin-cli-daemon-mode.md): Daemon mode — precedent for single-process execution
- [ADR-029](ADR-029-web-gateway-architecture.md): Gateway — server mode absorbs Gateway's role
- [ADR-038](ADR-038-public-data-api.md): Public data API — server mode implements this
- [ADR-046](ADR-046-single-process-core.md): Single-process core — architectural foundation

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-03-30 | Claude (proposal) | Initial proposal |
