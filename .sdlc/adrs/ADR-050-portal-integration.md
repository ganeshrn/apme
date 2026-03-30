# ADR-050: Portal and Backstage Integration

## Status

Proposed

## Date

2026-03-30

## Context

APME will be deployed alongside the Ansible self-service portal (Red Hat Developer Hub with Ansible Backstage plugins). The portal catalogs Ansible collections from Git repositories (`AnsibleGitContentsProvider`), Automation Hub (`PAHCollectionProvider`), and AAP (`AAPJobTemplateProvider`). When collections are cataloged, they should be scanned by APME for quality, security, and migration readiness.

### Deployment targets

The portal deploys in two models:

1. **OpenShift** — RHDH via Helm chart (`ansible-portal-chart`). APME runs as a sidecar container in the RHDH pod (ADR-047) and as KEDA-scaled workers for batch scanning.

2. **RHEL bootc appliance** — Podman Quadlet systemd services (`automation-portal-bootc-container`). APME runs as a single Quadlet container on the `portal-network` bridge, alongside `portal` (RHDH), `portal-postgres` (PostgreSQL), and `portal-devtools` (ADT).

Both models use the same APME container image with the `apme-server` entrypoint (ADR-047).

### Security context

An audit of the portal's existing sidecar model (devtools on port 8000) reveals several security gaps that APME must not inherit:

| Finding | DevTools (current) | Risk | APME approach |
|---|---|---|---|
| **No authentication** | Zero auth between portal and devtools. Any container on `portal-network` can call devtools APIs. | HIGH — a compromised container can invoke code generation. | Opt-in API key via `APME_API_KEY` env var. When set, all requests require `X-API-Key` header. When unset (sidecar mode), network isolation is primary boundary. |
| **Runs as root** | DevTools container has no `User` directive — defaults to root. | HIGH — container escape gives root on host. | APME runs as non-root (`USER 1001`). All capabilities dropped. |
| **No input validation** | Scaffolder passes user-supplied `namespace` and `collection_name` directly to devtools API without validation. | MEDIUM — potential for path traversal or injection in generated content. | APME validates all input: `repo_url` must be https/git scheme (no `file://`), `ref` must match `[a-zA-Z0-9._/-]`, `ansible_version` must be in supported set. |
| **No TLS** | Plain HTTP between portal and devtools. | LOW for same-pod (localhost), MEDIUM for bridge network (sniffable). | Same as devtools — plain HTTP for same-pod/bridge. TLS available via reverse proxy if APME is exposed externally. |
| **No rate limiting** | Unlimited requests. | LOW — only portal calls it. | Configurable rate limit on async scan endpoint (default: 100 scans/minute). Prevents queue flooding. |
| **No audit logging** | No record of who called what. | MEDIUM — no forensic trail. | All API calls logged with timestamp, endpoint, source IP, scan parameters. Scan results stored in PostgreSQL with full provenance. |

The devtools model is adequate for a **same-pod sidecar with a single trusted caller** but has gaps that compound with network exposure. APME improves on this baseline while remaining proportionate to the threat model.

### Integration pattern

The portal's existing plugins follow a consistent pattern:
- **Backend module** (TypeScript) implements Backstage's `EntityProvider` interface for catalog sync
- **Frontend plugin** (React) renders entity details with custom components
- **Service client** (TypeScript) communicates with backend services via HTTP

APME integration follows this same pattern: a Backstage backend module triggers scans, a frontend plugin displays results, and the APME server provides the REST API.

### Relationship to existing ADRs

- ADR-029 (Gateway) defined the REST API and persistence layer. In the single-process model (ADR-046), the server mode absorbs the Gateway's role.
- ADR-038 (Public Data API, Proposed) defined the consumer contract. This ADR implements ADR-038's vision with concrete endpoints and the Backstage plugin.
- ADR-037 (Project-centric UI) defined the dashboard model. The portal integration is complementary — the portal shows collection-level quality metadata, while the standalone dashboard (if deployed) shows detailed violation management.

## Decision

**APME integrates with the portal via a REST API (server mode) and a Backstage dynamic plugin.**

### REST API endpoints (APME server)

Extends the API defined in ADR-047's server mode:

