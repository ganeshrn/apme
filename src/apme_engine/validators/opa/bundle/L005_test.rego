# Integration tests for L005: Use only ansible.builtin or ansible.legacy

package apme.rules_test

import data.apme.rules

test_L005_fires_for_short_module_resolved_to_builtin if {
	# Engine resolved "apt" to "ansible.builtin.apt" but the YAML still says "apt"
	tree := {"nodes": [{"type": "taskcall", "module": "ansible.builtin.apt", "original_module": "apt", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	v := rules.only_builtins(tree, node)
	v.rule_id == "L005"
	v.resolved_fqcn == "ansible.builtin.apt"
	v.original_module == "apt"
}

test_L005_does_not_fire_for_builtin_fqcn if {
	tree := {"nodes": [{"type": "taskcall", "module": "ansible.builtin.copy", "original_module": "ansible.builtin.copy", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	not rules.only_builtins(tree, node)
}

test_L005_does_not_fire_for_legacy_fqcn if {
	tree := {"nodes": [{"type": "taskcall", "module": "ansible.legacy.copy", "original_module": "ansible.legacy.copy", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	not rules.only_builtins(tree, node)
}

test_L005_fires_for_collection_module if {
	tree := {"nodes": [{"type": "taskcall", "module": "community.general.ini_file", "original_module": "community.general.ini_file", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	v := rules.only_builtins(tree, node)
	v.rule_id == "L005"
	v.resolved_fqcn == "community.general.ini_file"
}

test_L005_fires_for_short_module_without_resolution if {
	# Short name where engine couldn't resolve — still fires, but without resolved_fqcn
	tree := {"nodes": [{"type": "taskcall", "module": "copy", "original_module": "copy", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	v := rules.only_builtins(tree, node)
	v.rule_id == "L005"
	not v.resolved_fqcn
}

test_L005_fires_for_taskfile_key_without_resolved_fqcn if {
	# Engine resolved "include" to an internal taskfile key — must NOT emit resolved_fqcn
	tree := {"nodes": [{"type": "taskcall", "module": "taskfile role:myrole#taskfile:roles/myrole/tasks/setup.yml", "original_module": "include", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	v := rules.only_builtins(tree, node)
	v.rule_id == "L005"
	not v.resolved_fqcn
}

test_L005_falls_back_to_module_when_original_missing if {
	# When original_module is absent, fall back to checking module
	tree := {"nodes": [{"type": "taskcall", "module": "community.general.npm", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	v := rules.only_builtins(tree, node)
	v.rule_id == "L005"
	v.resolved_fqcn == "community.general.npm"
}
