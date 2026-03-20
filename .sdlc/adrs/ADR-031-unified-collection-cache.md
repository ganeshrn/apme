# ADR-031: Unified Collection Cache as Single Authoritative Source

## Status

Proposed

## Date

2026-03-19

## Context

Today APME has **three independent systems** that download, store, and resolve Ansible collection/role content — each unaware of the others:

### 1. ARI engine dependency preparator (scanner path)

When `ARIScanner.evaluate()` encounters a dependency (e.g. `community.general`), `dependency_dir_preparator.py` calls `ansible-galaxy collection install` to download the tarball, extracts it into `{root_dir}/collections/src/ansible_collections/ns/coll/`, scans it, and writes findings + index JSON to `{root_dir}/{type}s/findings/`. In the daemon path, `root_dir` is a temp directory that is `shutil.rmtree()`'d after each request — so every scan re-downloads, re-extracts, and re-parses the same collections from scratch.

### 2. CacheMaintainer service (collection cache)

The CacheMaintainer gRPC service (:50052) downloads collections via `ansible-galaxy collection install` into a **persistent** cache at `~/.apme-data/collection-cache/galaxy/`. It also clones GitHub org repos into `collection-cache/github/`. This cache survives across scans and is managed via `PullGalaxy` / `PullRequirements` / `CloneOrg` RPCs.

### 3. Ansible validator venv builder

The Ansible validator builds per-session venvs with `ansible-core` installed, then **symlinks** collections from the CacheMaintainer's persistent cache into `site-packages/ansible_collections/`. This means the venv already has the full collection source tree available on `PYTHONPATH` — modules, roles, plugins, meta, docs — everything.

### The problem

- **Double download**: The same collection tarball is downloaded twice per scan — once by the scanner's dependency preparator into a throwaway temp dir, and once by CacheMaintainer into the persistent cache.
- **Triple storage**: Collection source may exist in three places simultaneously — scanner temp dir, persistent cache, and venv symlinks.
- **Wasted parse**: The scanner parses collection content to build `Findings` objects (module definitions, role specs, taskfile structures) that are immediately discarded when the temp dir is cleaned up. On the next scan of the same content, all that work is repeated.
- **RAMClient is a vestigial knowledge base**: `RAMClient` (`risk_assessment_model.py`) was designed for ARI's persistent local registry model. APME's daemon architecture made it ephemeral — the filesystem-backed "database" is written into a temp dir and destroyed after each request. Its management API (`list`, `search`, `diff`, `release`) is dead code.
- **The Ansible validator venv already has everything**: The venv built by `venv_builder.py` has `ansible-core` on the path and collections symlinked in. It can resolve FQCNs, load `argument_specs`, inspect `meta/runtime.yml` routing, and access `action_groups` — all things the native validator currently gets from RAMClient's parsed `Findings`.

### Forces

- The scanner's dependency resolution (tree building) is the critical path — it needs module/role/taskfile definitions to resolve `import_role`, `include_tasks`, FQCN lookups, and action groups.
- The native validator's P-rules (P001–P004, currently excluded from native runs in daemon mode) need `argument_specs` and `action_groups` that come from RAMClient today.
- Performance: the scanner currently re-scans every dependency on every request because the parsed data isn't cached persistently.
- The web gateway (ADR-029) will add a persistence layer (SQLite V1) — a fourth potential store for scan-derived data.

## Decision

**We will establish the CacheMaintainer's persistent collection cache as the single authoritative source for Ansible content, and provide a metadata layer on top that all validators can query.**

Concretely:

1. **Single download, single store**: Collections are downloaded once by CacheMaintainer into the persistent cache. The scanner reads collection source from the cache instead of downloading its own copy.

