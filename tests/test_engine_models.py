"""Tests for apme_engine.engine.models."""

from __future__ import annotations

import pytest

from apme_engine.engine.models import (
    ActionGroupMetadata,
    Annotation,
    AnnotationCondition,
    Arguments,
    ArgumentsType,
    AttributeCondition,
    BecomeInfo,
    CallObject,
    Collection,
    CommandExecDetail,
    DefaultRiskType,
    File,
    FileChangeDetail,
    FunctionCondition,
    JSONSerializable,
    KeyConfigChangeDetail,
    Load,
    LoadType,
    Location,
    LocationType,
    Module,
    ModuleArgument,
    NetworkTransferDetail,
    Object,
    ObjectList,
    PackageInstallDetail,
    Play,
    Playbook,
    PlaybookFormatError,
    Resolvable,
    RiskAnnotation,
    RiskAnnotationList,
    Role,
    RoleMetadata,
    Rule,
    RuleMetadata,
    RuleResult,
    RunTarget,
    RunTargetList,
    Severity,
    SpecMutation,
    Task,
    TaskCall,
    TaskCallsInTree,
    TaskFile,
    TaskFileMetadata,
    TaskFormatError,
    Variable,
    VariableAnnotation,
    VariableDict,
    VariablePrecedence,
    VariableType,
    ViolationDict,
    YAMLDict,
    YAMLScalar,
    YAMLValue,
    _convert_to_bool,
    filter_annotations_by_type,
    get_annotations_after,
    search_risk_annotations,
)


class TestExceptions:
    def test_playbook_format_error(self) -> None:
        with pytest.raises(PlaybookFormatError):
            raise PlaybookFormatError("bad playbook")

    def test_task_format_error(self) -> None:
        with pytest.raises(TaskFormatError):
            raise TaskFormatError("bad task")


class TestJSONSerializable:
    def test_dump_returns_json(self) -> None:
        obj = Load(target_name="test", target_type="collection")
        result = obj.dump()
        assert "test" in result
        assert "collection" in result

    def test_to_json_from_json_round_trip(self) -> None:
        obj = Load(target_name="myproject", target_type="project", path="/some/path")
        json_str = obj.to_json()
        restored = Load.from_json(json_str)
        assert restored.target_name == "myproject"
        assert restored.path == "/some/path"


class TestLoadType:
    def test_constants(self) -> None:
        assert LoadType.PROJECT == "project"
        assert LoadType.COLLECTION == "collection"
        assert LoadType.ROLE == "role"
        assert LoadType.PLAYBOOK == "playbook"
        assert LoadType.TASKFILE == "taskfile"
        assert LoadType.UNKNOWN == "unknown"


class TestLoad:
    def test_defaults(self) -> None:
        ld = Load()
        assert ld.target_name == ""
        assert ld.target_type == ""
        assert ld.playbook_only is False
        assert ld.roles == []

    def test_with_fields(self) -> None:
        ld = Load(target_name="ns.col", target_type="collection", path="/path")
        assert ld.target_name == "ns.col"
        assert ld.path == "/path"


class TestObject:
    def test_defaults(self) -> None:
        obj = Object()
        assert obj.type == ""
        assert obj.key == ""

    def test_with_values(self) -> None:
        obj = Object(type="module", key="module ns.col.mymod")
        assert obj.type == "module"


