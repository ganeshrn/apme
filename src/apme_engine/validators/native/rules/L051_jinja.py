"""Native rule L051: detect Jinja formatting issues (brace spacing and filter pipe spacing)."""

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
    RuleTag as Tag,
)

JINJA_NO_SPACE = re.compile(r"\{\{[^\s\}].*?\}\}|\{\{.*?[^\s\{]\}\}")
JINJA_EXPR_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")
JINJA_PIPE_BAD = re.compile(r"(?<!\|)\|(?!\|)(?:\S)|\S(?<!\|)\|(?!\|)")


@dataclass
class JinjaRule(Rule):
    """Rule for Jinja formatting: brace spacing and filter pipe spacing.

    Detects ``{{foo}}`` (missing brace spaces) and ``foo|bar`` (missing pipe
    spaces) inside Jinja expressions.

    Attributes:
        rule_id: Rule identifier.
        description: Rule description.
        enabled: Whether the rule is enabled.
        name: Rule name.
        version: Rule version.
        severity: Severity level.
        tags: Rule tags.
    """

    rule_id: str = "L051"
    description: str = "Jinja spacing could be improved"
    enabled: bool = True
    name: str = "Jinja"
    version: str = "v0.0.1"
    severity: str = Severity.VERY_LOW
    tags: tuple[str, ...] = (Tag.QUALITY,)

    def match(self, ctx: AnsibleRunContext) -> bool:
        """Check if context has a task target.

        Args:
            ctx: AnsibleRunContext to evaluate.

        Returns:
            True if current target is a task.
        """
        if ctx.current is None:
            return False
        return bool(ctx.current.type == RunTargetType.Task)

    def process(self, ctx: AnsibleRunContext) -> RuleResult | None:
        """Check Jinja spacing (braces and pipes) and return result.

        Args:
            ctx: AnsibleRunContext to process.

        Returns:
            RuleResult with bad_expressions/message detail, or None.
        """
        task = ctx.current
        if task is None:
            return None
        spec = task.spec
        yaml_lines = getattr(spec, "yaml_lines", "") or ""
        options = getattr(spec, "options", None) or {}
        module_options = getattr(spec, "module_options", None) or {}
        text = yaml_lines
        for v in (options, module_options):
            if isinstance(v, dict):
                for val in v.values():
                    if isinstance(val, str):
                        text += " " + val

        bad: list[str] = []
        bad.extend(JINJA_NO_SPACE.findall(text))

        for m in JINJA_EXPR_RE.finditer(text):
            inner = m.group(1)
            if JINJA_PIPE_BAD.search(inner):
                bad.append(m.group(0))

        verdict = len(bad) > 0
        detail: dict[str, object] = {}
        if bad:
            detail["bad_expressions"] = list(dict.fromkeys(bad))[:10]
            detail["message"] = "Jinja2 spacing could be improved"
        return RuleResult(
            verdict=verdict,
            detail=cast(YAMLDict | None, detail),
            file=cast("tuple[str | int, ...] | None", task.file_info()),
            rule=self.get_metadata(),
        )
