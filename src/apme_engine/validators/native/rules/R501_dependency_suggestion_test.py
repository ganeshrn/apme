# Colocated tests for R501 (DependencySuggestionRule).

from apme_engine.validators.native.rules._test_helpers import (
    make_context,
    make_task_call,
    make_task_spec,
)
from apme_engine.validators.native.rules.R501_dependency_suggestion import DependencySuggestionRule


def test_R501_fires_when_possible_candidates() -> None:
    spec = make_task_spec(
        module="ansible.builtin.some_unknown",
        possible_candidates=[("ansible.builtin.copy", "/path/to/collection")],
    )
    task = make_task_call(spec)
    ctx = make_context(task)
    rule = DependencySuggestionRule()
    assert rule.match(ctx)
    result = rule.process(ctx)
    assert result is not None
    assert result.verdict is True
    assert result.rule is not None and result.rule.rule_id == "R501"
    assert result.detail is not None
    assert result.detail.get("fqcn") == "ansible.builtin.copy"
    assert result.detail.get("defined_in") == "/path/to/collection"


def test_R501_does_not_fire_when_no_possible_candidates() -> None:
    spec = make_task_spec(module="ansible.builtin.copy", resolved_name="ansible.builtin.copy")
    task = make_task_call(spec)
    ctx = make_context(task)
    rule = DependencySuggestionRule()
    assert rule.match(ctx)
    result = rule.process(ctx)
    assert result is not None
    assert result.verdict is False