class TestObjectList:
    def test_add_and_find(self) -> None:
        ol = ObjectList()
        obj = Object(type="module", key="mod1")
        ol.add(obj)
        assert ol.find_by_key("mod1") is obj
        assert ol.find_by_key("nonexistent") is None

    def test_contains(self) -> None:
        ol = ObjectList()
        obj = Object(type="role", key="role1")
        ol.add(obj)
        assert ol.contains(key="role1") is True
        assert ol.contains(key="role2") is False
        assert ol.contains(obj=obj) is True

    def test_find_by_type(self) -> None:
        ol = ObjectList()
        ol.add(Object(type="module", key="m1"))
        ol.add(Object(type="role", key="r1"))
        ol.add(Object(type="module", key="m2"))
        modules = ol.find_by_type("module")
        assert len(modules) == 2

    def test_find_by_attr(self) -> None:
        ol = ObjectList()
        ol.add(Object(type="module", key="m1"))
        ol.add(Object(type="role", key="r1"))
        found = ol.find_by_attr("type", "role")
        assert len(found) == 1

    def test_merge(self) -> None:
        ol1 = ObjectList()
        ol1.add(Object(type="a", key="k1"))
        ol2 = ObjectList()
        ol2.add(Object(type="b", key="k2"))
        ol1.merge(ol2)
        assert len(ol1.items) == 2
        assert ol1.find_by_key("k2") is not None

    def test_merge_non_objectlist_raises(self) -> None:
        ol = ObjectList()
        with pytest.raises(ValueError, match="ObjectList"):
            ol.merge("bad")  # type: ignore[arg-type]

    def test_resolver_targets(self) -> None:
        ol = ObjectList()
        ol.add(Object(key="k1"))
        assert ol.resolver_targets == ol.items

    def test_to_json_and_from_json(self) -> None:
        ol = ObjectList()
        ol.add(Object(type="test", key="key1"))
        json_str = ol.to_json()
        restored = ObjectList.from_json(json_str)
        assert len(restored.items) == 1

    def test_to_one_line_json(self) -> None:
        ol = ObjectList()
        ol.add(Object(type="test", key="key1"))
        result = ol.to_one_line_json()
        assert "key1" in result


class TestCallObject:
    def test_defaults(self) -> None:
        co = CallObject()
        assert co.depth == -1
        assert co.node_id == ""

    def test_from_spec_without_caller(self) -> None:
        spec = Object(type="module", key="module mod1")
        co = CallObject.from_spec(spec, caller=None, index=0)
        assert co.spec is spec
        assert co.depth == 0
        assert co.node_id == "0"

    def test_from_spec_with_caller(self) -> None:
        spec = Object(type="module", key="module mod1")
        caller = CallObject(key="parent_key", depth=1, node_id="0.1")
        co = CallObject.from_spec(spec, caller=caller, index=2)
        assert co.depth == 2
        assert co.node_id == "0.1.2"
        assert co.called_from == "parent_key"


class TestRunTarget:
    def test_file_info(self) -> None:
        spec = Object(type="task")
        spec.defined_in = "tasks/main.yml"  # type: ignore[attr-defined]
        rt = RunTarget(spec=spec)
        file, lines = rt.file_info()
        assert file == "tasks/main.yml"
        assert lines is None

    def test_has_annotation_returns_false(self) -> None:
        rt = RunTarget()
        cond = AnnotationCondition()
        assert rt.has_annotation_by_condition(cond) is False

    def test_get_annotation_returns_none(self) -> None:
        rt = RunTarget()
        cond = AnnotationCondition()
        assert rt.get_annotation_by_condition(cond) is None


class TestRunTargetList:
    def test_len_and_getitem(self) -> None:
        items = [RunTarget(key="rt1"), RunTarget(key="rt2")]
        rtl = RunTargetList(items=items)
        assert len(rtl) == 2
        assert rtl[0].key == "rt1"

    def test_iteration(self) -> None:
        items = [RunTarget(key="a"), RunTarget(key="b")]
        rtl = RunTargetList(items=items)
        keys = [rt.key for rt in rtl]
        assert keys == ["a", "b"]


class TestFile:
    def test_defaults(self) -> None:
        f = File()
        assert f.type == "file"
        assert f.name == ""

    def test_resolver_targets(self) -> None:
        f = File()
        assert f.resolver_targets is None

    def test_children_to_key(self) -> None:
        f = File(name="test.yml")
        assert f.children_to_key() is f


class TestModuleArgument:
    def test_available_keys_no_aliases(self) -> None:
        arg = ModuleArgument(name="src")
        assert arg.available_keys() == ["src"]

    def test_available_keys_with_aliases(self) -> None:
        arg = ModuleArgument(name="src", aliases=["source", "origin"])
        assert arg.available_keys() == ["src", "source", "origin"]


class TestModule:
    def test_defaults(self) -> None:
        m = Module()
        assert m.type == "module"
        assert m.builtin is False

    def test_resolver_targets(self) -> None:
        m = Module()
        assert m.resolver_targets is None


