# 12 — CLI Output and Presentation

> Previous: [11 — Result Assembly](11-result-assembly.md) | Next: [13 — Gateway and Persistence](13-gateway-and-persistence.md)

## Purpose

After the `SessionResult` arrives at the CLI, the output layer renders
violations, diffs, and summaries for the user. This stage covers ANSI
rendering, JSON output, patch writing, and exit codes.

## Output Modes

### ANSI (Default)

`src/apme_engine/cli/output.py` provides rich terminal output:

**`render_check_results()`** — the main output function for `check`:

1. **Summary box** — PASSED/FAILED status, severity counts, remediation
   breakdown, scan time
2. **Issue table** — rule ID, severity badge, remediation badge, message,
   location
3. **File tree** — grouped by file with tree-drawing characters and severity
   indicators

Example output:
```
┌─ Check Results ──────────────────────────────────────┐
│ Status: PASSED                                       │
│ Scan ID: abc123                                      │
│ Issues: 2 medium, 1 low                              │
│ Remediation: 2 auto-fixable, 1 AI-candidate          │
└──────────────────────────────────────────────────────┘

Issues
 Rule   Severity  Remediation   Message              Location
 L007   medium    auto-fixable  Use command instead   tasks/main.yml:12
 ...

Issues by File
├── tasks/main.yml (2)
│   ├── ● L12 [L007] Use command instead of shell
│   └── ● L25 [M001] Use FQCN for module
└── handlers/main.yml (1)
    └── ○ L3  [L011] Task name should be descriptive
```

### JSON (--json)

Both `check` and `remediate` support `--json` for structured output:

```json
{
  "violations": [...],
  "count": 3,
  "scan_id": "abc123",
  "remediation_summary": {
    "auto_fixable": 2,
    "ai_candidate": 1,
    "manual_review": 0
  },
  "resolution_summary": {...},
  "diffs": [
    {"path": "tasks/main.yml", "diff": "--- a/tasks/main.yml\n..."}
  ]
}
```

### Diff Output (check --diff)

`check --diff` shows unified diffs of what `remediate` would change, without
actually modifying files:

```diff
--- a/tasks/main.yml
+++ b/tasks/main.yml
@@ -12,3 +12,3 @@
-    - shell: echo hello
+    - ansible.builtin.command: echo hello
```

## Remediate Output

`src/apme_engine/cli/remediate.py` handles remediate-specific rendering:

**`_render_tier1()`** — shows format diffs count, idempotency warning,
remediation passes/fixed/remaining counts, applied patches.

**`_render_remaining()`** — after patches are written, shows counts of
remaining Tier 2 (fixable with `--ai`) and Tier 3 (manual review) violations.

## Patch Writing

`_write_patches()` writes patched files to disk with a safety check:

```python
def _safe_write(path, expected_original, new_content):
    current = path.read_bytes()
    if current != expected_original:
        # File modified since scan — skip to avoid data loss
        return
    path.write_bytes(new_content)
```

The content hash check prevents overwriting files that were modified between
the scan and the write (e.g., by an editor).

## Progress Rendering

During the scan, `ProgressUpdate` events stream to stderr:

```python
min_level = {0: 3, 1: 2}.get(verbosity, 1)
# 0 (no flag): WARNING and above
# 1 (-v):      INFO and above
# 2+ (-vv):    DEBUG and above
```

Format: `  [phase] message` with color coding by level.

## Diagnostics

With `-v`, `print_diagnostics_v()` shows a concise timing summary:

```
  Engine:       45ms (parse: 12ms, annotate: 8ms)
  Files:        23
  Fan-out:      120ms
  ├── Native       80ms |  12 violation(s)
  ├── Opa          95ms |   3 violation(s)
  └── Ansible      110ms |   2 violation(s)
  Total:        165ms
```

With `-vv`, `print_diagnostics_vv()` adds per-rule timing breakdowns.

## Exit Codes

| Code | Constant | Meaning |
|------|----------|---------|
| 0 | `EXIT_SUCCESS` | No violations (or all fixed) |
| 1 | `EXIT_VIOLATIONS` | Violations remain |
| 2 | `EXIT_ERROR` | Runtime error (gRPC failure, file not found, etc.) |

## Key Source Files

| File | Key functions |
|------|---------------|
| `src/apme_engine/cli/output.py` | `render_check_results()`, `render_logs()`, `format_remediation_summary()`, `print_diagnostics_v()`, `print_diagnostics_vv()` |
| `src/apme_engine/cli/check.py` | JSON output, diff output, exit codes |
| `src/apme_engine/cli/remediate.py` | `_render_tier1()`, `_write_patches()`, `_safe_write()`, `_render_remaining()` |
| `src/apme_engine/cli/ansi.py` | ANSI color helpers, box/table/badge formatters |
| `src/apme_engine/cli/_exit_codes.py` | `EXIT_SUCCESS`, `EXIT_VIOLATIONS`, `EXIT_ERROR` |

---

> Next: [13 — Gateway and Persistence](13-gateway-and-persistence.md)
