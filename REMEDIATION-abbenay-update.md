# APME: Abbenay Integration Remediation

Abbenay `v2026.3.7-alpha` has been released with container support, GHCR
images, gRPC TCP listener changes, and a new CI/CD pipeline. This
document lists the items in APME that need updating.

---

## 1. ~~Update `abbenay-client` version pin~~ (done)

**File:** `pyproject.toml` (line 26)

~~The `[ai]` extra pins a specific git commit from March 19 (`5167424`).
This is now 4 commits behind `main` and does not include the GHCR
workflow or the `undici` security fix.~~ Updated to the release tag:

```toml
# Current (stale git commit)
ai = [
    "abbenay-client @ git+https://github.com/redhat-developer/abbenay.git@516742428c5b074ce7d098cfcf4f69413658f5f6#subdirectory=packages/python",
]

# Option A: pin to release tag
ai = [
    "abbenay-client @ git+https://github.com/redhat-developer/abbenay.git@v2026.3.7-alpha#subdirectory=packages/python",
]

# Option B: install from release wheel (when published to PyPI)
ai = [
    "abbenay-client>=2026.3.6a0",
]
```

After updating, regenerate the lockfile: `uv lock`

---

## 2. Update README container section

**File:** `README.md` (lines 138-152)

The README tells users to build the Abbenay container from source. GHCR
images are now published automatically. Update:

```markdown
### Container daemon

See the [Abbenay container documentation](https://github.com/redhat-developer/abbenay/blob/main/docs/CONTAINER.md)
for full container setup instructions.

<!-- Replace the build-from-source example -->
podman pull ghcr.io/redhat-developer/abbenay:latest

podman run -d --name abbenay \
  -v ./config.yaml:/home/abbenay/.config/abbenay/config.yaml:ro \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  -p 8787:8787 -p 50051:50051 \
  ghcr.io/redhat-developer/abbenay:latest

# Point APME at the container via gRPC TCP
apme-scan fix --ai --abbenay-addr localhost:50051 --apply .
```

Also note: the pre-built image is multi-arch (amd64 + arm64), so it
works on both x86_64 and Apple Silicon / Graviton hosts.

---

## 3. Update `DESIGN_AI_ESCALATION.md`

**File:** `docs/DESIGN_AI_ESCALATION.md`

Several items are out of date:

- **Version reference**: The health-check example shows `v2026.3.3`.
  Update to `v2026.3.7-alpha` or just say "current version".

- **Optional dependency example**: Shows `abbenay-client>=2026.3.3a0`
  as a hypothetical PyPI pin. Update to match whatever is chosen in
  item 1 above.

- **Package name drift**: Some prose refers to `abbenay_client`
  (underscored) which was the old package name. The actual import is
  `abbenay_grpc` and the pip package is `abbenay-client`. Verify all
  references are consistent.

- **Environment variable name**: The design doc mentions
  `ABBENAY_TOKEN` in some places, but the CLI implementation uses
  `APME_ABBENAY_TOKEN`. Align the doc with the implementation.

- **Container instructions**: The doc likely still references manual
  builds. Add a note about GHCR pre-built images.

---

## 4. Update ADR references

**Files:**
- `.sdlc/adrs/ADR-025-ai-provider-protocol.md` — refers to
  `abbenay_client` (old package name); should reference `abbenay_grpc`
- `.sdlc/adrs/ADR-027-agentic-project-remediation.md` — mentions
  future MCP integration; verify still accurate with DR-025 (dynamic
  MCP registration) now merged in Abbenay

---

## 5. Consider CI coverage for `[ai]` extra

**File:** `.github/workflows/test.yml`

The test workflow installs `uv sync --extra dev` but not `--extra ai`.
This means the `abbenay-client` dependency and `AbbenayProvider` code
are never exercised in CI. Consider:

- Adding a job (or matrix entry) that also installs `--extra ai` and
  runs at least the `test_ai_escalation.py` tests with mocked client
- This would catch import breakage if the Abbenay client API changes

---

## 6. Container image tag scheme

Abbenay GHCR images use tags **without** a `v` prefix:

| Tag | Meaning |
|-----|---------|
| `:main` | Latest merged code |
| `:sha-<short>` | Specific commit |
| `:2026.3.7-alpha` | Release (no `v` prefix) |
| `:latest` | Latest stable release |

If APME docs or scripts reference container tags, use this scheme.

---

## 7. `--grpc-host` default change

The Abbenay daemon's `--grpc-port` option now defaults `--grpc-host` to
`127.0.0.1` (localhost only) for security. The container's `CMD`
explicitly sets `--grpc-host 0.0.0.0` so published ports work. This
should not affect APME, but note:

- Bare-metal daemon: gRPC TCP is localhost-only unless
  `--grpc-host 0.0.0.0` is passed
- Container daemon: accessible on all interfaces (container default)

If APME docs describe connecting to a bare-metal daemon over TCP from
another host, mention `--grpc-host`.

---

## Summary checklist

- [x] Update `pyproject.toml` `[ai]` pin to `v2026.3.7-alpha` tag (or later)
- [ ] Run `uv lock` to regenerate lockfile
- [ ] Update README container section to use GHCR pull
- [x] Update `DESIGN_AI_ESCALATION.md` version refs and package names (already uses `abbenay_grpc`, `APME_ABBENAY_TOKEN`, and `v2026.3.7-alpha`)
- [x] Update ADR-025 package name references (already uses `abbenay_grpc`)
- [ ] Review ADR-027 against current Abbenay MCP capabilities
- [x] Consider adding `[ai]` extra to CI test matrix (`test-ai-extra` job in `.github/workflows/test.yml`)
- [ ] Verify container tag scheme in any scripts/docs
