"""Tests for apme_engine.engine.utils."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from apme_engine.engine.models import YAMLDict
from apme_engine.engine.utils import (
    bool_values,
    bool_values_false,
    bool_values_true,
    diff_files_data,
    equal,
    escape_local_path,
    escape_url,
    get_class_by_arg_type,
    get_collection_metadata,
    get_download_metadata,
    get_hash_of_url,
    get_lock_file_name,
    get_role_metadata,
    indent,
    install_galaxy_target,
    install_github_target,
    is_local_path,
    is_test_object,
    is_url,
    lock_file,
    parse_bool,
    recursive_copy_dict,
    remove_lock_file,
    report_to_display,
    show_all_ram_metadata,
    show_diffs,
    split_name_and_version,
    split_target_playbook_fullpath,
    split_target_taskfile_fullpath,
    unlock_file,
    version_to_num,
)


class TestGetLockFileName:
    def test_appends_lock_extension(self) -> None:
        assert get_lock_file_name("/tmp/foo.json") == "/tmp/foo.json.lock"

    def test_empty_path(self) -> None:
        assert get_lock_file_name("") == ".lock"


class TestLockUnlockRemove:
    def test_lock_file_returns_none_for_empty(self) -> None:
        assert lock_file(None) is None
        assert lock_file("") is None

    def test_lock_and_unlock(self, tmp_path: Path) -> None:
        fpath = str(tmp_path / "data.json")
        Path(fpath).write_text("{}")
        lk = lock_file(fpath)
        assert lk is not None
        assert os.path.exists(fpath + ".lock")
        unlock_file(lk)

    def test_unlock_non_filelock(self) -> None:
        unlock_file("not-a-lock")
        unlock_file(None)

    def test_remove_lock_file(self, tmp_path: Path) -> None:
        fpath = str(tmp_path / "data.json")
        Path(fpath).write_text("{}")
        lk = lock_file(fpath)
        assert lk is not None
        unlock_file(lk)
        remove_lock_file(lk)
        assert not os.path.exists(fpath + ".lock")

    def test_remove_lock_file_none(self) -> None:
        remove_lock_file(None)


class TestInstallGalaxyTarget:
    def test_basic_install(self) -> None:
        with patch("apme_engine.engine.utils.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="installed", stderr="")
            out, err = install_galaxy_target("ns.col", "collection", "/tmp/out")
        assert out == "installed"
        assert err == ""
        cmd = mock_run.call_args[0][0]
        assert "ansible-galaxy collection install ns.col" in cmd
        assert "-p /tmp/out" in cmd

    def test_with_server_and_version(self) -> None:
        with patch("apme_engine.engine.utils.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="ok", stderr="")
            install_galaxy_target(
                "ns.col", "collection", "/tmp/out", source_repository="https://galaxy.example.com", target_version="1.0"
            )
        cmd = mock_run.call_args[0][0]
        assert "--server https://galaxy.example.com" in cmd
        assert "ns.col:1.0" in cmd


class TestInstallGithubTarget:
    def test_clones_repo(self) -> None:
        with patch("apme_engine.engine.utils.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="cloned")
            result = install_github_target("https://github.com/user/repo", "/tmp/out")
        assert result == "cloned"
        cmd = mock_run.call_args[0][0]
        assert "git clone https://github.com/user/repo /tmp/out" in cmd


class TestGetDownloadMetadata:
    def test_collection_download(self) -> None:
        msg = "Downloading https://galaxy.example.com/ns-col-1.2.3.tar.gz to /tmp\nInstalling..."
        with patch("apme_engine.engine.utils.get_hash_of_url", return_value="abc123"):
            url, version, hash_val = get_download_metadata("collection", msg)
        assert url == "https://galaxy.example.com/ns-col-1.2.3.tar.gz"
        assert version == "1.2.3"
        assert hash_val == "abc123"

    def test_role_download(self) -> None:
        msg = "- downloading role from https://galaxy.example.com/role-2.0.0.tar.gz"
        with patch("apme_engine.engine.utils.get_hash_of_url", return_value="def456"):
            url, version, hash_val = get_download_metadata("role", msg)
        assert url == "https://galaxy.example.com/role-2.0.0.tar.gz"
        assert version == "role-2.0.0"
        assert hash_val == "def456"

    def test_no_download_url(self) -> None:
        url, version, hash_val = get_download_metadata("collection", "no download here")
        assert url == ""
        assert version == ""
        assert hash_val == ""


class TestGetCollectionMetadata:
    def test_nonexistent_path(self) -> None:
        assert get_collection_metadata("/nonexistent/path") is None

    def test_reads_manifest(self, tmp_path: Path) -> None:
        manifest = {"collection_info": {"name": "testcol", "namespace": "testns"}}
        (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest))
        result = get_collection_metadata(str(tmp_path))
        assert result == manifest

    def test_no_manifest(self, tmp_path: Path) -> None:
        result = get_collection_metadata(str(tmp_path))
        assert result is None


class TestGetRoleMetadata:
    def test_nonexistent_path(self) -> None:
        assert get_role_metadata("/nonexistent/path") is None

    def test_reads_meta_main(self, tmp_path: Path) -> None:
        meta_dir = tmp_path / "meta"
        meta_dir.mkdir()
        (meta_dir / "main.yml").write_text("galaxy_info:\n  author: tester\ndependencies: []\n")
        result = get_role_metadata(str(tmp_path))
        assert result is not None
        galaxy_info = result.get("galaxy_info")
        assert isinstance(galaxy_info, dict) and galaxy_info.get("author") == "tester"

    def test_no_meta_dir(self, tmp_path: Path) -> None:
        result = get_role_metadata(str(tmp_path))
        assert result is None


class TestEscapeUrl:
    def test_basic(self) -> None:
        assert escape_url("https://example.com/path/to/file") == "https__example.com_path_to_file"

    def test_with_query(self) -> None:
        assert escape_url("https://example.com/file?key=val") == "https__example.com_file"


class TestEscapeLocalPath:
    def test_replaces_slashes(self) -> None:
        assert escape_local_path("/home/user/project") == "__home__user__project"


class TestGetHashOfUrl:
    def test_hashes_response(self) -> None:
        mock_response = MagicMock()
        mock_response.content = b"test content"
        with patch("apme_engine.engine.utils.httpx.get", return_value=mock_response):
            result = get_hash_of_url("https://example.com/file.tar.gz")
        assert len(result) == 64  # SHA-256 hex digest


class TestSplitNameAndVersion:
    def test_with_version(self) -> None:
        assert split_name_and_version("ns.col:1.0.0") == ("ns.col", "1.0.0")

    def test_without_version(self) -> None:
        assert split_name_and_version("ns.col") == ("ns.col", "")

    def test_empty(self) -> None:
        assert split_name_and_version("") == ("", "")


class TestSplitTargetPlaybookFullpath:
    def test_with_playbooks_dir(self) -> None:
        basedir, playbook = split_target_playbook_fullpath("/home/user/project/playbooks/site.yml")
        assert basedir == "/home/user/project"
        assert playbook == "playbooks/site.yml"

    def test_without_playbooks_dir(self) -> None:
        basedir, playbook = split_target_playbook_fullpath("/home/user/project/site.yml")
        assert basedir == "/home/user/project"
        assert playbook == "site.yml"


class TestSplitTargetTaskfileFullpath:
    def test_with_roles_dir(self) -> None:
        basedir, taskfile = split_target_taskfile_fullpath("/project/roles/myrole/tasks/main.yml")
        assert basedir == "/project"
        assert taskfile == "roles/myrole/tasks/main.yml"

    def test_without_roles_dir(self) -> None:
        basedir, taskfile = split_target_taskfile_fullpath("/project/tasks/main.yml")
        assert basedir == "/project/tasks"
        assert taskfile == "main.yml"

    def test_empty_result(self) -> None:
        basedir, taskfile = split_target_taskfile_fullpath("/onlydir")
        assert basedir == "/"
        assert taskfile == "onlydir"


class TestVersionToNum:
    def test_simple_version(self) -> None:
        assert version_to_num("1.2.3") == pytest.approx(1.002003)

    def test_two_parts(self) -> None:
        assert version_to_num("2.10") == pytest.approx(2.01)

    def test_single_part(self) -> None:
        assert version_to_num("5") == pytest.approx(5.0)

    def test_unknown(self) -> None:
        assert version_to_num("unknown") == 0.0

    def test_with_prerelease(self) -> None:
        assert version_to_num("1.2.3-beta1") == pytest.approx(1.002003)


class TestIsUrl:
    def test_http(self) -> None:
        assert is_url("https://example.com") is True

    def test_not_url(self) -> None:
        assert is_url("some/path") is False

    def test_git_url(self) -> None:
        assert is_url("git://github.com/repo") is True


class TestIsLocalPath:
    def test_url_returns_false(self) -> None:
        assert is_local_path("https://example.com") is False

    def test_path_with_slash(self) -> None:
        assert is_local_path("/some/path") is True

    def test_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.yml"
        f.write_text("test")
        assert is_local_path(str(f)) is True


class TestIndent:
    def test_basic_indent(self) -> None:
        result = indent("line1\nline2", level=4)
        assert result == "    line1\n    line2"

    def test_skips_empty_lines(self) -> None:
        result = indent("line1\n   \nline2", level=2)
        assert result == "  line1\n  line2"

    def test_zero_indent(self) -> None:
        result = indent("line1\nline2", level=0)
        assert result == "line1\nline2"


class TestReportToDisplay:
    def test_no_content(self) -> None:
        report: dict[str, object] = {"summary": {"playbooks": {"total": 0}, "roles": {"total": 0}}}
        result = report_to_display(report)
        assert "No playbooks and roles found" in result

    def test_with_playbooks(self) -> None:
        report: dict[str, object] = {
            "summary": {"playbooks": {"total": 3}, "roles": {"total": 2}},
            "details": [],
        }
        result = report_to_display(report)
        assert "3 playbooks" in result
        assert "2 roles" in result

    def test_with_details(self) -> None:
        report: dict[str, object] = {
            "summary": {"playbooks": {"total": 1}, "roles": {"total": 0}},
            "details": [{"results": [{"output": "Something found"}]}],
        }
        result = report_to_display(report)
        assert "Something found" in result


class TestShowAllRamMetadata:
    def test_prints_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        meta = [{"name": "ns.col", "version": "1.0", "hash": "abc"}]
        show_all_ram_metadata(meta)
        out = capsys.readouterr().out
        assert "ns.col" in out
        assert "1.0" in out


class TestDiffFilesData:
    def test_created(self) -> None:
        files1: dict[str, object] = {"files": [{"ftype": "file", "name": "new.yml", "chksum_sha256": "aaa"}]}
        files2: dict[str, object] = {"files": []}
        diffs = diff_files_data(files1, files2)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "created"

    def test_deleted(self) -> None:
        files1: dict[str, object] = {"files": []}
        files2: dict[str, object] = {"files": [{"ftype": "file", "name": "old.yml", "chksum_sha256": "bbb"}]}
        diffs = diff_files_data(files1, files2)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "deleted"

    def test_updated(self) -> None:
        files1: dict[str, object] = {"files": [{"ftype": "file", "name": "changed.yml", "chksum_sha256": "new_hash"}]}
        files2: dict[str, object] = {"files": [{"ftype": "file", "name": "changed.yml", "chksum_sha256": "old_hash"}]}
        diffs = diff_files_data(files1, files2)
        assert len(diffs) == 1
        assert diffs[0]["type"] == "updated"

    def test_no_diff(self) -> None:
        files1: dict[str, object] = {"files": [{"ftype": "file", "name": "same.yml", "chksum_sha256": "aaa"}]}
        files2: dict[str, object] = {"files": [{"ftype": "file", "name": "same.yml", "chksum_sha256": "aaa"}]}
        diffs = diff_files_data(files1, files2)
        assert len(diffs) == 0

    def test_non_file_ftype_ignored(self) -> None:
        files1: dict[str, object] = {"files": [{"ftype": "dir", "name": "somedir", "chksum_sha256": ""}]}
        files2: dict[str, object] = {"files": []}
        diffs = diff_files_data(files1, files2)
        assert len(diffs) == 0

    def test_non_list_files(self) -> None:
        diffs = diff_files_data({"files": "bad"}, {"files": None})
        assert diffs == []


class TestShowDiffs:
    def test_prints_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        diffs = [{"filepath": "new.yml", "type": "created"}]
        show_diffs(diffs)
        out = capsys.readouterr().out
        assert "new.yml" in out
        assert "created" in out


class TestGetClassByArgType:
    @pytest.mark.parametrize(
        ("arg_type", "expected"),
        [
            ("str", str),
            ("list", list),
            ("dict", dict),
            ("bool", bool),
            ("int", int),
            ("float", float),
            ("path", str),
            ("raw", object),
            ("jsonarg", str),
            ("json", str),
            ("bytes", str),
            ("bits", str),
        ],
    )  # type: ignore[untyped-decorator]
    def test_known_types(self, arg_type: str, expected: type[object]) -> None:
        assert get_class_by_arg_type(arg_type) is expected

    def test_unknown_type(self) -> None:
        assert get_class_by_arg_type("custom") is None

    def test_non_string(self) -> None:
        assert get_class_by_arg_type(123) is None  # type: ignore[arg-type]


class TestEqual:
    def test_equal_dicts(self) -> None:
        assert equal({"a": 1, "b": 2}, {"a": 1, "b": 2}) is True

    def test_unequal_dicts(self) -> None:
        assert equal({"a": 1}, {"a": 2}) is False

    def test_equal_lists(self) -> None:
        assert equal([1, 2, 3], [1, 2, 3]) is True

    def test_unequal_lists_length(self) -> None:
        assert equal([1, 2], [1, 2, 3]) is False

    def test_unequal_lists_values(self) -> None:
        assert equal([1, 2], [1, 3]) is False

    def test_different_types(self) -> None:
        assert equal(1, "1") is False

    def test_nested_dicts(self) -> None:
        assert equal({"a": {"b": [1]}}, {"a": {"b": [1]}}) is True

    def test_objects_with_dict(self) -> None:
        class Obj:
            def __init__(self, x: int) -> None:
                self.x = x

        assert equal(Obj(1), Obj(1)) is True
        assert equal(Obj(1), Obj(2)) is False

    def test_primitives(self) -> None:
        assert equal(42, 42) is True
        assert equal(42, 43) is False
        assert equal("a", "a") is True


class TestRecursiveCopyDict:
    def test_shallow_copy(self) -> None:
        src: YAMLDict = {"a": 1, "b": "hello"}
        dst: YAMLDict = {}
        recursive_copy_dict(src, dst)
        assert dst == {"a": 1, "b": "hello"}

    def test_nested_copy(self) -> None:
        src: YAMLDict = {"a": {"b": {"c": 42}}}
        dst: YAMLDict = {}
        recursive_copy_dict(src, dst)
        assert dst == {"a": {"b": {"c": 42}}}
        inner: YAMLDict = cast(YAMLDict, src["a"])
        inner_b: YAMLDict = cast(YAMLDict, inner["b"])
        inner_b["c"] = 99
        dst_a: YAMLDict = cast(YAMLDict, dst["a"])
        dst_b: YAMLDict = cast(YAMLDict, dst_a["b"])
        assert dst_b["c"] == 42

    def test_non_dict_src_raises(self) -> None:
        with pytest.raises(ValueError, match="only dict"):
            recursive_copy_dict("not a dict", {})  # type: ignore[arg-type]

    def test_non_dict_dst_raises(self) -> None:
        with pytest.raises(ValueError, match="only dict"):
            recursive_copy_dict({}, "not a dict")  # type: ignore[arg-type]


class TestIsTestObject:
    def test_integration(self) -> None:
        assert is_test_object("tests/integration/foo.yml") is True

    def test_molecule(self) -> None:
        assert is_test_object("molecule/default/converge.yml") is True

    def test_regular_path(self) -> None:
        assert is_test_object("playbooks/site.yml") is False


class TestParseBool:
    @pytest.mark.parametrize("value", ["y", "yes", "on", "1", "true", "t", True, 1, 1.0])  # type: ignore[untyped-decorator]
    def test_truthy(self, value: object) -> None:
        assert parse_bool(value) is True

    @pytest.mark.parametrize("value", ["n", "no", "off", "0", "false", "f", False, 0, 0.0])  # type: ignore[untyped-decorator]
    def test_falsy(self, value: object) -> None:
        assert parse_bool(value) is False

    def test_invalid_raises(self) -> None:
        with pytest.raises(TypeError, match="failed to parse"):
            parse_bool("maybe")

    def test_bytes_true(self) -> None:
        assert parse_bool(b"yes") is True

    def test_bytes_false(self) -> None:
        assert parse_bool(b"no") is False

    def test_case_insensitive(self) -> None:
        assert parse_bool("YES") is True
        assert parse_bool("FALSE") is False

    def test_whitespace_stripped(self) -> None:
        assert parse_bool("  true  ") is True


class TestBoolConstants:
    def test_true_values(self) -> None:
        assert True in bool_values_true
        assert "yes" in bool_values_true

    def test_false_values(self) -> None:
        assert False in bool_values_false
        assert "no" in bool_values_false

    def test_union(self) -> None:
        assert bool_values == bool_values_true | bool_values_false


class TestGetDocumentationInModuleFile:
    def test_extracts_doc(self, tmp_path: Path) -> None:
        from apme_engine.engine.utils import get_documentation_in_module_file

        module = tmp_path / "mymod.py"
        module.write_text('DOCUMENTATION = """\nmodule: mymod\nshort_description: test\n"""\n')
        doc = get_documentation_in_module_file(str(module))
        assert "module: mymod" in doc

    def test_empty_path(self) -> None:
        from apme_engine.engine.utils import get_documentation_in_module_file

        assert get_documentation_in_module_file("") == ""

    def test_nonexistent(self) -> None:
        from apme_engine.engine.utils import get_documentation_in_module_file

        assert get_documentation_in_module_file("/nonexistent/file.py") == ""