class TestVariablePrecedence:
    def test_str_repr(self) -> None:
        vp = VariablePrecedence(name="task_vars", order=17)
        assert str(vp) == "task_vars"
        assert repr(vp) == "task_vars"

    def test_ordering(self) -> None:
        low = VariablePrecedence(name="low", order=2)
        high = VariablePrecedence(name="high", order=17)
        assert low < high
        assert low <= high
        assert high > low
        assert high >= low
        assert low != high

    def test_equality(self) -> None:
        a = VariablePrecedence(name="a", order=5)
        b = VariablePrecedence(name="b", order=5)
        assert a == b

    def test_not_equal_to_non_vp(self) -> None:
        vp = VariablePrecedence(name="x", order=1)
        assert vp.__eq__("other") is NotImplemented
        assert vp.__lt__("other") is NotImplemented
        assert vp.__le__("other") is NotImplemented


class TestVariableType:
    def test_ordering(self) -> None:
        assert VariableType.RoleDefaults < VariableType.ExtraVars
        assert VariableType.LoopVars > VariableType.ExtraVars

    def test_unknown_has_negative_order(self) -> None:
        assert VariableType.Unknown.order < 0


class TestVariable:
    def test_is_mutable_default(self) -> None:
        v = Variable(name="foo")
        assert v.is_mutable is True

    def test_is_mutable_with_loop_vars(self) -> None:
        v = Variable(name="item", type=VariableType.LoopVars)
        assert v.is_mutable is False

    def test_is_mutable_with_task_vars(self) -> None:
        v = Variable(name="x", type=VariableType.TaskVars)
        assert v.is_mutable is True


class TestArguments:
    def test_defaults(self) -> None:
        args = Arguments()
        assert args.type == ArgumentsType.SIMPLE
        assert args.raw is None

    def test_get_empty_key(self) -> None:
        args = Arguments(raw="some value")
        result = args.get("")
        assert result is not None
        assert result.raw == "some value"

    def test_get_returns_none_for_empty_raw(self) -> None:
        args = Arguments(raw=None)
        assert args.get() is None

    def test_get_dict_key(self) -> None:
        args = Arguments(raw={"src": "/tmp/file", "dest": "/opt/file"})
        result = args.get("src")
        assert result is not None
        assert result.raw == "/tmp/file"

    def test_get_missing_dict_key(self) -> None:
        args = Arguments(raw={"src": "/tmp/file"})
        result = args.get("missing")
        assert result is None

    def test_get_list_type(self) -> None:
        args = Arguments(raw=["a", "b", "c"])
        result = args.get("")
        assert result is not None
        assert result.type == ArgumentsType.LIST

    def test_get_with_variables(self) -> None:
        var = Variable(name="my_var", type=VariableType.TaskVars)
        args = Arguments(raw="{{ my_var }}/path", vars=[var])
        result = args.get("")
        assert result is not None
        assert len(result.vars) == 1
        assert result.is_mutable is True


class TestLocation:
    def test_defaults(self) -> None:
        loc = Location()
        assert loc.is_empty is True

    def test_with_values(self) -> None:
        loc = Location(type=LocationType.FILE, value="/tmp/file")
        assert loc.is_empty is False
        assert loc.is_mutable is False

    def test_is_mutable_with_vars(self) -> None:
        loc = Location(type=LocationType.FILE, value="{{ path }}", vars=[Variable(name="path")])
        assert loc.is_mutable is True

    def test_post_init_from_args(self) -> None:
        args = Arguments(raw="/tmp/file", vars=[])
        loc = Location(_args=args)
        assert loc.value == "/tmp/file"

    def test_contains(self) -> None:
        parent = Location(value="/opt")
        child = Location(value="/opt/myapp/data")
        assert parent.contains(child) is True
        assert child.contains(parent) is False

    def test_is_inside(self) -> None:
        parent = Location(value="/opt")
        child = Location(value="/opt/myapp")
        assert child.is_inside(parent) is True

    def test_contains_any(self) -> None:
        parent = Location(value="/opt")
        targets = [Location(value="/opt/a"), Location(value="/tmp/b")]
        assert parent.contains_any(targets) is True

    def test_contains_all(self) -> None:
        parent = Location(value="/opt")
        targets = [Location(value="/opt/a"), Location(value="/opt/b")]
        assert parent.contains_all(targets) is True
        targets2 = [Location(value="/opt/a"), Location(value="/tmp/b")]
        assert parent.contains_all(targets2) is False

    def test_contains_list_any_mode(self) -> None:
        parent = Location(value="/opt")
        targets = [Location(value="/opt/a"), Location(value="/tmp/b")]
        assert parent.contains(targets, any_mode=True, all_mode=False) is True

    def test_contains_list_all_mode(self) -> None:
        parent = Location(value="/opt")
        targets = [Location(value="/opt/a"), Location(value="/opt/b")]
        assert parent.contains(targets, any_mode=False, all_mode=True) is True

    def test_contains_bad_mode_raises(self) -> None:
        parent = Location(value="/opt")
        with pytest.raises(ValueError, match="any.*all"):
            parent.contains([Location(value="/opt/a")], any_mode=False, all_mode=False)

    def test_contains_non_location_raises(self) -> None:
        loc = Location(value="/opt")
        with pytest.raises(ValueError):
            loc.contains("not-a-location")  # type: ignore[arg-type]


