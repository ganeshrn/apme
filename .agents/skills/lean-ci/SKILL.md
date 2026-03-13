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

4. **Minimal setup actions.** Only `actions/checkout` and `astral-sh/setup-uv`.
   No `actions/setup-python` (uv handles it). No other setup actions without
   explicit justification.

5. **Pin actions to commit SHAs.** Mutable tags (`@v4`) allow upstream changes
   to affect CI without review. Pin to the commit SHA with the tag in a comment
   (ADR-015):

   ```yaml
   - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6
   ```

## Existing locally-runnable commands

| Command | What it does | CI workflow |
|---------|-------------|-------------|
| `prek run --all-files` | Lint (ruff), format (ruff-format), type check (mypy) | `prek.yml` |
| `uv run pytest --cov --cov-report=term-missing` | Run tests with coverage enforcement | `test.yml` |
| `uv sync --extra dev` | Install all runtime + dev dependencies | Both |

## Workflow structure

CI has two workflows (separation of concerns):

- **`prek.yml`**: Runs prek hooks (ruff lint, ruff format, mypy strict). Uses
  `j178/prek-action` which handles installation and caching.
- **`test.yml`**: Installs deps via `uv sync --extra dev`, runs pytest with
  coverage. Coverage threshold is in `pyproject.toml` (`fail_under = 95`).

Both workflows trigger on `pull_request` targeting `main` and use `concurrency`
groups with `cancel-in-progress` to avoid stacking runs on rapid pushes.

## Rules for modifications

When adding or modifying CI:

- **DO** add new build logic as a script in `scripts/`, then call it from the
  workflow with a single `run:` line.
- **DO** use SHA-pinned actions with the tag noted in a comment.
- **DO** set `FORCE_COLOR: 1` and `PY_COLORS: 1` for readable CI output.
- **DO NOT** put multi-line shell scripts in `run:` blocks. If it needs more
  than one command, it belongs in a script. The git dirty check is the one
  exception -- it is a CI-only guard with no local equivalent.
- **DO NOT** add setup actions beyond `actions/checkout` and
  `astral-sh/setup-uv`.
- **DO NOT** hardcode tool or Python versions in YAML.
- **DO NOT** add secrets or publishing steps without explicit approval.

## Example: adding a new CI step

Wrong (logic in YAML):

```yaml
- name: Generate docs
  run: |
    uv run pip install sphinx
    uv run sphinx-build -b html docs/ docs/_build/
    tar czf docs.tar.gz docs/_build/
```

Right (logic in a script):

```bash
# scripts/build_docs.sh
uv run sphinx-build -b html docs/ docs/_build/
```

```yaml
- name: Generate docs
  run: ./scripts/build_docs.sh
```
