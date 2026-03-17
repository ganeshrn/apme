# ADR-021: Proactive PR Feedback via GitHub Actions

## Status

Accepted

## Date

2026-03-17

## Context

APME requires all CI checks to pass, all review conversations to be resolved, and the branch to be up-to-date with `main` before a PR can merge. Contributors often don't realize their PR has drifted into a failing state — checks break after a push to main introduces a conflict, or a review comment goes unaddressed. Maintainers end up manually pinging contributors to fix their PRs, which doesn't scale.

We need an automated system that gives contributors clear, actionable feedback when their PR needs attention, so they can self-service fixes without maintainer intervention.

## Decision

**We will implement a GitHub Actions workflow that labels open PRs and posts `@mention` comments when a PR has failing checks or merge conflicts with `main`.**

The workflow will:
1. Add descriptive labels (`checks-failing`, `needs-rebase`) when conditions are detected
2. Post a comment `@mentioning` the PR author with specific guidance on what to fix
3. Automatically remove labels and post an "all clear" comment when the condition resolves

Labels and comments are informational — merge protection continues to be enforced by branch protection rules (required checks, up-to-date branch, resolved conversations).

## Alternatives Considered

### Alternative 1: Convert PRs to Draft

**Description**: Use the `convertPullRequestToDraft` GraphQL mutation to move failing PRs back to draft state automatically.

**Pros**:
- Clear visual signal in the PR list (grey "Draft" badge)
- Prevents accidental review of broken PRs
- Common pattern in some large projects

**Cons**:
- Author must manually click "Ready for review" to recover — friction for external contributors
- Can be confusing for contributors who don't expect it
- Reviews already posted become less visible
- `GITHUB_TOKEN` cannot convert fork PRs to draft — requires a PAT or GitHub App

**Why not chosen**: Too disruptive for a project with external contributors. The manual "Ready for review" step adds unnecessary friction and may discourage participation.

### Alternative 2: Do Nothing (manual maintainer pings)

**Description**: Maintainers manually monitor PR state and ask contributors to fix issues.

**Pros**:
- No automation to maintain
- Human judgment on when to ping

**Cons**:
- Doesn't scale — maintainers become bottlenecks
- Inconsistent feedback timing
- Contributors may not know their PR needs attention until a maintainer notices

**Why not chosen**: Current pain point that motivated this ADR.

### Alternative 3: Labels Only (no comments)

**Description**: Add/remove labels automatically but don't post comments.

**Pros**:
- Less noisy — no email notifications from comments
- Labels visible in PR list for maintainer triage

**Cons**:
- Contributors may not notice a label change — no email notification for label events
- No actionable guidance on how to fix the issue

**Why not chosen**: Labels alone don't reliably notify contributors. The `@mention` comment ensures an email notification with specific instructions.

## Consequences

### Positive

- Contributors get immediate, actionable feedback when their PR needs attention
- Maintainers spend less time manually triaging PR state
- PR list is filterable by label (`needs-rebase`, `checks-failing`) for quick triage
- Labels auto-clear when issues are resolved — no stale signals
- Works for both same-repo and fork PRs (labels and comments don't require special permissions)

### Negative

- Additional GitHub Actions minutes consumed (mitigated: API-only workflow, no builds)
- Comment notifications may feel noisy if checks are flaky (mitigated: required checks should be stable per ADR-015)
- Scheduled runs add a small delay for conflict detection after pushes to main

### Neutral

- Branch protection rules remain the actual enforcement mechanism — this workflow is advisory only

## Implementation Notes

- **Triggers**: `workflow_run.completed` for check failures, `push` to `main` for conflicts, `schedule` (every 6h) as a safety net for stale `mergeable` state
- **Labels**: Create `checks-failing` (red) and `needs-rebase` (yellow) repository labels
- **Comment format**: Include the label name, a one-line explanation, and a link to relevant docs (e.g., "run `git fetch upstream && git rebase upstream/main`")
- **Idempotency**: Don't post duplicate comments — check if the most recent bot comment already describes the current issue before posting
- **Skip bots**: Exclude PRs authored by bots (Dependabot, Copilot, etc.)
- **Unresolved conversations**: Defer to a future iteration — no reliable event-driven trigger exists; would require scheduled polling of the GraphQL `reviewThreads` API

## Related Decisions

- ADR-015: GitHub Actions CI with prek (the checks being monitored)
- ADR-016: Single-branch `main` strategy (defines the base branch)

## References

- GitHub Docs: [Managing labels](https://docs.github.com/en/issues/using-labels-and-milestones-to-track-work/managing-labels)
- GitHub Docs: [Pull request mergeability](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request)
- GitHub Docs: [workflow_run event](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_run)