class TestNetworkTransferDetail:
    def test_post_init_with_args(self) -> None:
        src_args = Arguments(raw="/tmp/file", is_mutable=True)
        dest_args = Arguments(raw="/opt/dest")
        detail = NetworkTransferDetail(_src_arg=src_args, _dest_arg=dest_args)
        assert detail.src is not None
        assert detail.src.value == "/tmp/file"
        assert detail.is_mutable_src is True
        assert detail.dest is not None
        assert detail.dest.value == "/opt/dest"


class TestFileChangeDetail:
    def test_insecure_permissions(self) -> None:
        detail = FileChangeDetail(_mode_arg=Arguments(raw="0777"))
        assert detail.is_insecure_permissions is True

    def test_deletion(self) -> None:
        detail = FileChangeDetail(_state_arg=Arguments(raw="absent"))
        assert detail.is_deletion is True

    def test_unsafe_write(self) -> None:
        detail = FileChangeDetail(_unsafe_write_arg=Arguments(raw=True))
        assert detail.is_unsafe_write is True


class TestCommandExecDetail:
    def test_basic_command(self) -> None:
        detail = CommandExecDetail(command=Arguments(raw="echo hello"))
        assert len(detail.exec_files) == 1
        assert detail.exec_files[0].value == "echo"

    def test_no_command(self) -> None:
        detail = CommandExecDetail(command=None)
        assert detail.exec_files == []

    def test_non_exec_program(self) -> None:
        detail = CommandExecDetail(command=Arguments(raw="tar xzf archive.tar.gz"))
        assert detail.exec_files == []


class TestConvertToBool:
    def test_true_values(self) -> None:
        assert _convert_to_bool(True) is True
        assert _convert_to_bool("true") is True
        assert _convert_to_bool("True") is True
        assert _convert_to_bool("yes") is True

    def test_false_values(self) -> None:
        assert _convert_to_bool(False) is False
        assert _convert_to_bool("false") is False

    def test_none_for_non_bool(self) -> None:
        assert _convert_to_bool(42) is None
        assert _convert_to_bool(None) is None


class TestAnnotation:
    def test_defaults(self) -> None:
        anno = Annotation()
        assert anno.key == ""
        assert anno.value is None

    def test_with_values(self) -> None:
        anno = Annotation(key="test_key", value="test_value", rule_id="rule1")
        assert anno.rule_id == "rule1"


class TestVariableAnnotation:
    def test_type(self) -> None:
        va = VariableAnnotation()
        assert va.type == "variable_annotation"


class TestRiskAnnotation:
    def test_init_factory(self) -> None:
        detail = FileChangeDetail(
            _path_arg=Arguments(raw="/tmp/test"),
            _state_arg=Arguments(raw="present"),
        )
        anno = RiskAnnotation.init(DefaultRiskType.FILE_CHANGE, detail)
        assert anno.risk_type == DefaultRiskType.FILE_CHANGE
        assert anno.path is not None
        assert anno.path.value == "/tmp/test"

    def test_equal_to(self) -> None:
        a = RiskAnnotation(risk_type="cmd_exec")
        b = RiskAnnotation(risk_type="cmd_exec")
        assert a.equal_to(b) is True

    def test_not_equal_different_risk_type(self) -> None:
        a = RiskAnnotation(risk_type="cmd_exec")
        b = RiskAnnotation(risk_type="file_change")
        assert a.equal_to(b) is False


class TestAnnotationCondition:
    def test_fluent_api(self) -> None:
        cond = AnnotationCondition()
        result = cond.risk_type("cmd_exec").attr("key1", "val1")
        assert result is cond
        assert cond.type == "cmd_exec"
        assert cond.attr_conditions == [("key1", "val1")]


