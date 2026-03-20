# Tests for M008: bare include removed

package apme.rules_test

import data.apme.rules

test_M008_fires_on_bare_include if {
	tree := {"nodes": [{"type": "taskcall", "module": "include", "original_module": "include", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	v := rules.bare_include(tree, node)
	v.rule_id == "M008"
}

test_M008_fires_on_bare_include_resolved_away if {
	# In production the engine resolves the include to a taskfile key,
	# so module != "include" but original_module preserves the YAML key.
	tree := {"nodes": [{"type": "taskcall", "module": "tasks/setup-Debian.yml", "original_module": "include", "line": [5], "key": "k", "file": "main.yml"}]}
	node := tree.nodes[0]
	v := rules.bare_include(tree, node)
	v.rule_id == "M008"
}

test_M008_fires_on_ansible_builtin_include if {
	tree := {"nodes": [{"type": "taskcall", "module": "tasks/foo.yml", "original_module": "ansible.builtin.include", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	v := rules.bare_include(tree, node)
	v.rule_id == "M008"
}

test_M008_no_fire_on_include_tasks if {
	tree := {"nodes": [{"type": "taskcall", "module": "ansible.builtin.include_tasks", "original_module": "include_tasks", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	not rules.bare_include(tree, node)
}

test_M008_no_fire_on_import_tasks if {
	tree := {"nodes": [{"type": "taskcall", "module": "ansible.builtin.import_tasks", "original_module": "import_tasks", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	not rules.bare_include(tree, node)
}

test_M008_no_fire_when_original_module_missing if {
	tree := {"nodes": [{"type": "taskcall", "module": "ansible.builtin.include_tasks", "line": [1], "key": "k", "file": "f.yml"}]}
	node := tree.nodes[0]
	not rules.bare_include(tree, node)
}