```
# Sync scan with uploaded content (portal sends files directly)
POST /api/v1/check
  Body: multipart/form-data
    files: <collection content as tar.gz or individual files>
    ansible_version: "2.18"
    entity_ref: "component:default/acme.webstack"
  Returns: {scan_id, status, violations, summary}

# Async scan with uploaded content (for large collections)
POST /api/v1/scans/async
  Body: multipart/form-data
    files: <collection content as tar.gz or individual files>
    ansible_version: "2.18"
    entity_ref: "component:default/acme.webstack"
  Returns: {"scan_id": "uuid", "status": "queued"}

# Async scan with content path (shared workspace)
POST /api/v1/scans/async
  Body: {
    "workspace_path": "/workspace/acme.webstack",
    "ansible_version": "2.18",
    "entity_ref": "component:default/acme.webstack"
  }
  Returns: {"scan_id": "uuid", "status": "queued"}

# Poll scan status
GET /api/v1/scans/{scan_id}
  Returns: {
    "status": "completed",
    "summary": {
      "quality_score": 82,
      "total_violations": 14,
      "by_severity": {"error": 2, "warning": 7, "info": 5},
      "by_category": {"lint": 8, "security": 2, "migration": 4},
      "migration_ready": {"2.18": true, "2.19": false}
    },
    "violations": [...]
  }

# Quality summary for catalog entity (consumed by Backstage plugin)
GET /api/v1/entities/{entity_ref}/quality
  Returns: {
    "entity_ref": "component:default/acme.webstack",
    "quality_score": 82,
    "security_issues": 2,
    "migration_status": {"2.18": "ready", "2.19": "needs_work"},
    "last_scan": "2026-03-30T10:15:00Z",
    "scan_id": "uuid"
  }
```

**Content delivery model**: The portal is the content broker, not APME. The portal already has authenticated access to all content sources (GitHub, GitLab, Automation Hub). The portal downloads collection content and passes it to APME via:

1. **Multipart upload** (POST /api/v1/check or /api/v1/scans/async) — portal sends files directly. Works in all deployments including air-gapped.
2. **Shared workspace** (POST /api/v1/scans/async with `workspace_path`) — portal writes content to a shared volume, APME reads from it. Efficient for large collections; avoids copying over HTTP.

This eliminates the need for APME to have SCM tokens, PAH credentials, or network access to external content sources. APME receives content; the portal handles acquisition and authentication.

### Backstage dynamic plugin

A new plugin package `@ansible/backstage-plugin-apme` with two components:

**Backend module** (`catalog-backend-module-apme`):
- Implements Backstage `EntityProvider` interface
- Listens for catalog entity change events
- When a new Ansible collection entity appears, triggers `POST /api/v1/scans/async` to the APME server
- Configurable scan schedule (default: on catalog sync, configurable interval)

**Frontend plugin** (`plugin-apme`):
- **APMEQualityCard**: Entity detail page card showing quality score, security status, migration readiness
- **APMEViolationsTab**: Detailed violation list with rule IDs, severity badges, file/line references, and snippets
- Fetches data from APME server via `GET /api/v1/entities/{entity_ref}/quality`

### Configuration

In RHDH `app-config.yaml`:

```yaml
ansible:
  apme:
    baseUrl: ${APME_HOST:-portal-apme}
    port: '8090'

catalog:
  providers:
    apme:
      schedule:
        frequency: { minutes: 60 }
        timeout: { minutes: 30 }
```

### Bootc integration

The `portal-setup` wizard (or cloud-init config) includes APME configuration:

```yaml
# /run/cloud-init/portal-config.yaml
apme:
  enabled: true
  ansible_version: "2.18"
```

The APME container starts after PostgreSQL and the portal, joins the `portal-network`, and is reachable at `portal-apme:8090`.

### Security model

#### Threat model by deployment

**Bootc appliance (single VM):**
- Trust boundary: the VM itself. The operator controls all containers.
- APME port 8090 is bound to the bridge network only (`PublishPort=127.0.0.1:8090:8090`), NOT exposed to the host's external interfaces.
- Attack path: an attacker must first compromise the portal or another container on `portal-network` — at which point they already have access to PostgreSQL credentials and AAP tokens. APME is not the meaningful security boundary.
- Network isolation is the primary defense. Opt-in API key adds defense-in-depth.

**OpenShift sidecar (same pod):**
- Trust boundary: the pod. All containers share localhost (127.0.0.1).
- APME port 8090 is not exposed via Service or Route. Only containers in the same pod can reach it.
- Other pods in the namespace cannot reach APME unless a Service is explicitly created.
- NetworkPolicy on worker Deployment denies all inbound traffic (workers only connect outbound to PostgreSQL).

