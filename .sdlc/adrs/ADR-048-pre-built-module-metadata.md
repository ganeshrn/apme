# ADR-048: Pre-Built Module Metadata (Lite Mode)

## Status

Proposed

## Date

2026-03-30

## Context

APME's Ansible validator (M001-M004) detects module FQCN resolution, deprecation, redirects, and removals by running actual ansible-core plugin introspection inside session-scoped virtual environments (ADR-022). This requires:

1. **VenvSessionManager** to create/manage per-session, per-ansible-core-version venvs
2. **Galaxy Proxy** (ADR-031) to convert Galaxy tarballs to pip wheels (PEP 503/427)
3. **Collection installation** via `uv pip install` into the venv
4. **`find_plugin_with_context()`** calls against the installed ansible-core

Per DEPLOYMENT.md, cold start (first scan with a new session) involves creating a venv and installing ansible-core + collections. This takes 30-60 seconds before the first rule runs. Per DESIGN_VALIDATORS.md, only 4 rules (M001-M004) and 3 rules (L057-L059) require this infrastructure.

### Where this hurts

1. **CI/CD pipelines**: A 30-60 second cold start for venv creation is unacceptable for PR gate checks. CI jobs should start scanning in <2 seconds.

2. **Batch scanning (3000 collections)**: Each worker creating its own venv multiplies the cold-start penalty. 100 workers × 30s = 50 minutes wasted on venv creation.

3. **90% of scans don't need custom collection modules**: Most M001-M004 violations involve `ansible.builtin.*` modules (shipped with ansible-core) and well-known collections (`community.general`, `ansible.posix`, `ansible.netcommon`). The argspec data for these is static per ansible-core version.

### Content delivery: portal as the content broker

The portal catalogs Ansible collections from multiple sources — Git repositories (GitHub/GitLab via `AnsibleGitContentsProvider`) and Automation Hub (`PAHCollectionProvider`). The portal already authenticates to these sources and maintains entity metadata including SCM coordinates, refs, and collection namespaces.

For APME scanning, the portal — not APME — is the natural content broker:

- **From Git**: The portal knows the SCM provider, organization, repository, ref, and `galaxy.yml` path (stored as `ansible.io/scm-*` annotations on catalog entities). The portal can construct archive download URLs (`https://github.com/{owner}/{repo}/archive/{ref}.tar.gz`) or clone repos directly. APME does not need independent SCM access.
- **From Automation Hub (PAH)**: The portal queries PAH's `/api/galaxy/v3/` API for collection metadata and has authenticated access. PAH serves collection tarballs that the portal can proxy to APME.
- **Air-gapped (bootc)**: In disconnected environments, the portal still has access to whatever content sources the operator configured (internal GitLab, on-prem Automation Hub). The portal downloads collection content from those sources and passes it to APME. APME itself does not need network access to content sources — the portal mediates.

This means APME's scan API should accept **content directly** (uploaded files or a local path), not just a `repo_url` for APME to clone. The portal fetches the content and passes it to APME:

```
Portal discovers collection in catalog
  → Portal downloads content from SCM or PAH (portal has auth)
  → Portal sends content to APME via POST /api/v1/check (multipart upload)
     or writes to shared workspace and calls APME with path
  → APME scans content, returns violations
  → Portal stores results and displays in UI
```

This is cleaner than APME independently cloning repos because:
- APME does not need SCM tokens or PAH credentials (separation of secrets)
- The portal already has authenticated access to all content sources
- Air-gapped environments work without APME needing network access
- Content is fetched once by the portal, not duplicated by each APME worker

### Precedent in RESEARCH_REVIEW.md

RESEARCH_REVIEW.md identifies `module_metadata.json` as valuable future work: *"machine-readable module lifecycle data (introduced, deprecated, removed, parameter renames) generated from `ansible-doc` across core versions."* This ADR implements that vision.

### What the migration rules actually need

Per the comprehensive rule analysis:

- **M005-M030** (10 rules): 100% static text/regex/syntax analysis. Zero ansible-core dependency. These rules work today without venvs.
- **M001-M004** (4 rules): Need module metadata (FQCN mapping, deprecated flag, redirect target, removed flag). This data CAN come from pre-built files instead of runtime introspection — for ansible.builtin and well-known collections.
- **L057** (syntax check): Needs `ansible-playbook --syntax-check`. Genuinely requires ansible-core.
- **L058-L059** (argspec validation): Need module argument specs. Require ansible-core for custom modules, but can use pre-built data for known modules.

## Decision

**Ship pre-built module metadata as versioned JSON data files, bundled in the package and container image.** M001-M004 use data files by default (lite mode). Full ansible-core introspection is available via `--with-ansible-runtime` flag.