class TestAttributeCondition:
    def test_check_match(self) -> None:
        anno = RiskAnnotation(risk_type="cmd_exec")
        anno.is_deletion = True  # type: ignore[attr-defined]
        cond = AttributeCondition(attr="is_deletion", result=True)
        assert cond.check(anno) is True

    def test_check_no_match(self) -> None:
        anno = RiskAnnotation(risk_type="cmd_exec")
        cond = AttributeCondition(attr="nonexistent", result=True)
        assert cond.check(anno) is False


class TestFunctionCondition:
    def test_check_with_func(self) -> None:
        def my_checker(anno: RiskAnnotation, **kwargs: YAMLValue) -> bool:
            return anno.risk_type == "cmd_exec"

        cond = FunctionCondition(func=my_checker, result=True)
        anno = RiskAnnotation(risk_type="cmd_exec")
        assert cond.check(anno) is True

    def test_check_no_func(self) -> None:
        cond = FunctionCondition()
        anno = RiskAnnotation()
        assert cond.check(anno) is False


class TestRiskAnnotationList:
    def _make_list(self) -> RiskAnnotationList:
        return RiskAnnotationList(
            items=[
                RiskAnnotation(risk_type="cmd_exec", key="a"),
                RiskAnnotation(risk_type="file_change", key="b"),
                RiskAnnotation(risk_type="cmd_exec", key="c"),
            ]
        )

    def test_iteration(self) -> None:
        ral = self._make_list()
        types = [a.risk_type for a in ral]
        assert types == ["cmd_exec", "file_change", "cmd_exec"]

    def test_filter(self) -> None:
        ral = self._make_list()
        filtered = ral.filter(risk_type="cmd_exec")
        assert len(filtered.items) == 2

    def test_after(self) -> None:
        ral = self._make_list()
        target = ral.items[1]
        after = ral.after(target)
        assert len(after.items) == 2
        assert after.items[0].key == "b"

    def test_after_not_found_raises(self) -> None:
        ral = self._make_list()
        missing = RiskAnnotation(risk_type="unknown", key="z")
        with pytest.raises(ValueError, match="not found"):
            ral.after(missing)

    def test_find(self) -> None:
        ral = self._make_list()
        cond = AttributeCondition(attr="risk_type", result="cmd_exec")
        found = ral.find(condition=cond)
        assert len(found.items) == 2


class TestBecomeInfo:
    def test_from_options_with_become(self) -> None:
        options: YAMLDict = {"become": True, "become_user": "root", "become_method": "sudo"}
        info = BecomeInfo.from_options(options)
        assert info is not None
        assert info.enabled is True
        assert info.user == "root"
        assert info.method == "sudo"

    def test_from_options_without_become(self) -> None:
        options: YAMLDict = {"hosts": "all"}
        assert BecomeInfo.from_options(options) is None

    def test_from_options_become_false(self) -> None:
        options: YAMLDict = {"become": False}
        info = BecomeInfo.from_options(options)
        assert info is not None
        assert info.enabled is False


class TestRuleResult:
    def test_verdict_normalization(self) -> None:
        rr = RuleResult(verdict=1)  # type: ignore[arg-type]
        assert rr.verdict is True
        rr2 = RuleResult(verdict=0)  # type: ignore[arg-type]
        assert rr2.verdict is False

    def test_set_value_and_get_detail(self) -> None:
        rr = RuleResult(detail={"key1": "val1"})
        rr.set_value("key2", "val2")
        detail = rr.get_detail()
        assert detail is not None
        assert detail["key2"] == "val2"

    def test_set_value_no_detail(self) -> None:
        rr = RuleResult()
        rr.set_value("key", "val")
        assert rr.detail is None


class TestRuleMetadata:
    def test_defaults(self) -> None:
        rm = RuleMetadata()
        assert rm.rule_id == ""
        assert rm.tags == ()


class TestSpecMutation:
    def test_defaults(self) -> None:
        sm = SpecMutation()
        assert sm.key is None
        assert sm.changes == []


class TestTaskCallsInTree:
    def test_defaults(self) -> None:
        tct = TaskCallsInTree()
        assert tct.root_key == ""
        assert tct.taskcalls == []


