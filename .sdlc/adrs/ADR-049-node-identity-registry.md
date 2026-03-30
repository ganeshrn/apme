# ADR-049: Node Identity Registry

## Status

Proposed

## Date

2026-03-30

## Context

ADR-044 correctly identifies six problems with APME's current stateless scan model. This ADR agrees with the problem statement but proposes a simpler solution.

### Problems (from ADR-044, all valid)

1. **Snippet accuracy**: Snippets show post-format content, not the original the user wrote.
2. **Violation matching**: `(rule_id, file, line)` tuples break when transforms shift line numbers.
3. **Remediation attribution**: "Which transform fixed which violation?" is inferred, not tracked.
4. **Three representations**: ARI tree + StructuredFile + raw bytes synchronized via disk I/O.
5. **No temporal history**: No per-node progression through the pipeline.
6. **Inherited property mis-attribution**: R108 fires on every task inheriting `become` (50 violations) instead of once on the defining play (1 violation).

### Why ADR-044's ContentGraph is more than needed

ADR-044 proposes a `ContentGraph` built on `networkx.MultiDiGraph` with a 3-phase migration porting all 96 native rules to a `GraphRule` interface. After comprehensive analysis, this solution is disproportionate:

**networkx is unnecessary for this graph shape.** Ansible content graphs are small (100-1000 nodes), mostly trees with a few cross-edges. The algorithms ADR-044 lists (`is_directed_acyclic_graph`, `topological_sort`, `weakly_connected_components`, `is_isomorphic`) are each implementable in <20 lines with parent/children pointers. Adding a runtime dependency for capabilities achievable with basic data structures violates ADR-019's dependency governance principle.

**Porting 96 rules is the highest-risk part of the plan.** Per DESIGN_VALIDATORS.md, native rules access `ctx.current` (234 call sites), `task.spec` (50 sites), `task.file_info()` (73 sites). Changing every call site across 96 rules in Phase 2 while maintaining production stability is a large surface area with high regression risk. The ADR's "zero throwaway code" claim means the switchover is a cliff — everything changes at once.

**ContentGraph doesn't eliminate the three representations.** Per DATA_FLOW.md, OPA needs JSON hierarchy_payload, Gitleaks needs raw files, transforms need ruamel.yaml mutation. These exist because different consumers need different formats, not because of a missing identity model. The ContentGraph adds a fourth representation (the graph itself) alongside the existing three.

**Variable provenance, Python AST analysis, complexity metrics, topology visualization, and dependency quality scorecards** are bundled into ADR-044 but are independent concerns. Each should be a separate ADR. Bundling them inflates the implementation scope.

