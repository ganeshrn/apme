# Example Playbooks

These playbooks are **intentionally non-conformant**. They exist to
demonstrate and test APME's scanner, auto-fix, and remediation capabilities.

**Do not "fix" these files** — the lint violations, bad practices, and fake
secrets are by design. **Do not run these playbooks** with
`ansible-playbook` — several contain tasks that modify system state
(package installs, file writes, user creation).

## Files

| File | Rules demonstrated |
|------|--------------------|
| `bad_practices.yml` | L002–L015, L024 — FQCN, ignore\_errors, state=latest |
| `risky_permissions.yml` | L018–L022, L031 — file modes, become, shell pipes |
| `style_violations.yml` | L025, L041–L050 — naming, key order, free-form |
| `complex_playbook.yml` | L003, L016–L017, L023, L042 — complexity, prompts |
| `module_issues.yml` | L026, L030, L037 — non-FQCN, non-builtin, unresolved |
| `secrets_example.yml` | SEC rules — AWS keys, GitHub PAT, private keys |
| `roles/broken_role/` | L027–L039 — missing metadata, undefined vars |
| `minimal_playbook.yml` | Minimal baseline with a few issues |

## Usage

```bash
# Scan all examples
apme-scan scan examples/

# Auto-fix what can be fixed (on a copy!)
cp -r examples/ /tmp/examples-copy
apme-scan fix /tmp/examples-copy/ --apply
```