**Workers (separate Deployment):**
- Workers have no inbound ports. They connect outbound to PostgreSQL only.
- PostgreSQL authentication: password via Kubernetes Secret, separate `apme` schema (cannot read/write portal tables).
- Workers receive content via the scan queue (portal uploaded content to shared workspace or inline in the queue row). Workers do not need SCM tokens or PAH credentials — the portal handles content acquisition.

#### APME-specific attack surface

APME has attack surface beyond what devtools has:

| Capability | Risk | Mitigation |
|---|---|---|
| **Content ingestion** (receives files from portal or CLI) | Path traversal — a malicious archive could contain `../../etc/passwd` paths. Zip bomb — large decompressed content exhausting disk. | Archive extraction uses `tarfile.data_filter` (Python 3.12+) or manual path validation rejecting absolute paths and `..` components. Extraction to isolated temp directory with size quota (2 GiB). Cleanup in `finally` block. When receiving `workspace_path`, validate it's within the allowed workspace root. |
| **YAML parsing** (processes untrusted Ansible content) | Billion-laughs (YAML bomb), excessive memory from deeply nested structures. | ruamel.yaml safe loader (no arbitrary Python object instantiation). Max file size 2 MiB (existing DATA_FLOW.md constraint). Max node depth limit. |
| **OPA subprocess** (runs `opa eval` with hierarchy payload) | Command injection if payload is interpolated into shell command. | Payload passed via stdin (`subprocess.run(input=...)`, not shell interpolation). No `shell=True`. |
| **Gitleaks subprocess** (runs `gitleaks detect`) | Limited — gitleaks reads files, doesn't execute them. | Subprocess with timeout. Non-zero exit code is informational (secrets found), not an error. |
| **PostgreSQL writes** (stores scan results) | SQL injection if violations are interpolated into queries. | SQLAlchemy parameterized queries only. No raw string interpolation. |
| **AI escalation** (sends content to Abbenay) | Content leakage to external AI provider. | AI is opt-in (`--ai` flag). Abbenay connection via gRPC with bearer token. Content sent only for Tier 2 violations, not entire repos. |

#### Container hardening

```ini
# apme.container (Quadlet)
[Container]
Image=registry.redhat.io/aap/apme-rhel9:latest
ContainerName=portal-apme
Network=portal-network
PublishPort=127.0.0.1:8090:8090
User=1001:0

# Read-only root filesystem
ReadOnly=true
# Writable tmpfs for scan workspace
Tmpfs=/tmp:rw,size=512m,noexec
Volume=/var/lib/apme/workspace:/workspace:Z

# Secrets (never in env files, never in image)
Secret=portal_apme_db_password,type=env,target=APME_DB_PASSWORD

# No extra capabilities
DropCapability=ALL

[Service]
Restart=always
RestartSec=10
After=postgres.service
ConditionPathExists=/etc/portal/.setup-complete
```

OpenShift equivalent:

```yaml
containers:
  - name: apme-server
    image: registry.redhat.io/aap/apme-rhel9:latest
    securityContext:
      runAsNonRoot: true
      runAsUser: 1001
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: [ALL]
    volumeMounts:
      - name: tmp
        mountPath: /tmp
      - name: workspace
        mountPath: /workspace
volumes:
  - name: tmp
    emptyDir:
      sizeLimit: 512Mi
  - name: workspace
    emptyDir:
      sizeLimit: 2Gi
```

#### Opt-in API key

When `APME_API_KEY` env var is set, all non-health endpoints require the key:

```python
@app.middleware("http")
async def check_api_key(request: Request, call_next):
    api_key = os.environ.get("APME_API_KEY")
    if api_key and request.url.path != "/health":
        provided = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(provided, api_key):
            return JSONResponse(
                status_code=401,
                content={"error": "invalid or missing API key"},
            )
    return await call_next(request)
```

When `APME_API_KEY` is not set: no auth enforced (sidecar mode where network isolation is sufficient). This is the default for bootc and OpenShift sidecar deployments.

When `APME_API_KEY` is set: required for all requests. Used when APME is exposed outside the pod boundary (e.g., shared APME server for multiple teams, CI/CD calling from external clusters).

The API key is stored as a Podman secret (bootc) or Kubernetes Secret (OpenShift), injected at runtime. It is never in configuration files, container images, or environment file templates.

#### Database isolation

APME uses a **separate PostgreSQL schema** from the portal:

```
Portal:  postgresql://portal-postgres:5432/backstage   (portal schema)
APME:    postgresql://portal-postgres:5432/apme         (apme schema)
```

