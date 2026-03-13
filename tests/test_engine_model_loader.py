"""Tests for apme_engine.engine.model_loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from apme_engine.engine.model_loader import (
    _safe_int,
    load_file,
    load_play,
    load_playbook,
    load_requirements,
    load_roleinplay,
    load_task,
    load_taskfile,
)
from apme_engine.engine.models import (
    File,
    Play,
    Playbook,
    PlaybookFormatError,
    RoleInPlay,
    Task,
    TaskFile,
    YAMLDict,
)

SIMPLE_PLAYBOOK_YAML = (
    "---\n"
    "- name: Test play\n"
    "  hosts: localhost\n"
    "  tasks:\n"
    "    - name: Debug\n"
    "      ansible.builtin.debug:\n"
    "        msg: hello\n"
)

SIMPLE_TASKFILE_YAML = (
    "---\n"
    "- name: Copy file\n"
    "  ansible.builtin.copy:\n"
    "    src: a.txt\n"
    "    dest: /tmp/a.txt\n"
)


class TestSafeInt:
    def test_int(self) -> None:
        assert _safe_int(42) == 42

    def test_float(self) -> None:
        assert _safe_int(3.7) == 3

    def test_str_valid(self) -> None:
        assert _safe_int("10") == 10

    def test_str_invalid(self) -> None:
        assert _safe_int("abc") == 0

    def test_none(self) -> None:
        assert _safe_int(None) == 0

    def test_list(self) -> None:
        assert _safe_int([1, 2]) == 0


class TestLoadPlaybook:
    def test_from_yaml_str(self) -> None:
        pb = load_playbook(yaml_str=SIMPLE_PLAYBOOK_YAML)
        assert isinstance(pb, Playbook)
        assert pb.type == "playbook"
        assert len(pb.plays) > 0

    def test_from_file(self, tmp_path: Path) -> None:
        pb_file = tmp_path / "play.yml"
        pb_file.write_text(SIMPLE_PLAYBOOK_YAML)
        pb = load_playbook(path="play.yml", basedir=str(tmp_path))
        assert isinstance(pb, Playbook)
        assert len(pb.plays) > 0

    def test_multi_play(self) -> None:
        yaml_str = (
            "---\n"
            "- name: Play 1\n"
            "  hosts: web\n"
            "  tasks:\n"
            "    - name: Task 1\n"
            "      ansible.builtin.debug:\n"
            "        msg: play1\n"
            "\n"
            "- name: Play 2\n"
            "  hosts: db\n"
            "  tasks:\n"
            "    - name: Task 2\n"
            "      ansible.builtin.debug:\n"
            "        msg: play2\n"
        )
        pb = load_playbook(yaml_str=yaml_str)
        assert len(pb.plays) == 2

    def test_empty_yaml(self) -> None:
        pb = load_playbook(yaml_str="---\n")
        assert isinstance(pb, Playbook)
        assert len(pb.plays) == 0

    def test_malformed_yaml_raises(self) -> None:
        yaml_str = "---\nnot_a_playbook:\n  key: value\n"
        with pytest.raises(PlaybookFormatError):
            load_playbook(yaml_str=yaml_str, skip_playbook_format_error=False)


class TestLoadTaskfile:
    def test_from_yaml_str(self) -> None:
        tf = load_taskfile(path="tasks/main.yml", yaml_str=SIMPLE_TASKFILE_YAML)
        assert isinstance(tf, TaskFile)
        assert len(tf.tasks) > 0

    def test_from_file(self, tmp_path: Path) -> None:
        tf_file = tmp_path / "tasks.yml"
        tf_file.write_text(SIMPLE_TASKFILE_YAML)
        tf = load_taskfile(path="tasks.yml", basedir=str(tmp_path))
        assert isinstance(tf, TaskFile)

    def test_empty_taskfile(self) -> None:
        tf = load_taskfile(path="empty.yml", yaml_str="---\n")
        assert isinstance(tf, TaskFile)
        assert len(tf.tasks) == 0


class TestLoadPlay:
    def test_basic_play(self) -> None:
        play_dict: YAMLDict = {
            "name": "My play",
            "hosts": "localhost",
            "gather_facts": False,
            "tasks": [
                {"name": "Debug task", "ansible.builtin.debug": {"msg": "hello"}},
            ],
        }
        play = load_play(
            path="play.yml",
            index=0,
            play_block_dict=play_dict,
            yaml_lines=SIMPLE_PLAYBOOK_YAML,
        )
        assert isinstance(play, Play)
        assert play.name == "My play"
        assert len(play.tasks) > 0

    def test_play_with_roles(self) -> None:
        play_dict: YAMLDict = {
            "name": "Role play",
            "hosts": "all",
            "roles": [{"role": "common"}],
            "tasks": [],
        }
        play = load_play(path="pb.yml", index=0, play_block_dict=play_dict, yaml_lines="---\n")
        assert isinstance(play, Play)
        assert len(play.roles) > 0

    def test_play_with_become(self) -> None:
        play_dict: YAMLDict = {
            "name": "Privileged play",
            "hosts": "all",
            "become": True,
            "become_user": "root",
            "tasks": [],
        }
        play = load_play(path="pb.yml", index=0, play_block_dict=play_dict, yaml_lines="---\n")
        assert play.options.get("become") is True

    def test_play_with_pre_and_post_tasks(self) -> None:
        play_dict: YAMLDict = {
            "name": "Multi-section play",
            "hosts": "all",
            "pre_tasks": [
                {"name": "Pre task", "ansible.builtin.debug": {"msg": "pre"}},
            ],
            "tasks": [],
            "post_tasks": [
                {"name": "Post task", "ansible.builtin.debug": {"msg": "post"}},
            ],
        }
        yaml_lines = "---\n- name: Multi-section play\n  hosts: all\n  pre_tasks:\n    - name: Pre task\n      ansible.builtin.debug:\n        msg: pre\n  tasks: []\n  post_tasks:\n    - name: Post task\n      ansible.builtin.debug:\n        msg: post\n"
        play = load_play(path="pb.yml", index=0, play_block_dict=play_dict, yaml_lines=yaml_lines)
        assert isinstance(play, Play)
        assert len(play.pre_tasks) > 0
        assert len(play.post_tasks) > 0

    def test_play_with_handlers(self) -> None:
        play_dict: YAMLDict = {
            "name": "Handler play",
            "hosts": "all",
            "tasks": [],
            "handlers": [
                {"name": "restart svc", "ansible.builtin.service": {"name": "svc", "state": "restarted"}},
            ],
        }
        yaml_lines = "---\n- name: Handler play\n  hosts: all\n  tasks: []\n  handlers:\n    - name: restart svc\n      ansible.builtin.service:\n        name: svc\n        state: restarted\n"
        play = load_play(path="pb.yml", index=0, play_block_dict=play_dict, yaml_lines=yaml_lines)
        assert len(play.handlers) > 0


class TestLoadTask:
    def test_basic_task(self, tmp_path: Path) -> None:
        task_dict: dict[str, object] = {
            "name": "Install package",
            "ansible.builtin.package": {"name": "vim", "state": "present"},
        }
        tf_content = "---\n- name: Install package\n  ansible.builtin.package:\n    name: vim\n    state: present\n"
        task = load_task(
            path="tasks/main.yml",
            index=0,
            task_block_dict=task_dict,
            yaml_lines=tf_content,
        )
        assert isinstance(task, Task)
        assert task.name == "Install package"
        assert "ansible.builtin.package" in task.module

    def test_task_with_register(self) -> None:
        task_dict: dict[str, object] = {
            "name": "Run command",
            "ansible.builtin.shell": "echo hello",
            "register": "result",
        }
        yaml_lines = "---\n- name: Run command\n  ansible.builtin.shell: echo hello\n  register: result\n"
        task = load_task(path="tasks/main.yml", index=0, task_block_dict=task_dict, yaml_lines=yaml_lines)
        assert isinstance(task, Task)

    def test_task_with_loop(self) -> None:
        task_dict: dict[str, object] = {
            "name": "Loop task",
            "ansible.builtin.debug": {"msg": "{{ item }}"},
            "loop": ["a", "b", "c"],
        }
        yaml_lines = "---\n- name: Loop task\n  ansible.builtin.debug:\n    msg: '{{ item }}'\n  loop:\n    - a\n    - b\n    - c\n"
        task = load_task(path="tasks/main.yml", index=0, task_block_dict=task_dict, yaml_lines=yaml_lines)
        assert isinstance(task, Task)

    def test_task_file_not_found_raises(self) -> None:
        task_dict: dict[str, object] = {"name": "test", "ansible.builtin.debug": {"msg": "hi"}}
        with pytest.raises(ValueError, match="file not found"):
            load_task(path="nonexistent.yml", index=0, task_block_dict=task_dict)

    def test_task_with_block(self) -> None:
        task_dict: dict[str, object] = {
            "block": [
                {"name": "Inner task", "ansible.builtin.debug": {"msg": "inside block"}},
            ],
        }
        yaml_lines = "---\n- block:\n    - name: Inner task\n      ansible.builtin.debug:\n        msg: inside block\n"
        task = load_task(path="tasks/main.yml", index=0, task_block_dict=task_dict, yaml_lines=yaml_lines)
        assert isinstance(task, Task)


class TestLoadRoleInPlay:
    def test_basic_role(self) -> None:
        rip = load_roleinplay(
            name="common",
            options={},
            defined_in="pb.yml",
            role_index=0,
            play_index=0,
        )
        assert isinstance(rip, RoleInPlay)
        assert rip.name == "common"

    def test_role_with_options(self) -> None:
        rip = load_roleinplay(
            name="webserver",
            options={"port": 8080, "ssl": True},
            defined_in="pb.yml",
            role_index=1,
            play_index=0,
        )
        assert rip.name == "webserver"


class TestLoadFile:
    def test_load_with_body(self) -> None:
        f = load_file(path="vars/main.yml", body="key: value\n", read=False)
        assert isinstance(f, File)
        assert f.body == "key: value\n"

    def test_load_with_read_false(self) -> None:
        f = load_file(path="nonexistent.yml", read=False)
        assert isinstance(f, File)
        assert f.body == ""

    def test_load_from_disk(self, tmp_path: Path) -> None:
        fpath = tmp_path / "data.yml"
        fpath.write_text("key: value\n")
        f = load_file(path="data.yml", basedir=str(tmp_path))
        assert isinstance(f, File)
        assert "key: value" in f.body


class TestLoadRequirements:
    def test_load_requirements_file(self, tmp_path: Path) -> None:
        req_content = "---\ncollections:\n  - name: ansible.utils\nroles:\n  - src: geerlingguy.docker\n"
        req_file = tmp_path / "requirements.yml"
        req_file.write_text(req_content)
        result = load_requirements(str(tmp_path))
        assert isinstance(result, dict)
        assert "collections" in result

    def test_load_nonexistent_requirements(self, tmp_path: Path) -> None:
        result = load_requirements(str(tmp_path / "missing_dir"))
        assert result == {}
