# Podman issues when running OPA

When running OPA via Podman (e.g. `opa eval` or `opa test` in the bundle), we hit three distinct issues. This document summarizes causes and fixes.

---

## 1. `mkdir /run/libpod: permission denied` (sandbox / rootless)

**What happened:** Running `podman run ...` from an environment where Podman is rootless and the runtime directory is restricted (e.g. Cursor/sandbox, or missing user session).

**Cause:**

- Rootless Podman uses `XDG_RUNTIME_DIR` (e.g. `/run/user/<uid>`) for temp/runtime files. If that isn't set or writable, some configs fall back to `/run/libpod`, which a normal user can't create.
- In a sandbox, the process may not have a proper session, so `/run/user/<uid>` may not exist or may be read-only.

**Fixes:**

- Run the command in a full login shell (e.g. `su -l $USER` or a real terminal), not a restricted/sandbox one.
- Ensure user linger so the runtime dir exists: `loginctl enable-linger $USER`.
- Don't override `tmp_dir` to `/run/libpod` in `containers.conf`; let rootless use the XDG path.
- For CI/automation: run Podman where a normal user session exists, or use a CI job that has the right permissions (e.g. `podman run` as the same user that owns `XDG_RUNTIME_DIR`).

**Reference:** [containers/podman#11526](https://github.com/containers/podman/issues/11526) (error creating tmpdir: mkdir /run/libpod: permission denied).

---

## 2. Short-name resolution enforced but cannot prompt without a TTY

**What happened:**  
`podman run ... openpolicyagent/opa:latest ...` failed with:  
`Error: short-name resolution enforced but cannot prompt without a TTY`.

**Cause:**

- Podman treats unqualified image names (e.g. `openpolicyagent/opa:latest`) as "short names" and may prompt to choose a registry when resolution is ambiguous.
- In non-interactive environments (IDE terminal, CI, scripts), there is no TTY, so the prompt fails.

**Fixes:**

- Use a **fully qualified image name** so no resolution prompt is needed:
  - `docker.io/openpolicyagent/opa:latest`
- We already use this in `opa_client.py` (`OPA_IMAGE = "docker.io/openpolicyagent/opa:latest"`). Any script or doc that runs `podman run` should use the full name.
- Alternatively, configure [unqualified-search registries](https://github.com/containers/podman/blob/main/docs/tutorials/mac_win_client.md#registriesconf) in `/etc/containers/registries.conf` so short names resolve without a prompt.

**Reference:** [containers/podman#12933](https://github.com/containers/podman/issues/12933), [suedbroecker.net](https://suedbroecker.net/2021/09/26/error-error-getting-default-registries-to-try-short-name-resolution-enforced-but-cannot-prompt-with-a-tty/).

---

## 3. `open /bundle: permission denied` (volume mount in rootless)

**What happened:**  
`podman run --rm -v "$(pwd):/bundle:ro" docker.io/openpolicyagent/opa:latest test /bundle -v` pulled the image but then failed with:  
`1 error occurred during loading: open /bundle: permission denied`.

**Cause:**

- The **OPA image runs as non-root** (e.g. `USER 1000:1000`). In rootless Podman, bind mounts often show up inside the container with ownership `nobody:nogroup` or with permissions that the container user (e.g. 1000) cannot read.
- So the process inside the container does not have read access to `/bundle` even though the host user can read the directory.

**Fixes:**

1. **Run container with host user (recommended for local dev):**  
   Use the same numeric user as the host so the container can read the mount:
   ```bash
   podman run --rm -v "$(pwd):/bundle:ro" --userns=keep-id -u root \
     docker.io/openpolicyagent/opa:latest test /bundle -v
   ```
   Using `-u root` inside the container with `--userns=keep-id` makes container root map to your host user, so it can read your bind-mounted directory. For `opa eval` we could add `--userns=keep-id` (and optionally `-u root`) in `opa_client.py` when invoking Podman.

2. **SELinux:**  
   If SELinux is enabled, try the `:z` or `:Z` suffix on the volume so the context allows the container to read the mount:
   ```bash
   -v "$(pwd):/bundle:ro,z"
   ```
   (`:z` = private label; `:Z` = exclusive; use `:z` for read-only shared content.)

3. **Ensure host directory is readable by "other":**  
   If the mount is only group-readable, the container's user (1000) may not be in that group. Making the bundle world-readable for execution (e.g. `chmod o+rx bundle`) can fix it but is less secure; prefer (1) or (2).

**Reference:** [Stack Overflow: Permission denied on volume bind in Podman](https://stackoverflow.com/questions/79158973/permission-denied-on-volume-bind-in-podman-container); [Red Hat: Podman volume mounts, rootless container](https://learn.redhat.com/t5/Containers-DevOps-OpenShift/Podman-volume-mounts-rootless-container-and-non-root-user-in/td-p/47579).

---

## Summary for this project

| Issue              | Where it appears              | Fix |
|--------------------|-------------------------------|-----|
| `/run/libpod`      | Sandbox / no user session     | Run Podman in a real login/shell or CI with proper session; avoid overriding `tmp_dir`. |
| Short-name / TTY   | Scripts, IDE, CI              | Use `docker.io/openpolicyagent/opa:latest` (already in code). |
| `/bundle` permission | Rootless + non-root OPA image | Add `--userns=keep-id` and optionally `-u root` to `podman run`, and/or use `:z` on the volume. |

---

## Optional: `opa_client.py` change for volume access

For `run_opa()` we only do `opa eval` with a single read of the bundle; that may work in environments where the mount is readable. If we add support for running `opa test` (e.g. for Rego unit tests), or if `opa eval` starts failing with "permission denied" on the bundle, the Podman invocation should include:

- Image: `docker.io/openpolicyagent/opa:latest` (already used).
- Volume: `-v "${bundle_abs}:/bundle:ro,z"` (add `:z` if SELinux is on).
- User mapping: `--userns=keep-id` and `-u root` so the container can read the bind-mounted bundle.

These can be applied in `_run_opa_podman()` or in a future helper that runs `opa test` via Podman.
