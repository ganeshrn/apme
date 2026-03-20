"""Risk detection from Ansible tasks via rule evaluation."""

from __future__ import annotations

import contextlib
import json
import os
import time
import traceback
from typing import cast

from . import logger
from .keyutil import detect_type, key_delimiter
from .models import (
    AnsibleRunContext,
    ARIResult,
    FatalRuleResultError,
    NodeResult,
    Rule,
    RuleResult,
    RunTarget,
    SpecMutation,
    TargetResult,
    TaskCall,
    YAMLDict,
)
from .utils import load_classes_in_dir

rule_versions_filename = "rule_versions.json"


def key2name(key: str) -> str:
    """Extract the name (last segment) from a key using key_delimiter.

    Args:
        key: Key string (e.g. "collection/namespace/name").

    Returns:
        Last segment of the key.
    """
    return key.split(key_delimiter)[-1]


def load_rule_versions_file(filepath: str) -> dict[str, object]:
    """Load rule_id -> commit_id mappings from a newline-delimited JSON file.

    Args:
        filepath: Path to rule_versions.json.

    Returns:
        Dict mapping rule_id to commit_id. Empty if file missing or invalid.
    """
    if not os.path.exists(filepath):
        return {}

    version_dict = {}
    with open(filepath) as file:
        for line in file:
            d = None
            with contextlib.suppress(Exception):
                d = json.loads(line)
            if not d or not isinstance(d, dict):
                continue
            rule_id = d.get("rule_id")
            if not rule_id:
                continue
            commit_id = d.get("commit_id")
            version_dict[rule_id] = commit_id
    return version_dict


def load_rules(
    rules_dir: str = "",
    rule_id_list: list[str] | None = None,
    fail_on_error: bool = False,
    exclude_rule_ids: list[str] | None = None,
) -> list[Rule]:
    """Load Rule classes from directories, optionally filtered by rule IDs.

    Supports colon-separated rules_dir. Applies rule_versions.json for commit_id.
    Sorts by rule_id suffix, rule_id_list order, and precedence.

    Args:
        rules_dir: Directory or colon-separated dirs containing rule modules.
        rule_id_list: If provided, only load rules in this list.
        fail_on_error: If True, raise on load errors; else log and skip.
        exclude_rule_ids: Rule IDs to exclude from loading.

    Returns:
        List of instantiated Rule objects, sorted.

    Raises:
        ValueError: If fail_on_error and load/instantiation fails.
    """
    if rule_id_list is None:
        rule_id_list = []
    if not rules_dir:
        return []
    if exclude_rule_ids is None:
        exclude_rule_ids = []
    rules_dir_list = rules_dir.split(":")
    _rules = []
    for _rules_dir in rules_dir_list:
        versions_file = os.path.join(_rules_dir, rule_versions_filename)
        versions_dict = {}
        if os.path.exists(versions_file):
            versions_dict = load_rule_versions_file(versions_file)
        _rule_classes, _errors_for_this_dir = load_classes_in_dir(_rules_dir, Rule, fail_on_error=fail_on_error)
        if _errors_for_this_dir:
            if fail_on_error:
                raise ValueError("error occurred while loading rule directory: " + "; ".join(_errors_for_this_dir))
            else:
                logger.warning("some rules are skipped by the following errors: " + "; ".join(_errors_for_this_dir))
        for r in _rule_classes:
            try:
                _rule = cast(Rule, r())
                # if `rule_id_list` is provided, filter out rules that are not in the list
                if rule_id_list and _rule.rule_id not in rule_id_list:
                    continue
                if _rule.rule_id in exclude_rule_ids:
                    continue
                if versions_dict and _rule.rule_id in versions_dict:
                    _rule.commit_id = (
                        str(versions_dict[_rule.rule_id]) if versions_dict[_rule.rule_id] is not None else ""
                    )
                _rules.append(_rule)
            except Exception as err:
                exc = traceback.format_exc()
                msg = f"failed to load a rule `{r}`: {exc}"
                if fail_on_error:
                    raise ValueError(msg) from err
                else:
                    logger.warning(f"The rule {r} was skipped: {msg}")

    # sort by rule_id
    _rules = sorted(_rules, key=lambda r: int(r.rule_id[-3:]))

    # sort by `rules` configuration for ARIScanner
    if rule_id_list:

        def index(_list: list[str], x: Rule) -> int:
            if x.rule_id in _list:
                return _list.index(x.rule_id)
            else:
                return len(_list)

        _rules = sorted(_rules, key=lambda r: index(rule_id_list, r))

    # sort by precedence
    _rules = sorted(_rules, key=lambda r: r.precedence)

    return _rules


def make_subject_str(playbook_num: int, role_num: int) -> str:
    """Build a subject string describing what was scanned (playbooks/roles).

    Args:
        playbook_num: Number of playbooks.
        role_num: Number of roles.

    Returns:
        "playbooks/roles", "playbooks", "roles", or "".
    """
    subject = ""
    if playbook_num > 0 and role_num > 0:
        subject = "playbooks/roles"
    elif playbook_num > 0:
        subject = "playbooks"
    elif role_num > 0:
        subject = "roles"
    return subject