class TestCollection:
    def test_defaults(self) -> None:
        c = Collection()
        assert c.type == "collection"

    def test_fields(self) -> None:
        c = Collection(name="testcol", path="/path/to/col")
        assert c.name == "testcol"
        assert c.path == "/path/to/col"
        assert c.playbooks == []
        assert c.modules == []


class TestTask:
    def test_defaults(self) -> None:
        t = Task()
        assert t.type == "task"
        assert t.module == ""
        assert t.index == -1


class TestRoleMetadataModel:
    def test_from_dict(self) -> None:
        d: YAMLDict = {"fqcn": "ns.col.role", "name": "role", "type": "role", "version": "1.0", "hash": "abc"}
        rm = RoleMetadata.from_dict(d)
        assert rm.fqcn == "ns.col.role"
        assert rm.version == "1.0"

    def test_equality(self) -> None:
        a = RoleMetadata(fqcn="ns.col.r", name="r", type="role", version="1", hash="a")
        b = RoleMetadata(fqcn="ns.col.r", name="r", type="role", version="1", hash="a")
        assert a == b

    def test_inequality_with_non_role(self) -> None:
        rm = RoleMetadata()
        assert rm.__eq__("not a role") is False


class TestTaskFileMetadata:
    def test_from_dict(self) -> None:
        d: YAMLDict = {"key": "k1", "type": "taskfile", "name": "main.yml", "version": "1.0", "hash": "x"}
        tfm = TaskFileMetadata.from_dict(d)
        assert tfm.key == "k1"
        assert tfm.name == "main.yml"

    def test_equality(self) -> None:
        a = TaskFileMetadata(key="k", type="tf", name="n", version="v", hash="h")
        b = TaskFileMetadata(key="k", type="tf", name="n", version="v", hash="h")
        assert a == b

    def test_inequality_with_non_tfm(self) -> None:
        tfm = TaskFileMetadata()
        assert tfm.__eq__("not a tfm") is False


class TestActionGroupMetadata:
    def test_from_action_group(self) -> None:
        mods = [Module(name="mod1")]
        meta: YAMLDict = {"type": "collection", "name": "ns.col", "version": "1.0", "hash": "abc"}
        agm = ActionGroupMetadata.from_action_group("mygroup", mods, meta)
        assert agm is not None
        assert agm.group_name == "mygroup"
        assert agm.name == "ns.col"

    def test_from_action_group_empty_name(self) -> None:
        assert ActionGroupMetadata.from_action_group("", [Module()], {}) is None

    def test_from_action_group_empty_modules(self) -> None:
        assert ActionGroupMetadata.from_action_group("grp", [], {}) is None

    def test_from_dict(self) -> None:
        d: YAMLDict = {
            "group_name": "g",
            "group_modules": [],
            "type": "t",
            "name": "n",
            "version": "v",
            "hash": "h",
        }
        agm = ActionGroupMetadata.from_dict(d)
        assert agm.group_name == "g"

    def test_equality(self) -> None:
        a = ActionGroupMetadata(group_name="g", name="n", type="t", version="v", hash="h")
        b = ActionGroupMetadata(group_name="g", name="n", type="t", version="v", hash="h")
        assert a == b

    def test_inequality_with_non_agm(self) -> None:
        agm = ActionGroupMetadata()
        assert agm.__eq__("not an agm") is False


class TestSeverity:
    def test_levels(self) -> None:
        assert Severity.VERY_HIGH == "very_high"
        assert Severity.HIGH == "high"
        assert Severity.MEDIUM == "medium"
        assert Severity.LOW == "low"
        assert Severity.VERY_LOW == "very_low"
        assert Severity.NONE == "none"


class TestVariableDict:
    def test_print_table(self) -> None:
        data = {
            "my_var": [Variable(name="my_var", value="hello", type=VariableType.TaskVars)],
        }
        result = VariableDict.print_table(data)
        assert "my_var" in result
        assert "hello" in result


class TestPackageInstallDetail:
    def test_with_args(self) -> None:
        detail = PackageInstallDetail(
            _pkg_arg=Arguments(raw="nginx", is_mutable=True),
        )
        assert detail.pkg == "nginx"
        assert detail.is_mutable_pkg is True


class TestKeyConfigChangeDetail:
    def test_deletion(self) -> None:
        detail = KeyConfigChangeDetail(
            _state_arg=Arguments(raw="absent"),
        )
        assert detail.is_deletion is True
