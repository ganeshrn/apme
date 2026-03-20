"""Tests for native rule L060."""

from typing import cast

from apme_engine.validators.native.rules._test_helpers import (
    make_context,
    make_task_call,
    make_task_spec,
)
from apme_engine.validators.native.rules.L060_line_length import (
    DEFAULT_MAX_LINE_LENGTH,
    LineLengthRule,
)


def test_L060_fires_when_line_exceeds_max() -> None:
    """Verify L060 fires when a line exceeds the max length."""
    long_line = "x" * (DEFAULT_MAX_LINE_LENGTH + 1)
    spec = make_task_spec(module="ansible.builtin.debug")
    spec.yaml_lines = f"- name: Test\n  debug:\n    msg: {long_line}"
    task = make_task_call(spec)
    ctx = make_context(task)
    rule = LineLengthRule()
    assert rule.match(ctx)
    result = rule.process(ctx)
    assert result is not None
    assert result.verdict is True
    assert result.rule is not None and result.rule.rule_id == "L060"
    assert result.detail is not None
    assert "long_lines" in result.detail
    long_lines = cast("list[dict[str, int]]", result.detail["long_lines"])
    assert len(long_lines) == 1
    assert long_lines[0]["line"] == 3
    assert long_lines[0]["length"] == len(f"    msg: {long_line}")


def test_L060_does_not_fire_within_limit() -> None:
    """Verify L060 does not fire when all lines are within limit."""
    prefix = "    msg: "
    short_line = "x" * (DEFAULT_MAX_LINE_LENGTH - len(prefix))
    spec = make_task_spec(module="ansible.builtin.debug")
    spec.yaml_lines = f"- name: Test\n  debug:\n{prefix}{short_line}"
    task = make_task_call(spec)
    ctx = make_context(task)
    rule = LineLengthRule()
    assert rule.match(ctx)
    result = rule.process(ctx)
    assert result is not None
    assert result.verdict is False


def test_L060_reports_multiple_long_lines() -> None:
    """Verify L060 reports all lines that exceed the limit."""
    long = "y" * (DEFAULT_MAX_LINE_LENGTH + 10)
    spec = make_task_spec(module="ansible.builtin.debug")
    spec.yaml_lines = f"{long}\nshort\n{long}"
    task = make_task_call(spec)
    ctx = make_context(task)
    rule = LineLengthRule()
    result = rule.process(ctx)
    assert result is not None
    assert result.verdict is True
    assert result.detail is not None
    long_lines = cast("list[dict[str, int]]", result.detail["long_lines"])
    assert len(long_lines) == 2
    assert long_lines[0]["line"] == 1
    assert long_lines[1]["line"] == 3


def test_L060_does_not_fire_for_role() -> None:
    """Verify L060 does not fire for role targets."""
    from apme_engine.validators.native.rules._test_helpers import make_role_call, make_role_spec

    role = make_role_call(make_role_spec(name="foo"))
    ctx = make_context(role)
    rule = LineLengthRule()
    assert not rule.match(ctx)
