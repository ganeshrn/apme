---
name: pr-review
description: >
  Guide for handling pull request reviews, including automated (Copilot) and
  human reviewer feedback. Use when responding to PR comments, resolving
  review threads, or updating PRs after review.
argument-hint: "<PR number>"
user-invocable: true
metadata:
  author: APME Team
  version: 1.0.0
---

# PR Review

This skill defines how to handle PR review feedback in the APME project.

## Responding to review comments

Every review comment MUST receive a response and resolution. Unanswered
comments block merge.

### Rules

- Address ALL review comments before requesting re-review. Do not leave
  comments unanswered.
- Every comment requires two actions: a **closing reply** and **thread
  resolution**. Replying alone does not resolve the thread; the thread must
  be explicitly resolved via the GitHub UI or API.
- Reply to each comment with a **brief explanation of how it was resolved** and
  the commit hash (e.g., "Removed the unused imports so Ruff F401 passes.
  Fixed in abc1234."). Do not reply with only the SHA; explain the fix.
- If a comment is a false positive or you disagree, reply with a clear
  technical explanation, then resolve the thread. Do not dismiss without
  justification.
- After pushing fixes, update the PR description to reflect the expanded scope
  (per the submit-pr skill).

## Copilot review patterns

Copilot automated reviews surface recurring categories. Address these
proactively before pushing to avoid review round-trips:

### Supply-chain security

Pin GitHub Actions to commit SHAs instead of mutable tags (`@v1`). Mutable
tags allow upstream changes to affect CI without review. Use a comment to
note the original tag:

```yaml
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4
```

### Inaccurate documentation

Documentation MUST accurately describe the actual behavior. If a workflow
triggers on `pull_request` targeting `main`, don't document it as running
on "every pull request". Be specific about triggers, branches, and conditions.

### Markdown table formatting

Tables must use a single leading `|` on each line. Double leading `||` renders
as an extra empty column. Validate table rendering before committing.

### Inaccurate comments

Code comments and docstrings MUST accurately describe what the code does. If
you rename a function, change behavior, or remove functionality, update all
associated comments in the same commit.

### Secrets in documentation

Never show API keys, tokens, or credentials on command lines in docs or
examples. Demonstrate env var usage instead. Shell history and process lists
expose command-line arguments.

### Unused imports (Ruff F401)

Copilot often flags unused imports. With Ruff `F` rules enabled, these fail CI.
Remove unused imports or use the symbol (e.g. in a type annotation or
assertion). Prefer trimming the import list over `# noqa: F401` unless the
import is intentionally side-effect only.

## Workflow

1. After pushing a PR, wait for both CI and Copilot review.
2. Read all review comments and CI logs.
3. Fix all issues in a single commit (or minimal commits).
4. Reply to each comment with a brief explanation of how it was resolved and
   the commit hash (e.g., "Removed unused imports. Fixed in abc1234.").
5. **Resolve each review thread** after replying. Every thread must have both
   a closing reply and an explicit resolution — replying alone is not enough.

### Replying to review comments

Post a reply using the REST API. Each reply must state **how** the issue was
resolved and include the commit hash (not only the SHA):

```bash
# Example: explain the fix, then cite the commit
gh api -X POST "repos/ansible/apme/pulls/PR/comments/COMMENT_ID/replies" \
  -f body="Removed the unused imports so Ruff F401 passes. Fixed in COMMIT_SHA."
```

To get comment IDs: `gh api repos/ansible/apme/pulls/PR/comments` and use each
comment's `id`. Alternatively, reply in the GitHub PR UI, then resolve threads
via GraphQL below.

### Resolving review threads (GraphQL)

Replace `N` with the PR number and `THREAD_ID` with the `id` from
`reviewThreads.nodes[].id` (from the list query). Filter nodes where
`isResolved` is false if you only want to resolve open threads.

```bash
# List threads (get id from nodes for each thread)
gh api graphql -f query='{
  repository(owner: "ansible", name: "apme") {
    pullRequest(number: N) {
      reviewThreads(first: 20) {
        nodes { id isResolved comments(first:1) { nodes { body } } }
      }
    }
  }
}'

# Resolve one thread
gh api graphql -f query='mutation {
  resolveReviewThread(input: {threadId: "THREAD_ID"}) {
    thread { isResolved }
  }
}'
```

6. Update the PR description to include the new commit(s).
7. If CI failure is unrelated to your changes (e.g., flaky test, transient
   network issue), fix it anyway — the PR owns the green build.

### After pushing fixes: check for a new Copilot review

Copilot may run again on new commits. Re-check whether it left a new review or
line comments so you can reply and resolve any new threads.

```bash
# New Copilot review (replace N with PR number, ISO8601 with last push time)
gh api repos/ansible/apme/pulls/N/reviews --jq '.[] | select(.user.login == "copilot-pull-request-reviewer[bot]" and .submitted_at > "ISO8601") | {submitted_at, state, body: .body[0:200]}'

# New Copilot line comments (replace N and ISO8601)
gh api repos/ansible/apme/pulls/N/comments --jq '.[] | select(.user.login == "Copilot" and .created_at > "ISO8601") | {id, created_at, path, body: .body[0:150]}'
```

If both return nothing, no new Copilot activity. Otherwise, address new
comments (reply with how it was resolved + commit hash, then resolve threads)
and repeat this check after the next push.
