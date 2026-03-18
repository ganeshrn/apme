"""Finding partition — routes violations to Tier 1, 2, or 3."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apme_engine.engine.models import ViolationDict
from apme_engine.remediation.registry import TransformRegistry


def is_finding_resolvable(violation: ViolationDict, registry: TransformRegistry) -> bool:
    """Return True if the violation has a registered deterministic transform (Tier 1).

    Args:
        violation: Violation dict with rule_id.
        registry: Transform registry to check for rule.

    Returns:
        True if rule_id has a registered transform.
    """
    rule_id = str(violation.get("rule_id", ""))
    # Native validator prefixes rule IDs with "native:" — strip it for registry lookup
    if rule_id.startswith("native:"):
        rule_id = rule_id[len("native:"):]
    return rule_id in registry


def partition_violations(
    violations: list[ViolationDict],
    registry: TransformRegistry,
) -> tuple[list[ViolationDict], list[ViolationDict], list[ViolationDict]]:
    """Split violations into (tier1_fixable, tier2_ai, tier3_manual).

    Tier 1: deterministic transform exists in registry.
    Tier 2: no transform, but ai_proposable (default True if not set).
    Tier 3: no transform, ai_proposable explicitly False.

    Args:
        violations: List of violation dicts.
        registry: Transform registry for Tier 1 lookup.

    Returns:
        Tuple of (tier1_fixable, tier2_ai, tier3_manual).
    """
    tier1: list[ViolationDict] = []
    tier2: list[ViolationDict] = []
    tier3: list[ViolationDict] = []

    for v in violations:
        if is_finding_resolvable(v, registry):
            tier1.append(v)
        elif v.get("ai_proposable", True):
            tier2.append(v)
        else:
            tier3.append(v)

    return tier1, tier2, tier3
