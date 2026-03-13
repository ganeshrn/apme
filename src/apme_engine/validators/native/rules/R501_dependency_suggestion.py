from dataclasses import dataclass
from typing import cast

from apme_engine.engine.models import (
    AnsibleRunContext,
    Rule,
    RuleResult,
    RunTargetType,
    Severity,
    Task,
    YAMLDict,
)
from apme_engine.engine.models import RuleTag as Tag


@dataclass
class DependencySuggestionRule(Rule):
    rule_id: str = "R501"
    description: str = "Suggest dependencies for unresolved modules/roles"
    enabled: bool = True
    name: str = "DependencySuggestion"
    version: str = "v0.0.1"
    severity: str = Severity.NONE
    tags: tuple[str, ...] = (Tag.DEPENDENCY,)

    def match(self, ctx: AnsibleRunContext) -> bool:
        if ctx.current is None:
            return False
        return bool(ctx.current.type == RunTargetType.Task)

    def process(self, ctx: AnsibleRunContext) -> RuleResult | None:
        task = ctx.current
        if task is None:
            return None

        verdict = False
        detail: YAMLDict = {}
        spec = task.spec
        if isinstance(spec, Task) and spec.possible_candidates:
            fqcn, defined_in = spec.possible_candidates[0]
            verdict = True
            detail["type"] = spec.executable_type.lower()
            detail["fqcn"] = fqcn
            detail["defined_in"] = defined_in

        return RuleResult(
            verdict=verdict,
            detail=detail if detail else None,
            file=cast("tuple[str | int, ...] | None", task.file_info()),
            rule=self.get_metadata(),
        )
