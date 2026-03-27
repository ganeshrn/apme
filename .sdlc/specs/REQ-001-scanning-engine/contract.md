# REQ-001: Contract

## gRPC Service

See `proto/apme/v1/validator.proto` for service definitions.

## CLI Interface

```bash
apme check <path> [--target-version VERSION] [--output FORMAT]
```

User-facing **check** maps to the engine’s internal scan pipeline (`ScanRequest`, `ScanResponse`, `scan_id`, etc.); names on the wire stay as in proto unless otherwise versioned.

## Output Schema

TBD - Define JSON/JUnit output structures.