### Data files

```
data/ansible-core/
  2.16/
    modules.json        # {module_fqcn: {short_name, deprecated, removed, redirect_to, ...}}
    redirects.json      # {old_fqcn: new_fqcn}
    removed.json        # [removed_fqcn, ...]
  2.17/
    modules.json
    redirects.json
    removed.json
  2.18/
    ...
  2.19/
    ...
```

Generated by extending the existing `scripts/scrape_ansible_deprecations.py` to output full module metadata per ansible-core version. Data files are ~2-5MB per version, covering `ansible.builtin.*` plus the 20 most common collections.

### Two modes

| Mode | Flag | M001-M004 source | L057-L059 | Cold start | Requires |
|------|------|---|---|---|---|
| **Lite** (default) | (none) | Pre-built data files | Skipped | <2s | Data files only |
| **Full** | `--with-ansible-runtime` | ansible-core plugin loader | Enabled | 30-60s | ansible-core installed or venv |

### Lite mode behavior

```python
# M001: FQCN resolution
module_data = load_module_data(target_version)
short_name = task.module  # e.g., "shell"
if short_name in module_data.short_to_fqcn:
    fqcn = module_data.short_to_fqcn[short_name]
    yield Violation("M001", f"Use FQCN: {fqcn}", metadata={"resolved_fqcn": fqcn})

# M002: Deprecated module
if task.module in module_data.deprecated:
    yield Violation("M002", f"Module {task.module} is deprecated")

# M003: Redirected module
if task.module in module_data.redirects:
    yield Violation("M003", f"Module redirected to {module_data.redirects[task.module]}")

# M004: Removed module
if task.module in module_data.removed:
    yield Violation("M004", f"Module {task.module} has been removed")
```

### Full mode behavior

Unchanged from today: VenvSessionManager creates venv, installs ansible-core + collections, runs `find_plugin_with_context()`. This is the authoritative source for custom collection modules not in the data files.

### Unknown modules in lite mode

If a module is not found in the data files (custom collection module), lite mode:
- Does NOT flag M001-M004 violations (no false positives from missing data)
- Emits an INFO-level note: "Module X not in pre-built data; use --with-ansible-runtime for full validation"

## Alternatives Considered

### Alternative 1: Always require venvs (status quo)

**Pros**: Authoritative, covers all modules including custom collections.

**Cons**: 30-60s cold start. Galaxy Proxy required. Air-gap complexity. Disproportionate for CI/CD and batch scanning where 90% of checks are against well-known modules.

**Why not chosen**: The majority of scans don't need runtime introspection.

### Alternative 2: Cache ansible-doc output per session

**Pros**: Authoritative data, cached after first run.

**Cons**: Still requires first-run cold start. Still requires venv infrastructure. Cache invalidation complexity.

**Why not chosen**: Moves the cost but doesn't eliminate it.

## Consequences

### Positive

- CI/CD cold start: <2s (no venv creation)
- Batch scanning: workers start immediately, no per-worker venv creation overhead
- Galaxy Proxy only needed in full mode (not for lite or CI/CD)
- Data files are versioned and deterministic (same input → same output)
- Portal-mediated content delivery: APME receives content from the portal, which already has authenticated access to SCMs and Automation Hub. APME does not need its own content source credentials.

### Negative

- Data files must be regenerated when new ansible-core versions release
- Custom collection modules not covered in lite mode
- Two code paths (lite data lookup vs full plugin introspection) for M001-M004

### Neutral

- Full mode behavior unchanged (venvs, Galaxy Proxy, plugin loader)
- M005-M030 unchanged (already static)
- L-rules unchanged
- R-rules unchanged
- SEC-rules unchanged

## Supplements (Does Not Replace)

- ADR-022 (session-scoped venvs) — venvs still used in full mode
- ADR-031 (unified Galaxy proxy) — Galaxy Proxy still used in full mode

## Related Decisions

- [ADR-022](ADR-022-session-scoped-venvs.md): Session venvs — retained for full mode
- [ADR-031](ADR-031-unified-collection-cache.md): Galaxy Proxy — retained for full mode
- [ADR-046](ADR-046-single-process-core.md): Single-process core — lite mode enables <2s cold start
- [ADR-047](ADR-047-deployment-modes.md): Deployment modes — CI/CD and workers default to lite mode

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2026-03-30 | Claude (proposal) | Initial proposal |
| 2026-03-30 | Claude (proposal) | Corrected air-gap assumption: portal is the content broker (downloads from SCM/PAH), passes content to APME. Added content delivery model section. Removed incorrect claim about Galaxy Proxy being needed for air-gap. |
