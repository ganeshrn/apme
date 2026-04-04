# 16 — Diagnostics Instrumentation

> Previous: [15 — Concurrency Model](15-concurrency-model.md) | Next: [17 — Scaling and Deployment Topology](17-scaling-and-deployment.md)

## Purpose

Every validator and the engine collect structured timing data on every
request. Diagnostics flow through the gRPC contract as first-class proto
messages — no log parsing required. This document covers the proto
definitions, per-validator instrumentation, and how timing data surfaces
in the CLI and Gateway.

## Proto Messages

`proto/apme/v1/common.proto` defines the diagnostics hierarchy:

### RuleTiming

Per-rule timing from a single validator:

```protobuf
message RuleTiming {
  string rule_id = 1;
  double elapsed_ms = 2;
  int32  violations = 3;
}
```

### ValidatorDiagnostics

Per-validator summary for one request:

```protobuf
message ValidatorDiagnostics {
  string validator_name = 1;
  string request_id = 2;
  double total_ms = 3;
  int32  files_received = 4;
  int32  violations_found = 5;
  repeated RuleTiming rule_timings = 6;
  map<string, string> metadata = 7;
}
```

The `metadata` map carries validator-specific key-value pairs (e.g.,
`opa_query_ms`, `ansible_core_version`).

### ScanDiagnostics

Aggregated diagnostics for an entire scan, returned in the
`SessionResult`:

```protobuf
message ScanDiagnostics {
  double engine_parse_ms = 1;
  double engine_annotate_ms = 2;
  double engine_total_ms = 3;
  int32  files_scanned = 4;
  int32  graph_nodes_built = 5;
  int32  total_violations = 6;
  repeated ValidatorDiagnostics validators = 7;
  double fan_out_ms = 8;
  double total_ms = 9;
}
```

## Data Flow

```
Validator → ValidateResponse.diagnostics (ValidatorDiagnostics)
                    ↓
Primary aggregates all ValidatorDiagnostics + engine timing
                    ↓
SessionResult.diagnostics (ScanDiagnostics)
                    ↓
            ┌───────┴────────┐
            ▼                ▼
    CLI renders          Gateway persists
    with -v / -vv        as diagnostics_json
```

Each validator returns its `ValidatorDiagnostics` in the
`ValidateResponse`. The Primary collects all of them, adds engine-level
timing, and assembles the `ScanDiagnostics`. This travels two paths:
back to the CLI via the `SessionResult`, and to the Gateway via
`FixCompletedEvent` for persistence.

## Per-Validator Instrumentation

### Engine (Primary)

The engine (`run_scan()`) reports per-phase timing:

| Metric | What it measures |
|--------|-----------------|
| `engine_parse_ms` | Target load + PRM load + metadata load |
| `engine_annotate_ms` | Call-graph construction (includes ContentGraph build) |
| `engine_total_ms` | Wall-clock for the full engine run |
| `files_scanned` | Number of files processed |
| `graph_nodes_built` | Nodes in the ContentGraph |

### Native Validator

| Metric | Source |
|--------|--------|
| Per-rule `elapsed_ms` | Engine's `detect()` timing records per rule function |
| Per-rule `violations` | Count from each rule's results |

No additional metadata — timing comes directly from the rule engine's
instrumentation.

### OPA Validator

| Metric | Source |
|--------|--------|
| `total_ms` | End-to-end `opa eval` subprocess time |
| Per-rule `violations` | Parsed from OPA JSON output |
| `metadata["opa_query_ms"]` | OPA subprocess query time |
| `metadata["opa_response_size"]` | Bytes in OPA JSON response |

### Ansible Validator

| Metric | Source |
|--------|--------|
| `total_ms` | End-to-end validation time |
| Per-phase timing | L057 syntax, M001–M004 introspection, L058 argspec-doc, L059 argspec-mock |
| `metadata["ansible_core_version"]` | Version from the session venv |
| `metadata["venv_build_ms"]` | Time to prepare/verify the venv (0 on warm hit) |

### Gitleaks Validator

| Metric | Source |
|--------|--------|
| `total_ms` | End-to-end subprocess time |
| `metadata["subprocess_ms"]` | Gitleaks binary execution time |
| `metadata["files_written"]` | Number of files written to temp dir |

## CLI Verbosity

The CLI uses `ScanDiagnostics` to render timing information at different
verbosity levels:

### No flag — violations only

No diagnostics displayed.

### `-v` — summary diagnostics

`print_diagnostics_v()` renders a compact tree:

```
  Engine:       45ms (parse: 12ms, annotate: 8ms)
  Files:        23
  Fan-out:      120ms
  ├── Native       80ms |  12 violation(s)
  ├── Opa          95ms |   3 violation(s)
  └── Ansible      110ms |   2 violation(s)
  Total:        165ms
```

### `-vv` — full per-rule breakdown

`print_diagnostics_vv()` adds per-rule timing for every validator:

```
  Engine:       45ms (parse: 12ms, annotate: 8ms)
  Files:        23, Nodes: 156
  Fan-out:      120ms
  ├── Native       80ms |  12 violation(s)
  │   ├── L026    12ms |  3 violations
  │   ├── L030     8ms |  2 violations
  │   └── M005    15ms |  1 violation
  ├── Opa          95ms |   3 violation(s)
  │   ├── L003     5ms |  1 violation
  │   └── P001    12ms |  2 violations
  └── Ansible      110ms |   2 violation(s)
      ├── M001    45ms |  1 violation
      └── L057    30ms |  1 violation
  Total:        165ms
```

### JSON output

With `--json` and `-v`/`-vv`, the `diagnostics` key is included in the
JSON output as a nested object matching the `ScanDiagnostics` structure.

## Gateway Persistence

The Gateway stores diagnostics as a JSON string in
`scans.diagnostics_json`. The `ReportingServicer` serializes the
`ScanDiagnostics` proto to JSON via `_diagnostics_to_json()`:

```python
{
    "engine_parse_ms": 12.3,
    "engine_annotate_ms": 8.1,
    "engine_total_ms": 45.5,
    "files_scanned": 23,
    "graph_nodes_built": 156,
    "total_violations": 17,
    "fan_out_ms": 120.0,
    "total_ms": 165.2
}
```

The REST API exposes this via `GET /api/v1/activity/{id}` in the
`diagnostics_json` field. The UI can parse and render timing breakdowns
from this data.

## Key Source Files

| File | Role |
|------|------|
| `proto/apme/v1/common.proto` | `RuleTiming`, `ValidatorDiagnostics`, `ScanDiagnostics` |
| `src/apme_engine/daemon/primary_server.py` | Aggregates validator diagnostics + engine timing |
| `src/apme_engine/runner.py` | Engine phase timing (`parse_ms`, `annotate_ms`) |
| `src/apme_engine/cli/output.py` | `print_diagnostics_v()`, `print_diagnostics_vv()` |
| `src/apme_gateway/grpc_reporting/servicer.py` | `_diagnostics_to_json()` for persistence |

## Related ADRs

- **ADR-001** — gRPC for all inter-service communication (diagnostics ride the same transport)

---

> Next: [17 — Scaling and Deployment Topology](17-scaling-and-deployment.md)
