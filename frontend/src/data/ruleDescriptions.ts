/**
 * Strip validator prefix (e.g. "native:L042" → "L042") for description lookup.
 */
export function bareRuleId(ruleId: string): string {
  const idx = ruleId.indexOf(":");
  if (idx > 0 && idx < ruleId.length - 1) return ruleId.slice(idx + 1);
  return ruleId;
}

/**
 * Look up a rule description, handling prefixed IDs like "native:L042".
 */
export function getRuleDescription(ruleId: string): string {
  return RULE_DESCRIPTIONS[ruleId] ?? RULE_DESCRIPTIONS[bareRuleId(ruleId)] ?? "";
}

/**
 * Rule ID → human-readable description mapping.
 * Source: docs/rules/RULE_CATALOG.md (auto-generated from validator frontmatter).
 */
export const RULE_DESCRIPTIONS: Record<string, string> = {
  L002: "Use fully qualified collection name for modules.",
  L003: "Each play should have a name.",
  L004: "Do not use deprecated modules.",
  L005: "Use ansible.builtin or ansible.legacy.",
  L006: "Use dedicated module instead of command.",
  L007: "Prefer command when no shell features needed.",
  L008: "Use delegate_to: localhost instead of local_action.",
  L009: "Avoid comparison to empty string in when.",
  L010: "Use failed_when or register instead of ignore_errors.",
  L011: "Avoid literal true/false in when.",
  L012: "Avoid state=latest; pin package versions.",
  L013: "command/shell/raw need changed_when or creates/removes.",
  L014: "Use notify/handler instead of when: result.changed.",
  L015: "Avoid Jinja in when; use variables.",
  L016: "pause without seconds/minutes prompts for input.",
  L017: "Avoid relative path in src.",
  L018: "become_user should have corresponding become.",
  L019: "Playbook should have .yml or .yaml extension.",
  L020: "mode should be string with leading zero.",
  L021: "Set mode explicitly for file/copy/template.",
  L022: "Shell with pipe should set set -o pipefail.",
  L023: "Consider whether run_once is appropriate.",
  L024: "Task should have a name.",
  L025: "Task/play name should start with uppercase.",
  L026: "Tasks should use FQCN for modules.",
  L027: "Roles should have meta/main.yml with metadata.",
  L030: "Prefer ansible.builtin modules when available.",
  L031: "File permission may be insecure.",
  L032: "Variable redefinition may cause confusion.",
  L033: "Overriding vars without conditions.",
  L034: "Lower-precedence override may be unused.",
  L035: "set_fact with random in args.",
  L036: "include_vars without when/tags.",
  L037: "Module name could not be resolved.",
  L038: "Role could not be resolved.",
  L039: "Variable use may be undefined.",
  L040: "YAML should not contain tabs; use spaces.",
  L041: "Task keys should follow canonical order.",
  L042: "Play/block has high task count.",
  L043: "Avoid {{ foo }}; prefer explicit form.",
  L044: "Set state explicitly where it matters.",
  L045: "Avoid inline environment in tasks.",
  L046: "Avoid raw/command/shell without args key.",
  L047: "Set no_log for password-like parameters.",
  L048: "copy with remote_src should set owner.",
  L049: "Loop variable should use prefix (e.g. item_).",
  L050: "Variable names: lowercase, underscores.",
  L051: "Jinja spacing: {{ var }} not {{var}}.",
  L052: "Galaxy version in meta should be semantic.",
  L053: "Role meta should have valid structure.",
  L054: "Role meta galaxy_info should include galaxy_tags.",
  L055: "Role meta video_links should be valid URLs.",
  L056: "Path may match ignore pattern.",
  L057: "Syntax check via ansible-playbook --syntax-check.",
  L058: "Argspec validation (docstring-based).",
  L059: "Argspec validation (mock/patch-based).",
  M001: "FQCN resolution — module resolved to a different canonical name.",
  M002: "Deprecated module — module has deprecation metadata.",
  M003: "Module redirect — module name was redirected to a new FQCN.",
  M004: "Removed module — tombstoned module.",
  M005: "Registered variable may be untrusted in 2.19+.",
  M006: "become with ignore_errors will not catch timeout in 2.19+.",
  M008: "Bare include is removed in 2.19+; use include_tasks or import_tasks.",
  M009: "with_* loops are deprecated; use loop instead.",
  M010: "ansible_python_interpreter set to Python 2; dropped in 2.18+.",
  M011: "Network module may require collection upgrade for 2.19+ compatibility.",
  P001: "Validate module name (Ansible required).",
  P002: "Validate module argument keys (Ansible required).",
  P003: "Validate module argument values (Ansible required).",
  P004: "Validate variables (Ansible required).",
  R101: "Task executes parameterized command.",
  R103: "Task downloads and executes.",
  R104: "Download from unauthorized source.",
  R105: "Outbound transfer.",
  R106: "Inbound transfer.",
  R107: "Package install with insecure option.",
  R108: "Privilege escalation.",
  R109: "Key/config change.",
  R111: "Parameterized role import.",
  R112: "Parameterized taskfile import.",
  R113: "Parameterized package install.",
  R114: "File change.",
  R115: "File deletion.",
  R117: "Role is from Galaxy/external source.",
  R118: "Task downloads from an external source.",
  R401: "Report inbound transfer sources.",
  R402: "Report variables used at end of sequence.",
  R404: "Expose variable_set for the task.",
  R501: "Suggest collection/role dependency.",
};
