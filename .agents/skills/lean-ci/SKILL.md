---
name: lean-ci
description: >
  Guide for writing and modifying GitHub Actions workflows in this repository.
  Use when creating CI/CD pipelines, adding workflow jobs, modifying build steps,
  or debugging CI failures. Enforces the project's lean CI philosophy.
---

# Lean CI

This project follows a strict "CI as thin wrapper" philosophy. GitHub Actions
workflows must never contain substantive build logic. All logic lives in
locally-runnable commands; CI just calls them.

## Principles

1. **Every CI step must be reproducible locally.** A developer should be able to
   run the exact same command on their laptop. If a step only works inside
   GitHub Actions, it violates this rule.

2. **Workflows call single commands, not inline shell.** Build and test logic
   belongs in `prek`, `uv run pytest`, or a script in `scripts/` -- never in
   multi-line YAML `run:` blocks.

3. **No scattered version pinning.** Python version is in `pyproject.toml`
   (`requires-python`). Tool versions are managed in `.pre-commit-config.yaml`
   (ruff, mypy) and `pyproject.toml` (deps). Not in workflow YAML.

4. **Minimal setup actions.** `astral-sh/setup-uv` and `actions/checkout` only.
   No `actions/setup-python` (uv handles it). No other setup actions without
   explicit justification.

5. **Pin actions to commit SHAs.** Mutable tags (`@v4`) allow upstream changes
   to affect CI without review. Always pin to a full commit SHA with a comment
   noting the tag (ADR-015).

## Existing locally-runnable commands

| Command | What it does | CI job |
|---------|-------------|--------|
| `prek run --all-files` | Lint, format, type check (ruff + mypy) | `prek` workflow |
| `uv run pytest --cov=src/apme_engine --cov-report=term-missing --cov-fail-under=36` | Test with coverage enforcement | `test` workflow |
| `uv sync --extra dev` | Install runtime + dev dependencies | Setup step |

## Workflow structure

CI has two workflows in `.github/workflows/`:

- **prek.yml**: Runs `prek` (ruff lint, ruff format, mypy strict). Quality gate
  for code style and type safety.
- **test.yml**: Runs `pytest` with coverage. Quality gate for correctness.
  Coverage threshold is enforced via `--cov-fail-under` (also configured
  in `pyproject.toml` under `[tool.coverage.report]`). Ratchet up as
  tests are added; never lower without justification.

Both trigger on `pull_request` targeting `main` and use `concurrency` groups
with `cancel-in-progress` to avoid stacking runs on rapid pushes.

## Rules for modifications

When adding or modifying CI:

- **DO** add new build logic as a script in `scripts/`, then call it from the
  workflow with a single `run:` line.
- **DO** use SHA-pinned actions with a tag comment (e.g.,
  `actions/checkout@de0fac2e...  # v6`).
- **DO** set `FORCE_COLOR: 1` and `PY_COLORS: 1` as workflow-level env vars
  for readable CI logs.
- **DO** use `ubuntu-24.04` explicitly rather than `ubuntu-latest`.
- **DO NOT** put multi-line shell scripts in `run:` blocks. If it needs more
  than one command, it belongs in a script. The git dirty check is the one
  exception -- it is a CI-only guard with no local equivalent.
- **DO NOT** add `actions/setup-python` or other setup actions. `setup-uv`
  handles the Python toolchain.
- **DO NOT** hardcode tool versions in YAML. Versions belong in
  `.pre-commit-config.yaml` or `pyproject.toml`.
- **DO NOT** add secrets or publishing steps without explicit approval.
