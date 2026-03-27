"""Feedback endpoint — creates GitHub issues for false positives and bad AI suggestions.

This is a pre-production feature gated by ``APME_FEEDBACK_ENABLED``.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apme_gateway.config import load_config

logger = logging.getLogger("apme.gateway.feedback")

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackContext(BaseModel):  # type: ignore[misc]
    """Optional context attached to feedback.

    Attributes:
        violation_message: Message from the violation.
        ai_proposal_diff: Diff from the AI proposal.
        ai_explanation: Explanation from the AI proposal.
        source_snippet: Source lines around the violation.
    """

    violation_message: str = ""
    ai_proposal_diff: str = ""
    ai_explanation: str = ""
    source_snippet: str = ""


class FeedbackRequest(BaseModel):  # type: ignore[misc]
    """Payload for the feedback endpoint.

    Attributes:
        feedback_type: Category of the feedback.
        rule_id: Rule ID that triggered the issue.
        source: Validator that produced the violation.
        file: File path where the violation occurred.
        scan_id: Scan ID for traceability.
        context: Optional structured context.
        user_comment: Free-text user comment.
    """

    feedback_type: Literal["false_positive", "bad_ai_suggestion", "rule_misfire"] = Field(..., alias="type")
    rule_id: str = ""
    source: str = ""
    file: str = ""
    scan_id: str = ""
    context: FeedbackContext = Field(default_factory=FeedbackContext)
    user_comment: str = ""


class FeedbackResponse(BaseModel):  # type: ignore[misc]
    """Response from the feedback endpoint.

    Attributes:
        issue_url: URL of the created GitHub issue.
        issue_number: Number of the created GitHub issue.
    """

    issue_url: str
    issue_number: int


_TYPE_LABELS = {
    "false_positive": "false-positive",
    "bad_ai_suggestion": "bad-ai",
    "rule_misfire": "rule-misfire",
}

_TYPE_TITLES = {
    "false_positive": "False Positive",
    "bad_ai_suggestion": "Bad AI Suggestion",
    "rule_misfire": "Rule Misfire",
}


def _build_issue_body(req: FeedbackRequest) -> str:
    """Format a GitHub issue body from a feedback request.

    Args:
        req: The feedback request.

    Returns:
        Markdown-formatted issue body.
    """
    sections = [
        f"**Type:** {_TYPE_TITLES.get(req.feedback_type, req.feedback_type)}",
        f"**Rule:** `{req.rule_id}`" + (f" (source: `{req.source}`)" if req.source else ""),
        f"**File:** `{req.file}`" if req.file else "",
        f"**Scan ID:** `{req.scan_id}`" if req.scan_id else "",
    ]
    body = "\n".join(s for s in sections if s)

    if req.user_comment:
        body += f"\n\n## User Comment\n\n{req.user_comment}"

    ctx = req.context
    if ctx.violation_message:
        body += f"\n\n## Violation Message\n\n{ctx.violation_message}"
    if ctx.ai_explanation:
        body += f"\n\n## AI Explanation\n\n{ctx.ai_explanation}"
    if ctx.source_snippet:
        body += f"\n\n## Source Context\n\n```yaml\n{ctx.source_snippet}\n```"
    if ctx.ai_proposal_diff:
        body += f"\n\n## AI Proposed Diff\n\n```diff\n{ctx.ai_proposal_diff}\n```"

    return body


@router.get("/feedback/enabled")  # type: ignore[untyped-decorator]
async def feedback_enabled() -> dict[str, bool]:
    """Check whether the feedback feature is enabled.

    Returns:
        Dict with ``enabled`` boolean.
    """
    cfg = load_config()
    return {"enabled": cfg.feedback_enabled}


@router.post("/feedback", response_model=FeedbackResponse)  # type: ignore[untyped-decorator]
async def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """Create a GitHub issue from user feedback.

    Args:
        req: The feedback request payload.

    Returns:
        FeedbackResponse with issue URL and number.

    Raises:
        HTTPException: If feedback is disabled or GitHub API fails.
    """
    cfg = load_config()

    if not cfg.feedback_enabled:
        raise HTTPException(status_code=403, detail="Feedback feature is disabled")

    if not cfg.feedback_github_repo or not cfg.feedback_github_token:
        raise HTTPException(
            status_code=503,
            detail="Feedback not configured (APME_FEEDBACK_GITHUB_REPO / APME_FEEDBACK_GITHUB_TOKEN)",
        )

    title = f"[{_TYPE_TITLES.get(req.feedback_type, req.feedback_type)}] {req.rule_id}"
    if req.file:
        title += f" in {req.file}"

    body = _build_issue_body(req)
    labels = ["feedback", _TYPE_LABELS.get(req.feedback_type, "feedback")]

    api_url = f"https://api.github.com/repos/{cfg.feedback_github_repo}/issues"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            api_url,
            json={"title": title, "body": body, "labels": labels},
            headers={
                "Authorization": f"Bearer {cfg.feedback_github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15.0,
        )

    if resp.status_code not in (200, 201):
        logger.error("GitHub API error: %d %s", resp.status_code, resp.text[:500])
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API returned {resp.status_code}",
        )

    data = resp.json()
    return FeedbackResponse(
        issue_url=data.get("html_url", ""),
        issue_number=data.get("number", 0),
    )