def detect(
    contexts: list[AnsibleRunContext],
    rules_dir: str = "",
    rules: list[Rule] | None = None,
    rules_cache: list[Rule] | None = None,
    save_only_rule_result: bool = False,
    exclude_rule_ids: list[str] | None = None,
) -> tuple[dict[str, object], list[Rule]]:
    """Run rules against task contexts and return ARI result plus loaded rules.

    Evaluates each rule against each task in each context. Builds ARIResult with
    TargetResult and NodeResult. Collects spec_mutations from rules.

    Args:
        contexts: Ansible run contexts with taskcalls.
        rules_dir: Directory to load rules from if rules/rules_cache empty.
        rules: Pre-loaded rules. If provided, rule_ids used for filtering.
        rules_cache: Cached rules to reuse instead of loading.
        save_only_rule_result: Omit node details in output.
        exclude_rule_ids: Rule IDs to exclude.

    Returns:
        Tuple of (data_report dict with ari_result and spec_mutations, loaded rules).

    Raises:
        FatalRuleResultError: If a rule returns fatal=True.
    """
    if rules_cache is None:
        rules_cache = []
    if rules is None:
        rules = []
    rule_ids: list[str] | None = [r.rule_id for r in rules] if rules else None
    loaded_rules: list[Rule] = rules_cache or load_rules(
        rules_dir, rule_ids, False, exclude_rule_ids=exclude_rule_ids or []
    )

    playbook_count = {"total": 0, "risk_found": 0}
    role_count = {"total": 0, "risk_found": 0}

    data_report: dict[str, object] = {"summary": {}, "details": [], "ari_result": None}
    role_to_playbook_mappings: dict[str, list[str]] = {}

    ari_result = ARIResult()
    spec_mutations = {}

    for ctx in contexts:
        if not isinstance(ctx, AnsibleRunContext):
            continue
        tree_root_key = ctx.root_key
        tree_root_type = detect_type(tree_root_key)
        tree_root_name = key2name(tree_root_key)

        t_result = TargetResult(
            target_type=tree_root_type,
            target_name=tree_root_name,
        )

        is_playbook = tree_root_type == "playbook"
        if is_playbook:
            playbook_count["total"] += 1

            for task in ctx.taskcalls:
                defined_in = getattr(task.spec, "defined_in", "") if task.spec else ""
                parts = defined_in.split("/")
                if parts[0] == "roles":
                    role_name = parts[1]
                    _mappings = role_to_playbook_mappings.get(role_name, [])
                    if tree_root_name not in _mappings:
                        _mappings.append(tree_root_name)
                    role_to_playbook_mappings[role_name] = _mappings
        else:
            role_count["total"] += 1

        for t in ctx:
            ctx.current = t
            n_result = NodeResult(node=t)
            for rule in loaded_rules:
                if not rule.enabled:
                    continue
                rule_id = rule.rule_id
                start_time = time.time()
                file_info = t.file_info()
                r_result = RuleResult(
                    file=(file_info[0], file_info[1] if file_info[1] is not None else 0),
                    rule=rule.get_metadata(),
                )
                detail: dict[str, object] = {}
                try:
                    matched = rule.match(ctx)
                    if matched:
                        tmp_result = rule.process(ctx)
                        if tmp_result:
                            r_result = tmp_result
                        r_result.matched = matched
                    r_result.duration = round((time.time() - start_time) * 1000, 6)
                    detail = cast(dict[str, object], r_result.get_detail() or {})
                    fatal = detail.get("fatal", False) if detail else False
                    if fatal:
                        error = r_result.error or "unknown error"
                        error = f"ARI rule evaluation threw fatal exception: RuleID={rule_id}, error={error}"
                        raise FatalRuleResultError(error)
                    if rule.spec_mutation:
                        s_mutations = detail.get("spec_mutations", [])
                        for s_mutation in s_mutations if isinstance(s_mutations, list) else []:
                            if not isinstance(s_mutation, SpecMutation):
                                continue
                            spec_mutations[s_mutation.key] = s_mutation
                except FatalRuleResultError:
                    raise
                except Exception:
                    exc = traceback.format_exc()
                    r_result.error = f"failed to execute the rule `{rule.rule_id}`: {exc}"
                n_result.rules.append(r_result)
            # remove node details (replace node with summary dict when save_only_rule_result)
            if save_only_rule_result and n_result.node is not None and isinstance(n_result.node, RunTarget):
                n_result.node = cast(YAMLDict, omit_node_details(n_result.node))
            t_result.nodes.append(n_result)
        ari_result.targets.append(t_result)

    data_report["ari_result"] = ari_result
    data_report["spec_mutations"] = spec_mutations

    return data_report, loaded_rules


def omit_node_details(node: RunTarget) -> dict[str, object]:
    """Reduce a RunTarget to a summary dict (type, spec) for compact output.

    Args:
        node: RunTarget (e.g. TaskCall) to summarize.

    Returns:
        Dict with type and spec keys.
    """
    spec = None
    if node.spec:
        spec = {
            "type": getattr(node.spec, "type", ""),
            "name": getattr(node.spec, "name", ""),
            "defined_in": getattr(node.spec, "defined_in", ""),
        }
        if isinstance(node, TaskCall) and node.spec:
            spec["line_num_in_file"] = (getattr(node.spec, "line_num_in_file", 0),)
    summary: dict[str, object] = {
        "type": node.type,
        "spec": spec,
    }
    return summary
