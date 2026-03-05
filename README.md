# Ansible Forward (APME Engine)

Ansible Policy & Modernization Engine — a multi-validator static analysis platform for Ansible content. It parses playbooks, roles, collections, and task files into a structured hierarchy, then fans validation out in parallel across three independent backends (OPA/Rego, native Python, and Ansible-runtime) to produce a single, unified list of violations.

## Architecture at a glance

```
┌─────────┐      gRPC       ┌───────────┐      gRPC (parallel)      ┌────────────┐
│   CLI   │ ──────────────► │  Primary   │ ──────────────────────►   │   Native   │ :50055
│ (on-the │  ScanRequest    │ (orchestr) │   ValidateRequest         │  (Python)  │
│  -fly)  │  chunked fs     │            │ ┌─────────────────────►   ├────────────┤
└─────────┘                 │   Engine   │ │                         │    OPA     │ :50054
     ▲                      │  ┌──────┐  │ │  ┌──────────────────►   │  (Rego)   │
     │   ScanResponse       │  │parse │  │ │  │                      ├────────────┤
     │   violations         │  │annot.│  │ │  │                      │  Ansible   │ :50053
     └──────────────────────│  │hier. │  ├─┘  │                      │ (runtime)  │
                            │  └──────┘  ├────┘                      └────────────┘
                            └───────────┘
                                 │
                            ┌────┴────┐
                            │  Cache  │ :50052
                            │Maintainr│
                            └─────────┘
```

Six containers, one pod. All inter-service communication is gRPC. The CLI is run on-the-fly with the project directory mounted. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Key features

- **Single parse, multiple validators** — the engine parses Ansible content once and produces a hierarchy payload + scandata; validators consume it independently.
- **Parallel fan-out** — Primary calls Native, OPA, and Ansible validators concurrently via `ThreadPoolExecutor`; total latency = max(validators), not sum.
- **Unified gRPC contract** — every validator implements the same `Validator` service (`validate.proto`); adding a new validator means implementing one RPC.
- **100+ rules** across three backends: OPA Rego (L001–L025, R118), native Python (L026–L056, R101–R501), Ansible runtime (L057–L059, M001–M004).
- **Multi ansible-core version support** — the Ansible validator pre-builds venvs for ansible-core 2.18, 2.19, 2.20; argspec and deprecation checks run against the requested version.
- **Collection cache** — pull from Galaxy or clone GitHub orgs; mount read-only into the Ansible validator. Managed by a dedicated Cache Maintainer service.
- **Colocated tests** — every rule has a `*_test.py` (native), `*_test.rego` (OPA), or `.md` doc with violation/pass examples usable as integration tests.

## Quick start

### Local development (no containers)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"

# Run a scan
apme-scan /path/to/playbook-or-project

# JSON output
apme-scan --json .

# Skip specific validators
apme-scan --no-opa .
apme-scan --no-native .
```

### Container deployment (Podman)

```bash
# Build all images
./containers/podman/build.sh

# Start the pod (Primary + Native + OPA + Ansible + Cache Maintainer)
./containers/podman/up.sh

# Scan a project (CLI container, on-the-fly)
cd /path/to/your/project
/path/to/ansible-forward/containers/podman/run-cli.sh

# With options
containers/podman/run-cli.sh --json .
```

### Health check

```bash
apme-scan health-check --primary-addr 127.0.0.1:50051
```

## Scaling

Scale pods, not services within a pod. Each pod is a self-contained stack that can process a scan request end-to-end. For more throughput, run multiple pods behind a load balancer. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#scaling).

## Tests

```bash
pip install -e ".[dev]"

# Unit + colocated rule tests
pytest

# With coverage
pytest --cov=src/apme_engine --cov-report=term-missing --cov-fail-under=95

# End-to-end integration (requires Podman + built images)
pytest -m integration tests/integration/test_e2e.py
```

## Project layout

```
proto/apme/v1/          gRPC service definitions (.proto)
src/apme/v1/            generated Python gRPC stubs
src/apme_engine/
  ├── engine/           ARI-based scanner (parse, annotate, hierarchy)
  │   └── annotators/   per-module risk annotators
  ├── validators/
  │   ├── base.py       Validator protocol + ScanContext
  │   ├── native/       Python rules (L026–L056, R101–R501)
  │   ├── opa/          Rego bundle (L001–L025, R118)
  │   └── ansible/      Ansible-runtime rules (L057–L059, M001–M004)
  ├── daemon/           gRPC server implementations
  ├── collection_cache/ Galaxy/GitHub cache management
  ├── cli.py            CLI entry point
  └── runner.py         scan orchestration
containers/             Dockerfiles + Podman pod config
docs/                   architecture, design, rule mapping
tests/                  unit, integration, rule doc coverage
```

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Container topology, gRPC contracts, data flow, scaling model |
| [DATA_FLOW.md](docs/DATA_FLOW.md) | Request lifecycle, engine pipeline, serialization formats |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Podman pod setup, configuration, troubleshooting |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Adding rules, proto generation, testing, code organization |
| [DESIGN_VALIDATORS.md](docs/DESIGN_VALIDATORS.md) | Validator abstraction rationale and design decisions |
| [LINT_RULE_MAPPING.md](docs/LINT_RULE_MAPPING.md) | Complete rule ID cross-reference (L/M/R/P) |
| [ANSIBLELINT_COVERAGE.md](docs/ANSIBLELINT_COVERAGE.md) | Coverage vs ansible-lint, gap analysis |
| [RULE_DOC_FORMAT.md](docs/RULE_DOC_FORMAT.md) | Rule `.md` format for docs + integration tests |
| [ANSIBLE_CORE_MIGRATION.md](docs/ANSIBLE_CORE_MIGRATION.md) | ansible-core 2.19/2.20 breaking changes and rule mapping |
| [PODMAN_OPA_ISSUES.md](docs/PODMAN_OPA_ISSUES.md) | Podman rootless troubleshooting |

## Roadmap

- **Phase 2** — Remediation engine: suggest and apply fixes, opt-in, re-scan.
- **Phase 3** — AI integration: OpenLLM daemon via gRPC for explanations, YAML generation, Q&A, review summaries.
- **Phase 4** — Web UI: dashboards, findings management, remediation queue, enterprise tracking.

## License

Apache-2.0
