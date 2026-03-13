"""Tests for apme_engine.engine.parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from apme_engine.engine.models import (
    Load,
    LoadType,
)
from apme_engine.engine.parser import Parser, load_name2target_name


class TestLoadName2TargetName:
    def test_with_prefix(self) -> None:
        assert load_name2target_name("/some/dir/load-ns.col.json") == "ns.col"

    def test_without_prefix(self) -> None:
        assert load_name2target_name("/some/dir/myproject.json") == "myproject"

    def test_bare_filename(self) -> None:
        assert load_name2target_name("load-foobar.json") == "foobar"

    def test_no_load_prefix(self) -> None:
        assert load_name2target_name("something.json") == "something"


class TestParserInit:
    def test_defaults(self) -> None:
        p = Parser()
        assert p.do_save is False
        assert p.use_ansible_doc is True
        assert p.skip_playbook_format_error is True
        assert p.skip_task_format_error is True

    def test_custom_values(self) -> None:
        p = Parser(do_save=True, use_ansible_doc=False, skip_playbook_format_error=False)
        assert p.do_save is True
        assert p.use_ansible_doc is False
        assert p.skip_playbook_format_error is False


class TestParserRun:
    def test_unsupported_type_raises(self) -> None:
        p = Parser()
        ld = Load(target_type="unsupported_type")
        with pytest.raises(ValueError, match="unsupported type"):
            p.run(load_data=ld)

    def test_playbook_only_from_yaml(self, tmp_path: Path) -> None:
        playbook_yaml = (
            "---\n- name: Test\n  hosts: localhost\n  tasks:\n"
            "    - name: Debug\n      ansible.builtin.debug:\n        msg: hello\n"
        )
        pb_path = tmp_path / "test.yml"
        pb_path.write_text(playbook_yaml)
        ld = Load(
            target_type=LoadType.PLAYBOOK,
            target_name="test",
            path=str(pb_path),
            playbook_yaml=playbook_yaml,
            playbook_only=True,
        )
        p = Parser(use_ansible_doc=False)
        result = p.run(load_data=ld)
        assert result is not None
        definitions, _ = result
        assert "playbooks" in definitions
        assert "tasks" in definitions

    def test_taskfile_only_from_yaml(self, tmp_path: Path) -> None:
        tf_yaml = "---\n- name: Copy file\n  ansible.builtin.copy:\n    src: a.txt\n    dest: /tmp/a.txt\n"
        tf_path = tmp_path / "tasks.yml"
        tf_path.write_text(tf_yaml)
        ld = Load(
            target_type=LoadType.TASKFILE,
            target_name="tasks",
            path=str(tf_path),
            taskfile_yaml=tf_yaml,
            taskfile_only=True,
        )
        p = Parser(use_ansible_doc=False)
        result = p.run(load_data=ld)
        assert result is not None
        definitions, _ = result
        assert "taskfiles" in definitions

    def test_load_json_path_not_found_raises(self) -> None:
        p = Parser()
        with pytest.raises(ValueError, match="file not found"):
            p.run(load_json_path="/nonexistent/load.json")

    def test_collection_load_returns_none_on_exception(self, tmp_path: Path) -> None:
        ld = Load(target_type=LoadType.COLLECTION, target_name="bad.col", path=str(tmp_path / "nonexistent"))
        p = Parser(use_ansible_doc=False)
        result = p.run(load_data=ld)
        assert result is None

    def test_role_load_returns_none_on_exception(self, tmp_path: Path) -> None:
        ld = Load(target_type=LoadType.ROLE, target_name="badrole", path=str(tmp_path / "nonexistent"))
        p = Parser(use_ansible_doc=False)
        result = p.run(load_data=ld)
        assert result is None


class TestParserDumpAndRestore:
    def test_dump_and_restore_round_trip(self, tmp_path: Path) -> None:
        playbook_yaml = (
            "---\n- name: Test\n  hosts: localhost\n  tasks:\n"
            "    - name: Debug\n      ansible.builtin.debug:\n        msg: hello\n"
        )
        pb_path = tmp_path / "test.yml"
        pb_path.write_text(playbook_yaml)

        ld = Load(
            target_type=LoadType.PLAYBOOK,
            target_name="test",
            path=str(pb_path),
            playbook_yaml=playbook_yaml,
            playbook_only=True,
        )
        p = Parser(use_ansible_doc=False)
        result = p.run(load_data=ld)
        assert result is not None
        definitions, returned_ld = result

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        Parser.dump_definition_objects(str(output_dir), definitions, returned_ld)

        mapping_path = output_dir / "mappings.json"
        assert mapping_path.exists()

        restored_defs, restored_ld = Parser.restore_definition_objects(str(output_dir))
        assert "playbooks" in restored_defs

    def test_restore_missing_mappings_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="file not found.*mappings"):
            Parser.restore_definition_objects(str(tmp_path))
