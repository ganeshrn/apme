# APME Agent Skills

Agent skills for development workflow and spec-driven development.

## Available Skills

### Development Workflow

| Skill | Purpose | Arguments |
|-------|---------|-----------|
| `submit-pr` | Prepare and submit a pull request | — |
| `pr-review` | Handle PR review feedback | — |

### Spec-Driven Development (SDLC)

| Skill | Purpose | Arguments |
|-------|---------|-----------|
| `sdlc-status` | Show project status and blockers | `[phase or req]` |
| `workflow` | Get workflow guidance | `[next\|blockers\|start\|resume]` |
| `prd-import` | Import PRD, create artifacts | `[path or URL]` |
| `phase-new` | Create delivery phase | `[Phase Name]` |
| `req-new` | Create requirement spec | `[Feature] [--phase X]` |
| `task-new` | Create implementation tasks | `[REQ-NNN] [Task Name]` |
| `dr-new` | Create Decision Request | `[Question] [--priority X]` |
| `dr-review` | Resolve Decision Request | `[DR-NNN] [--quick]` |
| `adr-new` | Create Architecture Decision Record | `[Title] [--from-dr X]` |

## Skill Structure

```
skills/
├── README.md               ← You are here
├── resources/              # Shared resources
│   └── status-values.md
├── submit-pr/
│   └── SKILL.md
├── pr-review/
│   └── SKILL.md
├── sdlc-status/
│   ├── SKILL.md
│   └── references/
├── workflow/
│   ├── SKILL.md
│   └── references/
├── prd-import/
│   └── SKILL.md
├── phase-new/
│   └── SKILL.md
├── req-new/
│   ├── SKILL.md
│   └── references/
├── task-new/
│   ├── SKILL.md
│   └── references/
├── dr-new/
│   ├── SKILL.md
│   └── references/
├── dr-review/
│   ├── SKILL.md
│   └── references/
└── adr-new/
    ├── SKILL.md
    └── references/
```

## SKILL.md Format

Each skill has YAML frontmatter:

```yaml
---
name: skill-name
description: >-
  What the skill does. When to use it. Trigger phrases.
  When NOT to use it.
argument-hint: "[expected arguments]"
user-invocable: true
metadata:
  author: APME Team
  version: 1.0.0
---
```

## Agent Invocation Policy

SDLC skills may be invoked by the agent proactively during development
when the context warrants it (e.g., creating an ADR after an architectural
decision is made). The agent informs the user when it creates an artifact.
See ADR-017 for rationale.

## Version

- **Version**: 1.0.0
- **Author**: APME Team
- **License**: Apache 2.0
