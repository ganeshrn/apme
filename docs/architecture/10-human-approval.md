# 10 — Human Approval Flow

> Previous: [09 — Post-AI Deterministic Pass](09-post-ai-deterministic.md) | Next: [11 — Result Assembly](11-result-assembly.md)

## Purpose

AI-generated fixes require human review before being applied. This stage
covers how proposals are presented to the user, how approvals/rejections
are processed, and the differences between check mode, interactive mode,
and auto-approve mode.

## Sequence

```mermaid
sequenceDiagram
    participant Primary as PrimaryServicer
    participant CLI as CLI / UI

    Note over Primary: AI proposals generated
    Primary-->>CLI: ProposalsReady(proposals[])

    alt Check mode
        CLI->>Primary: ApprovalRequest(approved_ids=[])
        Note over CLI: Declines all — read-only
    else Interactive mode
        loop For each proposal
            CLI->>CLI: Display diff + explanation
            CLI->>CLI: Prompt: y/n/a/s/q
        end
        CLI->>Primary: ApprovalRequest(approved_ids=[...])
    else Auto-approve mode (--auto-approve)
        CLI->>Primary: ApprovalRequest(approved_ids=[all])
    end

    Primary->>Primary: _session_apply_approved(approved_ids)
    Primary-->>CLI: ApprovalAck(applied_count)
    Primary->>Primary: _session_build_result()
    Primary-->>CLI: SessionResult
```

## ProposalsReady Event

When the graph engine produces AI proposals, the Primary converts them to
`Proposal` proto messages and emits a `ProposalsReady` event:

```protobuf
message Proposal {
  string id = 1;           // "ai-0000", "ai-0001", ...
  string file = 2;
  string rule_id = 3;
  int32 line_start = 4;
  int32 line_end = 5;
  string before_text = 6;  // Original YAML
  string after_text = 7;   // Proposed YAML
  string diff_hunk = 8;    // Unified diff
  float confidence = 9;
  string explanation = 10;
  int32 tier = 11;          // 2 for AI
  string status = 12;       // "proposed"
  string source = 14;       // "ai"
}
```

Proposal IDs follow the pattern `ai-NNNN` (zero-padded index).

## Check Mode

In check mode (no `FixOptions`), the CLI automatically declines all proposals:

```python
if oneof == "proposals":
    cmd_queue.put(SessionCommand(approve=ApprovalRequest(approved_ids=[])))
```

This ensures `check` is always a read-only assessment — it shows what
remediation would change without making any modifications.

## Interactive Review

`src/apme_engine/cli/remediate.py` — `_interactive_review()` presents each
proposal with:

- Rule ID, file path, line range, confidence score
- Explanation text
- Unified diff hunk

User choices:

| Key | Action |
|-----|--------|
| `y` | Accept this proposal |
| `n` | Skip this proposal |
| `a` | Accept all remaining proposals |
| `s` | Skip all remaining proposals |
| `q` | Abort the entire review |

Returns a list of approved proposal IDs.

## Auto-Approve Mode

With `--auto-approve`, all proposals are accepted without review:

```python
if getattr(args, "auto_approve", False):
    approved = [p.id for p in proposals]
```

Useful for CI pipelines where human review is not practical.

## Applying Approvals

`PrimaryServicer._session_apply_approved()` processes the `ApprovalRequest`:

### Graph-Based Proposals (AI)

For proposals with `id` starting with `"ai-"`:

1. Map proposal IDs back to graph node IDs via `proposal_node_map`
2. For approved proposals: `graph.approve_node(node_id)` — promotes the
   latest progression entry
3. For rejected proposals: `graph.reject_node(node_id)` — reverts to the
   last approved state
4. Re-splice modifications to update working files

### Legacy Text-Based Proposals

For non-graph proposals (backward compatibility), uses text-based
find/replace on `session.working_files`.

## Session Status Transitions

```
PROCESSING → AWAITING_APPROVAL (when proposals emitted)
AWAITING_APPROVAL → COMPLETE (after approval processed)
```

If no AI proposals are generated, the session goes directly from PROCESSING
to COMPLETE.

## Gateway/UI Approval

The Gateway bridges WebSocket connections to the `FixSession` gRPC stream.
The approval flow is the same — `ApprovalRequest` with approved IDs — but
delivered via WebSocket message instead of CLI prompt.

## Key Source Files

| File | Key types/functions |
|------|---------------------|
| `src/apme_engine/daemon/primary_server.py` | `_session_apply_approved()`, `_build_graph_proposals()`, `_apply_graph_approvals()` |
| `src/apme_engine/cli/remediate.py` | `_interactive_review()`, `_prompt_ynasq()` |
| `src/apme_engine/cli/check.py` | Auto-decline on `proposals` event |
| `proto/apme/v1/primary.proto` | `Proposal`, `ProposalsReady`, `ApprovalRequest`, `ApprovalAck` |

## Related ADRs

- **ADR-028** — FixSession bidirectional streaming
- **ADR-039** — Unified check/remediate through FixSession

---

> Next: [11 — Result Assembly](11-result-assembly.md)