The APME database user has `CONNECT` and `CREATE` on the `apme` database only. It cannot read or write portal tables (`backstage` database). This is enforced by PostgreSQL's native database-level isolation — no additional configuration needed beyond creating a separate database and user.

#### Secrets inventory

| Secret | Purpose | Who needs it | Rotation |
|---|---|---|---|
| `APME_DB_PASSWORD` | PostgreSQL auth for `apme` database | Server, Workers | On credential rotation; restart containers |
| `APME_API_KEY` | Optional API authentication | Server (validates), Portal plugin (sends) | On rotation; update both server and client |
| `APME_ABBENAY_TOKEN` | AI provider auth (Abbenay) | Server (if AI enabled) | Per Abbenay token lifecycle |

APME does **not** need and must **not** receive: `AAP_TOKEN`, `OAUTH_CLIENT_SECRET`, `POSTGRESQL_ADMIN_PASSWORD`, SCM tokens (`GITHUB_TOKEN`, `GITLAB_TOKEN`), or any portal-level secrets.

The portal is the content broker — it downloads collection content from SCMs and Automation Hub using its own credentials, then passes the content to APME. APME never contacts external content sources directly. This separation means:
- A compromised APME container cannot access AAP, Git repositories, or the portal's database
- APME needs only 2-3 secrets (database password, optional API key, optional AI token) vs the portal's 6+
- Air-gapped environments work without APME needing any network egress beyond the internal bridge

## Alternatives Considered

### Alternative 1: AAP job template integration

**Description**: Create an AAP job template that calls APME, expose via portal's existing job template catalog.

**Pros**: No new Backstage plugin. Uses existing portal infrastructure.

**Cons**: Requires AAP Controller deployment. Scans run as Ansible jobs (heavy). Results not integrated into catalog entity metadata. No quality badges on collection pages.

**Why not chosen**: APME is a lightweight scanning tool, not an Ansible job. Running it through AAP Controller adds unnecessary infrastructure.

### Alternative 2: Webhook-only integration

**Description**: APME server sends webhook on scan completion. Portal receives and stores results.

**Pros**: Decoupled. APME doesn't need to know about Backstage.

**Cons**: Requires webhook receiver in portal. More complex than direct API polling. Webhook delivery is not guaranteed (needs retry logic).

**Why not chosen**: Direct REST API polling is simpler and more reliable for the portal sidecar model where APME is on localhost.

## Consequences

### Positive

- Collections in the portal catalog automatically scanned for quality/security/migration
- Quality scores visible on collection detail pages
- Security issues surfaced before collections are used in automation
- Migration readiness visible per ansible-core version
- Same pattern as existing portal plugins (consistent DX)
- No new infrastructure (PostgreSQL shared with portal, separate schema)
- Security model improves on devtools baseline (non-root, input validation, opt-in API key, audit logging, read-only filesystem)
- Secret separation limits blast radius (APME cannot access AAP or portal secrets)

### Negative

- New Backstage plugin to maintain (TypeScript)
- APME server must be co-deployed with portal
- Quality scores may lag behind code changes (scan schedule dependent)
- Separate PostgreSQL database/user requires provisioning during setup

### Neutral

- APME's core scanning unchanged
- CI/CD integration unchanged (CLI mode)
- Standalone dashboard (if deployed) unchanged
- No mTLS between portal and APME (consistent with portal's existing sidecar model; network isolation is primary boundary)

## Related Decisions

- [ADR-029](ADR-029-web-gateway-architecture.md): Gateway — server mode absorbs Gateway's role
- [ADR-038](ADR-038-public-data-api.md): Public data API — this ADR implements it
- [ADR-046](ADR-046-single-process-core.md): Single-process core — server runs in one container
- [ADR-047](ADR-047-deployment-modes.md): Deployment modes — server mode and worker mode
- [ADR-048](ADR-048-pre-built-module-metadata.md): Lite mode — workers use lite mode for fast scanning

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-03-30 | Claude (proposal) | Initial proposal |
| 2026-03-30 | Claude (proposal) | Added security model: threat analysis, devtools audit findings, container hardening, input validation, opt-in API key, database isolation, secrets inventory |
| 2026-03-30 | Claude (proposal) | Corrected content delivery model: portal is the content broker (downloads from SCM/PAH and passes to APME). APME does not clone repos or need SCM/PAH credentials. Removed GIT_TOKEN from secrets inventory. Updated API to accept multipart uploads and shared workspace paths. Updated attack surface (content ingestion replaces git clone SSRF). |