2. **Persistent parsed metadata**: A new metadata cache (initially filesystem-backed JSON alongside the collection source, later migrated to the web gateway's SQLite) stores parsed `Findings`-equivalent data — module definitions, role specs, taskfile structures, action groups — so the scanner doesn't re-parse unchanged collections.

3. **Validator-accessible collection path**: The Ansible validator's venv setup already symlinks from this cache. The native validator and scanner will also read from it, either directly or via a shared resolution API.

4. **RAMClient evolves into a read-through cache**: `RAMClient` becomes a read-through client over the persistent metadata layer rather than owning its own filesystem store. Its `search_module()` / `search_role()` / `search_action_group()` interface is preserved, but the backing store changes from per-scan temp dirs to the shared persistent cache.

5. **Venv as a resolution oracle**: For P-rules that need `argument_specs` or FQCN resolution, the native validator can query the Ansible validator's venv (via subprocess or a thin gRPC call) rather than maintaining a parallel parsed copy. The venv has `ansible-core` which can authoritatively resolve module arguments via `ansible-doc`.

## Alternatives Considered

### Alternative 1: Keep the status quo

**Description**: Leave the three systems independent. The scanner downloads and parses its own copies; CacheMaintainer maintains the persistent cache; the Ansible validator builds venvs from the cache.

**Pros**:
- No cross-system coupling
- Each system is self-contained

**Cons**:
- Double download on every scan
- Wasted CPU re-parsing unchanged collections
- RAMClient's persistence model is incoherent (writes to temp dirs)
- Will become a quadruple-store problem when web gateway persistence lands

**Why not chosen**: The waste is measurable and grows with collection count. The incoherent persistence model creates confusion for contributors.

### Alternative 2: Make the scanner use the venv directly

**Description**: Instead of maintaining a separate metadata cache, have the scanner shell out to the Ansible validator's venv for all collection resolution (module lookup, role specs, etc.).

**Pros**:
- Single source of truth (the venv)
- `ansible-doc` is the authoritative resolver

**Cons**:
- Subprocess overhead per lookup would be prohibitive during tree building (hundreds of lookups per scan)
- Tight coupling between scanner and Ansible validator lifecycle
- Venv may not exist if Ansible validator is not enabled

**Why not chosen**: Performance characteristics are wrong for the scanner's hot loop. Better suited as a targeted optimization for P-rules (small number of lookups).

### Alternative 3: Merge all caching into the web gateway's SQLite

**Description**: Skip the filesystem metadata layer entirely and persist parsed collection data in the web gateway's database from the start.

**Pros**:
- Single store for everything
- Query-friendly

**Cons**:
- Web gateway doesn't exist yet
- Creates a hard dependency between the engine and the gateway
- Doesn't help the standalone CLI / daemon-without-gateway use case

**Why not chosen**: Premature — the web gateway is not built yet. The filesystem metadata layer can be migrated later.

## Consequences

### Positive

- Each collection is downloaded once and cached persistently
- Parsed metadata survives across scans — subsequent scans of unchanged content skip re-parsing
- Contributors see one clear system instead of three overlapping ones
- `dependency_dir_preparator.py` simplifies significantly (reads from cache instead of managing downloads)
- Foundation for web gateway persistence migration
- P-rules could use the venv's `ansible-doc` for authoritative argument spec resolution

### Negative

- Cross-system dependency: scanner now depends on CacheMaintainer having run
- Cache invalidation complexity: must detect when a collection version changes
- Migration effort: `RAMClient`, `dependency_dir_preparator`, and scanner wiring all need refactoring

### Neutral

- The Ansible validator's venv model is unaffected — it already reads from the cache
- OPA validator is unaffected — it consumes the hierarchy payload, not collection source
- The dead RAMClient management API (`list`, `search`, `diff`, `release`) should be removed regardless (cleanup, not architecture)

## Implementation Notes

### Phase 1: Dead code removal — COMPLETE (PR #49)
- Removed dead `engine/cli/` (ARICLI/RAMCLI), `ram_generator.py`, `key_test.py`, backup/sample annotators, empty `engine/rules/`
- Pruned dead RAMClient public methods (`list_all_ram_metadata`, `diff`, `release`); privatized internal search methods
- Removed orphan `main()` functions and `__main__` blocks from 6 live modules
- Removed dead utility functions (`diff_files_data`, `show_all_ram_metadata`, `show_diffs`, `version_to_num`)
- **~3,100 lines removed** across 25 files (14 deleted, 11 trimmed)

### Phase 2: Scanner reads from persistent cache
- Modify `dependency_dir_preparator.py` to resolve collections from `collection_cache` instead of downloading
- CacheMaintainer becomes a prerequisite: `primary_server` calls `PullGalaxy` before scan if collection not cached
- RAMClient's `root_dir` changes from temp dir to persistent cache location
- Parsed Findings are written to `{cache_root}/metadata/{ns.coll}/{version}/` alongside the source

### Phase 3: Native validator leverages venv for P-rules
- For `search_action_group()` and argument spec validation, query the venv's `ansible-doc` (batch mode) instead of maintaining parallel parsed data
- Re-enable P001–P004 in daemon mode (currently excluded because they require `ram_client` with populated data)

### Phase 4: Web gateway migration (future, ADR-029)
- Migrate the filesystem metadata layer to SQLite/PostgreSQL
- RAMClient becomes a DB-backed read-through cache

## Related Decisions

- [ADR-003](ADR-003-vendor-ari-engine.md): Vendor ARI Engine — established the engine as integrated code
- [ADR-009](ADR-009-remediation-engine.md): Separate Remediation Engine — validators are read-only
- [ADR-022](ADR-022-session-scoped-venvs.md): Session-Scoped Venvs — venv lifecycle
- [ADR-029](ADR-029-web-gateway-architecture.md): Web Gateway Architecture — future persistence layer

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-03-19 | AI-assisted | Initial proposal |
| 2026-03-19 | AI-assisted | Phase 1 complete (PR #49): ~3,100 lines of dead ARI code removed |
