"""Native rule L046: detect modules using free-form key=value syntax."""

import re
from dataclasses import dataclass
from typing import cast

from apme_engine.engine.models import (
    AnsibleRunContext,
    Rule,
    RuleResult,
    RunTargetType,
    Severity,
    YAMLDict,
)
from apme_engine.engine.models import (
    ExecutableType as ActionType,
)
from apme_engine.engine.models import (
    RuleTag as Tag,
)

_KV_PATTERN = re.compile(r"\b\w+=\S")

_COMMAND_MODULES = frozenset(
    {
        "ansible.builtin.command",
        "ansible.builtin.shell",
        "ansible.builtin.raw",
        "ansible.builtin.script",
        "ansible.legacy.command",
        "ansible.legacy.shell",
        "ansible.legacy.raw",
        "ansible.legacy.script",
        "command",
        "shell",
        "raw",
        "script",
    }
)


@dataclass
class NoFreeFormRule(Rule):
    """Rule for avoiding free-form key=value syntax on module actions.

    Detects any module invoked with a string argument containing
    ``key=value`` pairs (e.g. ``stat: path=/tmp``).  The preferred
    style is a YAML mapping with explicit keys.

    Attributes:
        rule_id: Rule identifier.
        description: Rule description.
        enabled: Whether the rule is enabled.
        name: Rule name.
        version: Rule version.
        severity: Severity level.
        tags: Rule tags.
    """

    rule_id: str = "L046"
    description: str = "Avoid free-form when calling module actions"
    enabled: bool = True
    name: str = "NoFreeForm"
    version: str = "v0.0.1"
    severity: str = Severity.LOW
    tags: tuple[str, ...] = (Tag.COMMAND,)

    def match(self, ctx: AnsibleRunContext) -> bool:
        """Return True if the current target is a task.

        Args:
            ctx: Current Ansible run context.

        Returns:
            True if the current target is a task.

        """
        if ctx.current is None:
            return False
        return bool(ctx.current.type == RunTargetType.Task)

    def process(self, ctx: AnsibleRunContext) -> RuleResult | None:
        """Check for free-form module arguments and return result.

        Args:
            ctx: Current Ansible run context.

        Returns:
            RuleResult with verdict and detail if free-form usage found, None otherwise.

        """
        task = ctx.current
        if task is None:
            return None
        if getattr(task, "action_type", "") != ActionType.MODULE_TYPE:
            return RuleResult(
                verdict=False,
                file=cast("tuple[str | int, ...] | None", task.file_info()),
                rule=self.get_metadata(),
            )
        args = getattr(task, "args", None)
        raw = getattr(args, "raw", None) if args is not None else None
        if isinstance(raw, dict) and "_raw" in raw:
            raw = raw.get("_raw")
        resolved = getattr(task.spec, "resolved_name", "") or ""
        is_free_form = False
        if isinstance(raw, str) and raw.strip():
            is_free_form = True if resolved in _COMMAND_MODULES else bool(_KV_PATTERN.search(raw))
        verdict = is_free_form
        detail: dict[str, object] = {}
        if verdict:
            detail["module"] = resolved
            detail["message"] = "avoid using free-form when calling module actions"
        return RuleResult(
            verdict=verdict,
            detail=cast("YAMLDict | None", detail),
            file=cast("tuple[str | int, ...] | None", task.file_info()),
            rule=self.get_metadata(),
        )