**The highest-impact problem (#6, inherited property mis-attribution) is solvable with ~30 lines.** A parent-chain walk from any node to its root, checking where a property is first defined, gives PropertyOrigin without a graph library.

### The simpler alternative

A `NodeRegistry` (~200 lines) that sits on top of the existing `hierarchy_payload` output from ARI. It adds identity and progression tracking without touching the engine, rules, validators, or serialization boundaries.

## Decision

**Build a NodeRegistry that assigns stable identities to ARI's hierarchy nodes and tracks their progression across pipeline passes.** ARI remains the parser. Rules remain on their current interfaces. The registry is a new layer between the engine output and the remediation loop.

### Core data structures

```python
@dataclass
class NodeSnapshot:
    """Immutable record of a node's state at a specific pipeline phase."""
    pass_number: int
    phase: str            # "original", "formatted", "scanned", "transformed"
    content: str          # YAML text at this point
    violations: list[ViolationDict]
    transforms_applied: list[str]  # rule_ids of transforms that changed this node

@dataclass
class TrackedNode:
    """A node with stable identity and progression history."""
    id: str               # stable YAML path: "site.yml::play[0]#task[3]"
    key: str              # ARI's node key (bridge to hierarchy_payload)
    kind: str             # "playcall", "taskcall", "rolecall", "blockcall"
    file: str             # relative file path
    line: int             # line number (from hierarchy_payload)
    parent_id: str | None
    children_ids: list[str]
    history: list[NodeSnapshot]

class NodeRegistry:
    """Stable identity and progression tracking for ARI hierarchy nodes."""

    _by_id: dict[str, TrackedNode]
    _by_key: dict[str, TrackedNode]          # ARI key → TrackedNode
    _by_file_line: dict[tuple[str, int], TrackedNode]

    @classmethod
    def from_hierarchy_payload(cls, payload: dict) -> NodeRegistry:
        """Build registry from ARI's hierarchy_payload output.

        Walks the hierarchy trees, assigns YAML-path IDs,
        records parent-child relationships.
        """
        ...

    def get(self, node_id: str) -> TrackedNode | None:
        """Look up node by stable ID."""
        ...

    def match_violation(self, violation: ViolationDict) -> TrackedNode | None:
        """Match a violation to its node.

        First tries violation['path'] (ARI key) via _by_key.
        Falls back to (file, line) via _by_file_line.
        """
        ...

    def inherited(self, node_id: str, key: str) -> tuple[Any, str | None]:
        """Walk parent chain for inherited property.

        Returns (value, origin_node_id) or (None, None).
        Used by rules that need PropertyOrigin
        (R108, M010, M022).
        """
        node = self._by_id.get(node_id)
        while node:
            # Look up property in hierarchy_payload node
            payload_node = self._get_payload_node(node.key)
            val = payload_node.get("options", {}).get(key)
            if val is not None:
                return val, node.id
            if node.parent_id:
                node = self._by_id.get(node.parent_id)
            else:
                break
        return None, None

    def snapshot(self, pass_number: int, phase: str,
                 file_contents: dict[str, str],
                 violations: list[ViolationDict]) -> None:
        """Record a snapshot of all nodes at a pipeline phase.

        Called at: original parse, post-format, each scan pass,
        each transform pass.
        """
        for v in violations:
            node = self.match_violation(v)
            if node:
                v["node_id"] = node.id  # enrich violation with stable ID

        for node in self._by_id.values():
            content = self._extract_node_content(node, file_contents)
            node_violations = [v for v in violations
                               if v.get("node_id") == node.id]
            node.history.append(NodeSnapshot(
                pass_number=pass_number,
                phase=phase,
                content=content,
                violations=node_violations,
                transforms_applied=[],
            ))

    def snippet_at(self, node_id: str, pass_number: int,
                   context_lines: int = 10) -> str | None:
        """Extract snippet from any historical state."""
        node = self._by_id.get(node_id)
        if not node:
            return None
        for snap in node.history:
            if snap.pass_number == pass_number:
                return snap.content
        return None

    def attribution(self, node_id: str) -> list[dict]:
        """Return progression timeline for a node.

        Example: [
          {"pass": 0, "phase": "original", "violations": []},
          {"pass": 1, "phase": "formatted", "violations": []},
          {"pass": 2, "phase": "scanned", "violations": [V1, V2]},
          {"pass": 3, "phase": "transformed", "violations": [V2],
           "transforms": ["L007"]},
        ]
        """
        ...
```

### Integration points

**Built after ARI parse (no ARI changes):**
```python
# In Primary's scan pipeline (primary_server.py)
context = run_scan(target_path, ...)  # existing ARI call
registry = NodeRegistry.from_hierarchy_payload(context.hierarchy_payload)
registry.snapshot(0, "original", file_contents, violations=[])
```

**Used in remediation loop (opt-in, no rule changes):**
```python
# In remediation engine (engine.py convergence loop)
for pass_num in range(max_passes):
    violations = scan()
    registry.snapshot(pass_num, "scanned", file_contents, violations)

    for v in fixable:
        transform_registry.apply(v.rule_id, ...)
    registry.snapshot(pass_num, "transformed", file_contents, violations)
```

**Enriches violations (transparent to validators):**
```python
# After merge/dedup in Primary
for v in violations:
    node = registry.match_violation(v)
    if node:
        v["node_id"] = node.id  # stable identity
        v["snippet_original"] = registry.snippet_at(node.id, 0)
```

**PropertyOrigin for opted-in rules (no interface change):**
```python
# R108 can optionally use registry (if available)
# Graph variant rules already exist (R108_graph, M010_graph, M022_graph)
# These can call registry.inherited() instead of requiring full ContentGraph
val, origin_id = registry.inherited(node_id, "become")
if val and origin_id == current_node_id:
    # This node DEFINES become, not just inherits it
    yield Violation("R108", node_id=origin_id, ...)
```

### NodeIdentity scheme

Same as ADR-044:
```
<file-path>::<yaml-path>

Examples:
  site.yml::play[0]#task[3]
  roles/web/tasks/main.yml::task[0]
  site.yml::play[1]#block[0]#task[2]
```

Derived from structural position in the hierarchy_payload, not from content. Assigned once at first parse, stable through formatting and transforms that don't restructure the document.

## Alternatives Considered

### Alternative 1: ADR-044 ContentGraph (networkx MultiDiGraph)

**Pros**: Full graph with algorithms. Unified model for all consumers. Variable provenance, Python AST analysis, complexity metrics.

**Cons**: Requires porting 96 rules to GraphRule. networkx dependency. 3-phase migration. Doesn't eliminate three representations. Bundles 7+ separate concerns into one ADR.

**Why not chosen**: Disproportionate effort for the stated problems. The highest-value outcomes (identity, progression, PropertyOrigin) don't require a graph library or rule porting.

### Alternative 2: Do nothing (status quo + NodeIndex)

**Pros**: No changes. NodeIndex works as a workaround.

**Cons**: Pain points persist. Violation matching breaks after transforms. No progression tracking. Inherited property mis-attribution generates noisy reports.

**Why not chosen**: The problems are real and growing. The NodeRegistry is small enough (~200 lines) to be low-risk.

## Consequences

### Positive

- Stable violation identity across passes (YAML-path IDs, not line numbers)
- Snippets from any pipeline phase (original, formatted, scanned, transformed)
- Remediation attribution: progression timeline per node
- PropertyOrigin for inherited properties (R108 fires once on play, not 50x on tasks)
- No rule changes required (registry enriches violations transparently)
- No ARI engine changes
- No networkx dependency
- No migration phases
- ~200 lines total, replacing ~100 lines (NodeIndex)

### Negative

- Does not solve "three representations" (separate concern, higher-effort refactor)
- Variable provenance not addressed (separate concern)
- Python AST analysis not addressed (separate concern)
- Parent-child relationships derived from hierarchy_payload structure, not from deep include resolution

### Neutral

- ARI engine unchanged
- All 100+ rules unchanged
- All transforms unchanged
- Validator gRPC contract unchanged (if retained) or Validator Protocol unchanged (per ADR-046)
- OPA Rego rules unchanged
- Gitleaks integration unchanged

## Supersedes

- ADR-044 (Node Identity and Progression Model) — same problem statement, simpler solution. The capabilities ADR-044 bundles beyond identity and progression (variable provenance, Python AST, complexity metrics, visualization, dependency scorecards) should be proposed as separate ADRs when needed.

## Related Decisions

- [ADR-044](ADR-044-node-identity-progression-model.md): ContentGraph — superseded by this simpler approach
- [ADR-003](ADR-003-vendor-ari-engine.md): ARI engine — unchanged, registry consumes ARI's output
- [ADR-009](ADR-009-remediation-engine.md): Remediation — convergence loop gains progression tracking
- [ADR-023](ADR-023-per-finding-classification.md): Per-finding classification — violations gain stable node_id
- [ADR-019](ADR-019-dependency-governance.md): Dependency governance — no new runtime dependencies

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-03-30 | Claude (proposal) | Initial proposal superseding ADR-044 |
