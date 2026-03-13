from __future__ import annotations

import builtins
import contextlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import jsonpickle
from rapidfuzz.distance import Levenshtein
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from tabulate import tabulate

# Recursive type for YAML/JSON values (defined before local imports to avoid circular import)
YAMLScalar = str | int | float | bool | None
YAMLValue = YAMLScalar | list["YAMLValue"] | dict[str, "YAMLValue"]
YAMLDict = dict[str, YAMLValue]
YAMLList = list[YAMLValue]

# Violation dicts from validators (rule_id, level, message, file, line, path, etc.)
ViolationDict = dict[str, str | int | list[int] | bool | None]

from . import yaml as ariyaml  # noqa: E402
from .finder import (  # noqa: E402
    identify_lines_with_jsonpath,
)
from .keyutil import (  # noqa: E402
    get_obj_info_by_key,
    set_call_object_key,
    set_collection_key,
    set_file_key,
    set_module_key,
    set_play_key,
    set_playbook_key,
    set_repository_key,
    set_role_key,
    set_task_key,
    set_taskfile_key,
)
from .utils import (  # noqa: E402
    equal,
    parse_bool,
    recursive_copy_dict,
)

if TYPE_CHECKING:
    from .risk_assessment_model import RAMClient


class PlaybookFormatError(Exception):
    pass


class TaskFormatError(Exception):
    pass


class FatalRuleResultError(Exception):
    pass


class JSONSerializable:
    def dump(self) -> str:
        return self.to_json()

    def to_json(self) -> str:
        return str(jsonpickle.encode(self, make_refs=False))

    @classmethod
    def from_json(cls: type[JSONSerializable], json_str: str) -> JSONSerializable:
        instance = cls()
        loaded: object = jsonpickle.decode(json_str)
        if hasattr(loaded, "__dict__"):
            instance.__dict__.update(loaded.__dict__)
        return instance


class Resolver(Protocol):
    def apply(self, target: Resolvable) -> None: ...


class Resolvable:
    def resolve(self, resolver: Resolver) -> None:
        if not hasattr(resolver, "apply"):
            raise ValueError("this resolver does not have apply() method")
        if not callable(resolver.apply):
            raise ValueError("resolver.apply is not callable")

        # apply resolver for this instance
        resolver.apply(self)

        # call resolve() for children recursively
        targets = self.resolver_targets
        if targets is None:
            return
        for t in targets:
            if isinstance(t, str):
                continue
            t.resolve(resolver)

        # apply resolver again here
        # because some attributes was not set at first
        resolver.apply(self)
        return

    @property
    def resolver_targets(self) -> list[Resolvable | str] | None:
        raise NotImplementedError


class LoadType:
    PROJECT = "project"
    COLLECTION = "collection"
    ROLE = "role"
    PLAYBOOK = "playbook"
    TASKFILE = "taskfile"
    UNKNOWN = "unknown"


@dataclass
class Load(JSONSerializable):
    target_name: str = ""
    target_type: str = ""
    path: str = ""
    loader_version: str = ""
    playbook_yaml: str = ""
    playbook_only: bool = False
    taskfile_yaml: str = ""
    taskfile_only: bool = False
    base_dir: str = ""
    include_test_contents: bool = False
    yaml_label_list: list[str] = field(default_factory=list)
    timestamp: str = ""

    # the following variables are list of paths; not object
    roles: list[str] = field(default_factory=list)
    playbooks: list[str] = field(default_factory=list)
    taskfiles: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass
class Object(JSONSerializable):
    type: str = ""
    key: str = ""


@dataclass
class ObjectList(JSONSerializable):
    items: list[Object | CallObject] = field(default_factory=list)
    _dict: dict[str, Object | CallObject] = field(default_factory=dict)

    def dump(self, fpath: str = "") -> str:
        return self.to_json(fpath=fpath)

    def to_json(self, fpath: str = "") -> str:
        lines: list[str] = [jsonpickle.encode(obj, make_refs=False) for obj in self.items]
        json_str = "\n".join(lines)
        if fpath != "":
            Path(fpath).write_text(json_str)
        return json_str

    def to_one_line_json(self) -> str:
        return str(jsonpickle.encode(self.items, make_refs=False))

    @classmethod
    def from_json(cls: type[ObjectList], json_str: str = "", fpath: str = "") -> ObjectList:
        instance = cls()
        if fpath != "":
            json_str = Path(fpath).read_text()
        lines: list[str] = json_str.splitlines()
        items: list[object] = [jsonpickle.decode(obj_str) for obj_str in lines]
        instance.items = [cast(Object, obj) for obj in items]
        instance._update_dict()
        return instance

    def add(self, obj: Object | CallObject, update_dict: bool = True) -> None:
        self.items.append(obj)
        if update_dict:
            self._add_dict_item(obj)
        return

    def merge(self, obj_list: ObjectList) -> None:
        if not isinstance(obj_list, ObjectList):
            raise ValueError(f"obj_list must be an instance of ObjectList, but got {type(obj_list).__name__}")
        self.items.extend(obj_list.items)
        self._update_dict()
        return

    def find_by_attr(self, key: str, val: YAMLValue) -> list[Object | CallObject]:
        found = [obj for obj in self.items if obj.__dict__.get(key, None) == val]
        return found

    def find_by_type(self, type_name: str) -> list[Object | CallObject]:
        return [obj for obj in self.items if hasattr(obj, "type") and obj.type == type_name]

    def find_by_key(self, key: str) -> Object | CallObject | None:
        return self._dict.get(key, None)

    def contains(self, key: str = "", obj: Object | None = None) -> bool:
        if obj is not None:
            key = obj.key
        return self.find_by_key(key) is not None

    def update_dict(self) -> None:
        self._update_dict()

    def _update_dict(self) -> None:
        for obj in self.items:
            self._dict[obj.key] = obj

    def _add_dict_item(self, obj: Object | CallObject) -> None:
        self._dict[obj.key] = obj

    @property
    def resolver_targets(self) -> list[Object | CallObject]:
        return self.items


@dataclass
class CallObject(JSONSerializable):
    type: str = ""
    key: str = ""
    called_from: str = ""
    spec: Object = field(default_factory=Object)
    depth: int = -1
    node_id: str = ""

    @classmethod
    def from_spec(cls: builtins.type[CallObject], spec: Object, caller: CallObject | None, index: int) -> CallObject:
        instance = cls()
        instance.spec = spec
        caller_key = "None"
        depth = 0
        node_id = "0"
        if caller:
            instance.called_from = caller.key
            caller_key = caller.key
            depth = caller.depth + 1
            index_str = "0"
            if index >= 0:
                index_str = str(index)
            node_id = caller.node_id + "." + index_str
        instance.depth = depth
        instance.node_id = node_id
        instance.key = set_call_object_key(cls.__name__, spec.key, caller_key)
        return instance


class RunTargetType:
    Playbook = "playbookcall"
    Play = "playcall"
    Role = "rolecall"
    TaskFile = "taskfilecall"
    Task = "taskcall"


@dataclass
class RunTarget:
    type: str = ""
    spec: Object = field(default_factory=Object)  # from CallObject in subclasses
    key: str = ""
    annotations: list[Annotation] = field(default_factory=list)

    def file_info(self) -> tuple[str, str | None]:
        file = getattr(self.spec, "defined_in", "") if self.spec else ""
        lines: str | None = None
        return file, lines

    def has_annotation_by_condition(self, cond: AnnotationCondition) -> bool:
        return False

    def get_annotation_by_condition(self, cond: AnnotationCondition) -> Annotation | RiskAnnotation | None:
        return None


@dataclass
class RunTargetList:
    items: list[RunTarget] = field(default_factory=list)

    _i: int = 0

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> RunTargetList:
        return self

    def __next__(self) -> RunTarget:
        if self._i == len(self.items):
            self._i = 0
            raise StopIteration()
        item = self.items[self._i]
        self._i += 1
        return item

    def __getitem__(self, i: int) -> RunTarget:
        return self.items[i]


@dataclass
class File:
    type: str = "file"
    name: str = ""
    key: str = ""
    local_key: str = ""
    role: str = ""
    collection: str = ""

    body: str = ""
    data: YAMLValue | None = None
    encrypted: bool = False
    error: str = ""
    label: str = ""
    defined_in: str = ""

    annotations: dict[str, YAMLValue] = field(default_factory=dict)

    def set_key(self) -> None:
        set_file_key(self)

    def children_to_key(self) -> File:
        return self

    @property
    def resolver_targets(self) -> None:
        return None


@dataclass
class ModuleArgument:
    name: str = ""
    type: str | None = None
    elements: str | None = None
    default: YAMLValue = None
    required: bool = False
    description: str = ""
    choices: list[YAMLScalar] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def available_keys(self) -> list[str]:
        keys = [self.name]
        if self.aliases:
            keys.extend(self.aliases)
        return keys


@dataclass
class Module(Object, Resolvable):
    type: str = "module"
    name: str = ""
    fqcn: str = ""
    key: str = ""
    local_key: str = ""
    collection: str = ""
    role: str = ""
    documentation: str = ""
    examples: str = ""
    arguments: list[ModuleArgument] = field(default_factory=list)
    defined_in: str = ""
    builtin: bool = False
    used_in: list[str] = field(default_factory=list)  # resolved later

    annotations: dict[str, YAMLValue] = field(default_factory=dict)

    def set_key(self) -> None:
        set_module_key(self)

    def children_to_key(self) -> Module:
        return self

    @property
    def resolver_targets(self) -> None:
        return None


@dataclass
class ModuleCall(CallObject, Resolvable):
    type: str = "modulecall"


@dataclass
class Collection(Object, Resolvable):
    type: str = "collection"
    name: str = ""
    path: str = ""
    key: str = ""
    local_key: str = ""
    metadata: YAMLDict = field(default_factory=dict)
    meta_runtime: YAMLDict = field(default_factory=dict)
    files: YAMLDict = field(default_factory=dict)
    playbooks: list[Playbook | str] = field(default_factory=list)
    taskfiles: list[TaskFile | str] = field(default_factory=list)
    roles: list[Role | str] = field(default_factory=list)
    modules: list[Module | str] = field(default_factory=list)
    dependency: YAMLDict = field(default_factory=dict)
    requirements: YAMLDict = field(default_factory=dict)

    annotations: dict[str, YAMLValue] = field(default_factory=dict)

    variables: YAMLDict = field(default_factory=dict)
    options: YAMLDict = field(default_factory=dict)

    def set_key(self) -> None:
        set_collection_key(self)

    def children_to_key(self) -> Collection:
        module_keys = [m.key if isinstance(m, Module) else m for m in self.modules]
        self.modules = cast(list["Module | str"], sorted(module_keys))

        playbook_keys = [p.key if isinstance(p, Playbook) else p for p in self.playbooks]
        self.playbooks = cast(list["Playbook | str"], sorted(playbook_keys))

        role_keys = [r.key if isinstance(r, Role) else r for r in self.roles]
        self.roles = cast(list["Role | str"], sorted(role_keys))

        taskfile_keys = [tf.key if isinstance(tf, TaskFile) else tf for tf in self.taskfiles]
        self.taskfiles = cast(list["TaskFile | str"], sorted(taskfile_keys))
        return self

    @property
    def resolver_targets(self) -> list[Resolvable | str]:
        return cast(
            list["Resolvable" | str],
            list(self.playbooks) + list(self.taskfiles) + list(self.roles) + list(self.modules),
        )


@dataclass
class CollectionCall(CallObject, Resolvable):
    type: str = "collectioncall"


@dataclass
class TaskCallsInTree(JSONSerializable):
    root_key: str = ""
    taskcalls: list[TaskCall] = field(default_factory=list)


@dataclass
class VariablePrecedence:
    name: str = ""
    order: int = -1

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return self.name

    def __eq__(self, __o: object) -> bool:
        if not isinstance(__o, VariablePrecedence):
            return NotImplemented
        return self.order == __o.order

    def __ne__(self, __o: object) -> bool:
        return not self.__eq__(__o)

    def __lt__(self, __o: object) -> bool:
        if not isinstance(__o, VariablePrecedence):
            return NotImplemented
        return self.order < __o.order

    def __le__(self, __o: object) -> bool:
        if not isinstance(__o, VariablePrecedence):
            return NotImplemented
        return self.__lt__(__o) or self.__eq__(__o)

    def __gt__(self, __o: object) -> bool:
        return not self.__le__(__o)

    def __ge__(self, __o: object) -> bool:
        return not self.__lt__(__o)


class VariableType:
    # When resolving variables, sometimes find unknown variables (e.g. undefined variable)
    # so we consider it as one type of variable
    Unknown = VariablePrecedence("unknown", -100)
    # Variable Precedence
    # https://docs.ansible.com/ansible/latest/playbook_guide
    #     /playbooks_variables.html#understanding-variable-precedence
    CommandLineValues = VariablePrecedence("command_line_values", 1)
    RoleDefaults = VariablePrecedence("role_defaults", 2)
    InventoryFileOrScriptGroupVars = VariablePrecedence("inventory_file_or_script_group_vars", 3)
    InventoryGroupVarsAll = VariablePrecedence("inventory_group_vars_all", 4)
    PlaybookGroupVarsAll = VariablePrecedence("playbook_group_vars_all", 5)
    InventoryGroupVarsAny = VariablePrecedence("inventory_group_vars_any", 6)
    PlaybookGroupVarsAny = VariablePrecedence("playbook_group_vars_any", 7)
    InventoryFileOrScriptHostVars = VariablePrecedence("inventory_file_or_script_host_vars", 8)
    InventoryHostVarsAny = VariablePrecedence("inventory_host_vars_any", 9)
    PlaybookHostVarsAny = VariablePrecedence("playbook_host_vars_any", 10)
    HostFacts = VariablePrecedence("host_facts", 11)
    PlayVars = VariablePrecedence("play_vars", 12)
    PlayVarsPrompt = VariablePrecedence("play_vars_prompt", 13)
    PlayVarsFiles = VariablePrecedence("play_vars_files", 14)
    RoleVars = VariablePrecedence("role_vars", 15)
    BlockVars = VariablePrecedence("block_vars", 16)
    TaskVars = VariablePrecedence("task_vars", 17)
    IncludeVars = VariablePrecedence("include_vars", 18)
    # we deal with set_facts and registered_vars separately
    # because the expression in a fact will be evaluated everytime it is used
    SetFacts = VariablePrecedence("set_facts", 19)
    RegisteredVars = VariablePrecedence("registered_vars", 20)
    RoleParams = VariablePrecedence("role_params", 21)
    IncludeParams = VariablePrecedence("include_params", 22)
    ExtraVars = VariablePrecedence("extra_vars", 23)
    # vars defined in `loop` cannot be overridden by the vars above
    # so we put this as a highest precedence var type
    LoopVars = VariablePrecedence("loop_vars", 24)


immutable_var_types = [VariableType.LoopVars]


@dataclass
class Variable:
    name: str = ""
    value: YAMLValue = None
    type: VariablePrecedence | None = None
    elements: list[Variable] = field(default_factory=list)
    setter: str | TaskCall | None = None
    used_in: str | TaskCall | None = None

    @property
    def is_mutable(self) -> bool:
        return self.type not in immutable_var_types if self.type else True


@dataclass
class VariableDict:
    _dict: dict[str, list[Variable]] = field(default_factory=dict)

    @staticmethod
    def print_table(data: dict[str, list[Variable]]) -> str:
        d = VariableDict(_dict=data)
        table = []
        type_labels = []
        found_type_label_names = []
        for v_list in d._dict.values():
            for v in v_list:
                if not v.type or v.type.name in found_type_label_names:
                    continue
                type_labels.append(v.type)
                found_type_label_names.append(v.type.name)
        type_labels = sorted(type_labels, key=lambda x: x.order, reverse=True)

        for v_name in d._dict:
            v_list = d._dict[v_name]
            row: dict[str, YAMLValue] = {"NAME": v_name}
            for t in type_labels:
                cell_value: YAMLValue = "-"
                for v in v_list:
                    if v.type != t:
                        continue
                    cell_value = v.value
                    if isinstance(cell_value, str) and cell_value == "":
                        cell_value = '""'
                type_label = t.name.upper()
                row[type_label] = cell_value
            table.append(row)
        return str(tabulate(table, headers="keys"))


class ArgumentsType:
    SIMPLE = "simple"
    LIST = "list"
    DICT = "dict"


@dataclass
class Arguments:
    type: str = ArgumentsType.SIMPLE
    raw: YAMLValue = None
    vars: list[Variable] = field(default_factory=list)
    resolved: bool = False
    templated: YAMLValue = None
    is_mutable: bool = False

    def get(self, key: str = "") -> Arguments | None:
        sub_raw: YAMLValue = None
        sub_templated: YAMLValue = None
        if key == "":
            sub_raw = self.raw
            sub_templated = self.templated
        else:
            if isinstance(self.raw, dict):
                sub_raw = self.raw.get(key, None)
                if self.templated and isinstance(self.templated, (list, tuple)):
                    first: YAMLValue = self.templated[0]
                    sub_templated = first.get(key, None) if isinstance(first, dict) else self.templated
            else:
                sub_raw = self.raw
                sub_templated = self.templated
        if not sub_raw:
            return None

        _vars: list[Variable] = []
        sub_type = ArgumentsType.SIMPLE
        if isinstance(sub_raw, str):
            for v in self.vars:
                if v.name in sub_raw:
                    _vars.append(v)
        elif isinstance(sub_raw, list):
            sub_type = ArgumentsType.LIST
        elif isinstance(sub_raw, dict):
            sub_type = ArgumentsType.DICT
        is_mutable = False
        for v in _vars:
            if v.is_mutable:
                is_mutable = True
                break

        return Arguments(
            type=sub_type,
            raw=sub_raw,
            vars=_vars,
            resolved=self.resolved,
            templated=sub_templated,
            is_mutable=is_mutable,
        )


class LocationType:
    FILE = "file"
    DIR = "dir"
    URL = "url"


@dataclass
class Location:
    type: str = ""
    value: str = ""
    vars: list[Variable] = field(default_factory=list)

    _args: Arguments | None = None

    def __post_init__(self) -> None:
        if self._args:
            self.value = str(self._args.raw) if self._args.raw is not None else ""
            self.vars = self._args.vars

    @property
    def is_mutable(self) -> bool:
        return len(self.vars) > 0

    @property
    def is_empty(self) -> bool:
        return not self.type and not self.value

    def is_inside(self, loc: Location) -> bool:
        if not isinstance(loc, Location):
            raise ValueError(f"is_inside() expect Location but given {type(loc)}")
        return loc.contains(self)

    def contains(self, target: Location | list[Location], any_mode: bool = False, all_mode: bool = True) -> bool:
        if isinstance(target, list):
            if any_mode:
                return self.contains_any(target_list=target)
            elif all_mode:
                return self.contains_all(target_list=target)
            else:
                raise ValueError('contains() must be run in either "any" or "all" mode')

        else:
            if not isinstance(target, Location):
                raise ValueError(f"contains() expect Location or list of Location, but given {type(target)}")

        my_path = self.value
        target_path = target.value
        return bool(target_path.startswith(my_path))

    def contains_any(self, target_list: list[Location]) -> bool:
        return any(self.contains(target) for target in target_list)

    def contains_all(self, target_list: list[Location]) -> bool:
        count = 0
        for target in target_list:
            if self.contains(target):
                count += 1
        return count == len(target_list)


class AnnotationDetail:
    pass


@dataclass
class NetworkTransferDetail(AnnotationDetail):
    src: Location | None = None
    dest: Location | None = None
    is_mutable_src: bool = False
    is_mutable_dest: bool = False

    _src_arg: Arguments | None = None
    _dest_arg: Arguments | None = None

    def __post_init__(self) -> None:
        if self._src_arg:
            self.src = Location(_args=self._src_arg)
            if self._src_arg.is_mutable:
                self.is_mutable_src = True

        if self._dest_arg:
            self.dest = Location(_args=self._dest_arg)
            if self._dest_arg.is_mutable:
                self.is_mutable_dest = True


@dataclass
class InboundTransferDetail(NetworkTransferDetail):
    def __post_init__(self) -> None:
        super().__post_init__()


@dataclass
class OutboundTransferDetail(NetworkTransferDetail):
    def __post_init__(self) -> None:
        super().__post_init__()


@dataclass
class PackageInstallDetail(AnnotationDetail):
    pkg: str | Arguments = ""
    version: str | Arguments | list[Variable] = ""
    is_mutable_pkg: bool = False
    disable_validate_certs: bool = False
    allow_downgrade: bool = False

    _pkg_arg: Arguments | None = None
    _version_arg: Arguments | None = None
    _allow_downgrade_arg: Arguments | None = None
    _validate_certs_arg: Arguments | None = None

    def __post_init__(self) -> None:
        if self._pkg_arg:
            self.pkg = cast(str | Arguments, self._pkg_arg.raw)
            if self._pkg_arg.is_mutable:
                self.is_mutable_pkg = True
        if self._version_arg:
            self.version = self._version_arg.vars
        if self._allow_downgrade_arg and _convert_to_bool(self._allow_downgrade_arg.raw):
            self.allow_downgrade = True
        if self._validate_certs_arg and not _convert_to_bool(self._validate_certs_arg.raw):
            self.disable_validate_certs = True


@dataclass
class KeyConfigChangeDetail(AnnotationDetail):
    is_deletion: bool = False
    is_mutable_key: bool = False
    key: str | list[Variable] = ""

    _key_arg: Arguments | None = None
    _state_arg: Arguments | None = None

    def __post_init__(self) -> None:
        if self._key_arg:
            self.key = self._key_arg.vars
            if self._key_arg and self._key_arg.is_mutable:
                self.is_mutable_key = True
        if self._state_arg and self._state_arg.raw == "absent":
            self.is_deletion = True


@dataclass
class FileChangeDetail(AnnotationDetail):
    path: Location | None = None
    src: Location | None = None
    is_mutable_path: bool = False
    is_mutable_src: bool = False
    is_unsafe_write: bool = False
    is_deletion: bool = False
    is_insecure_permissions: bool = False

    _path_arg: Arguments | None = None
    _src_arg: Arguments | None = None
    _mode_arg: Arguments | None = None
    _state_arg: Arguments | None = None
    _unsafe_write_arg: Arguments | None = None

    def __post_init__(self) -> None:
        if self._mode_arg and self._mode_arg.raw in ["1777", "0777"]:
            self.is_insecure_permissions = True
        if self._state_arg and self._state_arg.raw == "absent":
            self.is_deletion = True
        if self._path_arg:
            self.path = Location(_args=self._path_arg)
            if self._path_arg.is_mutable:
                self.is_mutable_path = True
        if self._src_arg:
            self.src = Location(_args=self._src_arg)
            if self._src_arg.is_mutable:
                self.is_mutable_src = True
        if self._unsafe_write_arg and _convert_to_bool(self._unsafe_write_arg.raw):
            self.is_unsafe_write = True


execution_programs: list[str] = ["sh", "bash", "zsh", "fish", "ash", "python*", "java*", "node*"]
non_execution_programs: list[str] = ["tar", "gunzip", "unzip", "mv", "cp"]


@dataclass
class CommandExecDetail(AnnotationDetail):
    command: Arguments | None = None
    exec_files: list[Location] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.exec_files = self.extract_exec_files()

    def extract_exec_files(self) -> list[Location]:
        cmd_str: str | list[str] | YAMLDict = cast(
            "str | list[str] | YAMLDict", "" if not self.command else (self.command.raw or "")
        )
        if isinstance(cmd_str, list):
            cmd_str = " ".join(str(x) for x in cmd_str)
        elif isinstance(cmd_str, dict):
            cmd_str = str(cmd_str.get("cmd", ""))
        elif not isinstance(cmd_str, str):
            cmd_str = str(cmd_str) if cmd_str else ""
        lines: list[str] = cmd_str.splitlines()
        exec_files = []
        for line in lines:
            parts = []
            is_in_variable = False
            concat_p = ""
            for p in line.split(" "):
                if "{{" in p and "}}" not in p:
                    is_in_variable = True
                if "}}" in p:
                    is_in_variable = False
                concat_p += " " + p if concat_p != "" else p
                if not is_in_variable:
                    parts.append(concat_p)
                    concat_p = ""
            found_program = None
            for i, p in enumerate(parts):
                if i == 0:
                    program = p if "/" not in p else p.split("/")[-1]
                    # filter out some specific non-exec patterns
                    if program in non_execution_programs:
                        break
                    # if the command string is like "python {{ python_script_path }}",
                    # {{ python_script_path }} is the exec file instead of "python"
                    if program in execution_programs:
                        continue
                    # for the case that the program name is like "python-3.6"
                    for exec_p in execution_programs:
                        if exec_p[-1] == "*" and program.startswith(exec_p[:-1]):
                            continue
                if p.startswith("-"):
                    continue
                if found_program is None:
                    found_program = p
                    break
            if found_program and self.command:
                exec_file_name = found_program
                related_vars = [v for v in self.command.vars if v.name in exec_file_name]
                location_type = LocationType.FILE
                exec_file = Location(
                    type=location_type,
                    value=exec_file_name,
                    vars=related_vars,
                )
                exec_files.append(exec_file)
        return exec_files


def _convert_to_bool(a: YAMLValue) -> bool | None:
    if type(a) is bool:
        return bool(a)
    if type(a) is str:
        return bool(a == "true" or a == "True" or a == "yes")
    return None


@dataclass
class Annotation(JSONSerializable):
    key: str = ""
    value: YAMLValue = None

    rule_id: str = ""

    # TODO: avoid Annotation variants and remove `type`
    type: str = ""


@dataclass
class VariableAnnotation(Annotation):
    type: str = "variable_annotation"
    option_value: Arguments = field(default_factory=lambda: Arguments())


class RiskType:
    pass


class DefaultRiskType(RiskType):
    NONE = ""
    CMD_EXEC = "cmd_exec"
    INBOUND = "inbound_transfer"
    OUTBOUND = "outbound_transfer"
    FILE_CHANGE = "file_change"
    SYSTEM_CHANGE = "system_change"
    NETWORK_CHANGE = "network_change"
    CONFIG_CHANGE = "config_change"
    PACKAGE_INSTALL = "package_install"
    PRIVILEGE_ESCALATION = "privilege_escalation"


@dataclass
class RiskAnnotation(Annotation, NetworkTransferDetail, CommandExecDetail):
    type: str = "risk_annotation"
    risk_type: str | RiskType = ""

    @classmethod
    def init(
        cls: builtins.type[RiskAnnotation],
        risk_type: str | RiskType,
        detail: AnnotationDetail,
    ) -> RiskAnnotation:
        anno = cls()
        anno.risk_type = risk_type
        # Walk MRO to collect annotations from all parent classes of the detail
        all_attrs: dict[str, Any] = {}  # type: ignore[explicit-any]
        for klass in reversed(type(detail).__mro__):
            all_attrs.update(getattr(klass, "__annotations__", {}))
        for attr_name in all_attrs:
            if attr_name.startswith("_"):
                continue
            val = getattr(detail, attr_name, None)
            setattr(anno, attr_name, val)
        return anno

    def equal_to(self, anno: RiskAnnotation) -> bool:
        if self.type != anno.type:
            return False
        if self.risk_type != anno.risk_type:
            return False
        self_dict = self.__dict__
        anno_dict = anno.__dict__
        return bool(equal(self_dict, anno_dict))


@dataclass
class FindCondition:
    def check(self, anno: RiskAnnotation) -> bool:
        raise NotImplementedError


@dataclass
class AnnotationCondition:
    type: str | RiskType = ""
    attr_conditions: list[tuple[str, YAMLValue]] = field(default_factory=list)

    def risk_type(self, risk_type: str | RiskType) -> AnnotationCondition:
        self.type = risk_type
        return self

    def attr(self, key: str, val: YAMLValue) -> AnnotationCondition:
        self.attr_conditions.append((key, val))
        return self


@dataclass
class AttributeCondition(FindCondition):
    attr: str | None = None
    result: YAMLValue = None

    def check(self, anno: RiskAnnotation) -> bool:
        if self.attr and hasattr(anno, self.attr):
            anno_value = getattr(anno, self.attr, None)
            if anno_value == self.result:
                return True
            if self.result is None and isinstance(anno_value, bool) and anno_value:
                return True
        return False


class _RiskAnnotationChecker(Protocol):
    def __call__(self, anno: RiskAnnotation, **kwargs: YAMLValue) -> bool | None: ...


@dataclass
class FunctionCondition(FindCondition):
    func: _RiskAnnotationChecker | None = None
    args: YAMLDict | YAMLList | None = None
    result: bool | None = None

    def check(self, anno: RiskAnnotation) -> bool:
        if self.func is not None and callable(self.func):
            kwargs: YAMLDict = self.args if isinstance(self.args, dict) else {}
            result = self.func(anno, **kwargs)
            if result == self.result:
                return True
        return False


@dataclass
class RiskAnnotationList:
    items: list[RiskAnnotation] = field(default_factory=list)

    _i: int = 0

    def __iter__(self) -> RiskAnnotationList:
        return self

    def __next__(self) -> RiskAnnotation:
        if self._i == len(self.items):
            self._i = 0
            raise StopIteration()
        anno = self.items[self._i]
        self._i += 1
        return anno

    def after(self, anno: RiskAnnotation) -> RiskAnnotationList:
        return get_annotations_after(self, anno)

    def filter(self, risk_type: str | RiskType = "") -> RiskAnnotationList:
        current = self
        if risk_type:
            current = filter_annotations_by_type(current, risk_type)
        return current

    def find(
        self,
        risk_type: str | RiskType = "",
        condition: FindCondition | list[FindCondition] | None = None,
    ) -> RiskAnnotationList:
        return search_risk_annotations(self, risk_type, condition)


def get_annotations_after(anno_list: RiskAnnotationList, anno: RiskAnnotation) -> RiskAnnotationList:
    sub_list = []
    found = False
    for anno_i in anno_list:
        if anno_i.equal_to(anno):
            found = True
        if found:
            sub_list.append(anno_i)
    if not found:
        raise ValueError(f"Annotation {anno} is not found in the specified AnnotationList")
    return RiskAnnotationList(sub_list)


def filter_annotations_by_type(anno_list: RiskAnnotationList, risk_type: str | RiskType) -> RiskAnnotationList:
    sub_list: list[RiskAnnotation] = []
    for anno_i in anno_list:
        if anno_i.risk_type == risk_type:
            sub_list.append(anno_i)
    return RiskAnnotationList(sub_list)


def search_risk_annotations(
    anno_list: RiskAnnotationList,
    risk_type: str | RiskType = "",
    condition: FindCondition | list[FindCondition] | None = None,
) -> RiskAnnotationList:
    matched = []
    for risk_anno in anno_list:
        if not isinstance(risk_anno, RiskAnnotation):
            continue
        if risk_type and risk_anno.risk_type != risk_type:
            continue
        if condition:
            if isinstance(condition, FindCondition):
                condition = [condition]
            for cond in condition:
                if cond.check(risk_anno):
                    matched.append(risk_anno)
                    break
    return RiskAnnotationList(matched)


class ExecutableType:
    MODULE_TYPE = "Module"
    ROLE_TYPE = "Role"
    TASKFILE_TYPE = "TaskFile"


@dataclass
class BecomeInfo:
    enabled: bool = False
    become: str = ""
    user: str = ""
    method: str = ""
    flags: str = ""

    @staticmethod
    def from_options(options: YAMLDict) -> BecomeInfo | None:
        if "become" in options:
            become = options.get("become", "")
            enabled = False
            with contextlib.suppress(Exception):
                enabled = parse_bool(become)
            user = str(options.get("become_user", ""))
            method = str(options.get("become_method", ""))
            flags = str(options.get("become_flags", ""))
            return BecomeInfo(enabled=enabled, user=user, method=method, flags=flags)
        return None


@dataclass
class Task(Object, Resolvable):
    type: str = "task"
    name: str | None = ""
    module: str = ""
    index: int = -1
    play_index: int = -1
    defined_in: str = ""
    key: str = ""
    local_key: str = ""
    role: str = ""
    collection: str = ""
    become: BecomeInfo | None = None
    variables: YAMLDict = field(default_factory=dict)
    module_defaults: YAMLDict = field(default_factory=dict)
    registered_variables: YAMLDict = field(default_factory=dict)
    set_facts: YAMLDict = field(default_factory=dict)
    loop: YAMLDict = field(default_factory=dict)
    options: YAMLDict = field(default_factory=dict)
    module_options: YAMLDict = field(default_factory=dict)
    executable: str = ""
    executable_type: str = ""
    collections_in_play: list[str] = field(default_factory=list)

    yaml_lines: str = ""
    line_num_in_file: list[int] = field(default_factory=list)  # [begin, end]
    jsonpath: str = ""

    # FQCN for Module and Role. Or a file path for TaskFile.  resolved later
    resolved_name: str = ""
    # candidates of resovled_name — (fqcn, defined_in_path)
    possible_candidates: list[tuple[str, str]] = field(default_factory=list)

    # embed these data when module/role/taskfile are resolved
    module_info: YAMLDict = field(default_factory=dict)
    include_info: YAMLDict = field(default_factory=dict)

    def set_yaml_lines(
        self,
        fullpath: str = "",
        yaml_lines: str = "",
        task_name: str = "",
        module_name: str = "",
        module_options: YAMLValue | None = None,
        task_options: YAMLValue | None = None,
        previous_task_line: int = -1,
        jsonpath: str = "",
    ) -> None:
        if not task_name and not module_options:
            return

        lines: list[str] = []
        lines = yaml_lines.splitlines() if yaml_lines else Path(fullpath).read_text().splitlines()

        if jsonpath:
            found_yaml, line_num = identify_lines_with_jsonpath(fpath=fullpath, yaml_str=yaml_lines, jsonpath=jsonpath)
            if found_yaml and line_num:
                self.yaml_lines = found_yaml
                self.line_num_in_file = list(line_num)
                return

        # search candidates that match either of the following conditions
        #   - task name is included in the line
        #   - if module name is included,
        #       - if module option is string, it is included
        #       - if module option is dict, at least one key is included
        candidate_line_nums = []
        for i, line in enumerate(lines):
            # skip lines until `previous_task_line` if provided
            if previous_task_line > 0 and i <= previous_task_line - 1:
                continue

            if task_name:
                if task_name in line:
                    candidate_line_nums.append(i)
            elif f"{module_name}:" in line:
                if isinstance(module_options, str):
                    if module_options in line:
                        candidate_line_nums.append(i)
                elif isinstance(module_options, dict):
                    option_matched = False
                    for key in module_options:
                        if i + 1 < len(lines) and f"{key}:" in lines[i + 1]:
                            option_matched = True
                            break
                    if option_matched:
                        candidate_line_nums.append(i)
        if not candidate_line_nums:
            return

        # get task yaml_lines for each candidate
        candidate_blocks = []
        for candidate_line_num in candidate_line_nums:
            _yaml_lines, _line_num_in_file = self._find_task_block(lines, candidate_line_num)
            if _yaml_lines and _line_num_in_file:
                candidate_blocks.append((_yaml_lines, _line_num_in_file))

        if not candidate_blocks:
            return

        reconstructed_yaml = ""
        best_yaml_lines = ""
        best_line_num_in_file = []
        sorted_candidates = []
        if len(candidate_blocks) == 1:
            best_yaml_lines = candidate_blocks[0][0]
            best_line_num_in_file = candidate_blocks[0][1]
        else:
            # reconstruct yaml from the task data to calculate similarity (edit distance) later
            reconstructed_data: list[YAMLDict] = [{}]
            if task_name:
                reconstructed_data[0]["name"] = task_name
            reconstructed_data[0][module_name] = module_options
            if isinstance(task_options, dict):
                for key, val in task_options.items():
                    if key not in reconstructed_data[0]:
                        reconstructed_data[0][key] = val

            with contextlib.suppress(Exception):
                reconstructed_yaml = ariyaml.dump(cast(YAMLValue, reconstructed_data))

            # find best match by edit distance
            if reconstructed_yaml:

                def remove_comment_lines(s: str) -> str:
                    lines = s.splitlines()
                    updated = []
                    for line in lines:
                        if line.strip().startswith("#"):
                            continue
                        updated.append(line)
                    return "\n".join(updated)

                def calc_dist(s1: str, s2: str) -> int:
                    us1 = remove_comment_lines(s1)
                    us2 = remove_comment_lines(s2)
                    dist = int(Levenshtein.distance(us1, us2))
                    return dist

                r = reconstructed_yaml
                sorted_candidates = sorted(candidate_blocks, key=lambda x: calc_dist(r, x[0]))
                best_yaml_lines = sorted_candidates[0][0]
                best_line_num_in_file = sorted_candidates[0][1]
            else:
                # give up here if yaml reconstruction failed
                # use the first candidate
                best_yaml_lines = candidate_blocks[0][0]
                best_line_num_in_file = candidate_blocks[0][1]

        self.yaml_lines = best_yaml_lines
        self.line_num_in_file = best_line_num_in_file
        return

    def _find_task_block(self, yaml_lines: list[str], start_line_num: int) -> tuple[str | None, list[int] | None]:
        if not yaml_lines:
            return None, None

        if start_line_num < 0:
            return None, None

        lines = yaml_lines
        found_line = lines[start_line_num]
        is_top_of_block = found_line.replace(" ", "").startswith("-")
        begin_line_num = start_line_num
        indent_of_block = -1
        if is_top_of_block:
            indent_of_block = len(found_line.split("-")[0])
        else:
            found = False
            found_line = ""
            _indent_of_block = -1
            parts = found_line.split(" ")
            for i, p in enumerate(parts):
                if p != "":
                    break
                _indent_of_block = i + 1
            for _ in range(len(lines)):
                index = begin_line_num
                _line = lines[index]
                is_top_of_block = _line.replace(" ", "").startswith("-")
                if is_top_of_block:
                    _indent = len(_line.split("-")[0])
                    if _indent < _indent_of_block:
                        found = True
                        found_line = _line
                        break
                begin_line_num -= 1
                if begin_line_num < 0:
                    break
            if not found:
                return None, None
            indent_of_block = len(found_line.split("-")[0])
        index = begin_line_num + 1
        end_found = False
        end_line_num = -1
        for _ in range(len(lines)):
            if index >= len(lines):
                break
            _line = lines[index]
            is_top_of_block = _line.replace(" ", "").startswith("-")
            is_when_at_same_indent = _line.replace(" ", "").startswith("when")
            if is_top_of_block or is_when_at_same_indent:
                if is_top_of_block:
                    _indent = len(_line.split("-")[0])
                elif is_when_at_same_indent:
                    _indent = len(_line.split("when")[0])
                if _indent <= indent_of_block:
                    end_found = True
                    end_line_num = index - 1
                    break
            else:
                _indent = len(_line) - len(_line.lstrip())
                if _indent <= indent_of_block:
                    end_found = True
                    end_line_num = index - 1
                    break
            index += 1
            if index >= len(lines):
                end_found = True
                end_line_num = index
                break

        if not end_found:
            return None, None
        if begin_line_num < 0 or end_line_num > len(lines) or begin_line_num > end_line_num:
            return None, None

        result_yaml = "\n".join(lines[begin_line_num : end_line_num + 1])
        line_num_in_file = [begin_line_num + 1, end_line_num + 1]
        return result_yaml, line_num_in_file

    # this keeps original contents like comments, indentation
    # and quotes for string as much as possible
    def yaml(self, original_module: str = "", use_yaml_lines: bool = True) -> str:
        task_data_wrapper: list[YAMLDict] | None = None
        task_data: YAMLDict | None = None
        if use_yaml_lines:
            try:
                loaded: object = ariyaml.load(self.yaml_lines)
                task_data_wrapper = cast(list[YAMLDict], loaded) if loaded else None
                task_data = task_data_wrapper[0] if task_data_wrapper else None
            except Exception:
                pass

            if not task_data:
                return self.yaml_lines
        else:
            task_data_wrapper = []
            task_data = {}

        is_local_action = "local_action" in self.options

        # task name
        if self.name:
            task_data["name"] = self.name
        elif "name" in task_data:
            task_data.pop("name")

        if not is_local_action:
            # module name
            if original_module:
                mo = deepcopy(task_data[original_module])
                task_data[self.module] = mo
            elif self.module and self.module not in task_data:
                task_data[self.module] = self.module_options

            # module options
            if isinstance(self.module_options, dict):
                current_mo = task_data[self.module]
                # if the module options was an old style inline parameter in YAML,
                # we can ignore them here because it is parsed as self.module_options
                if not isinstance(current_mo, dict):
                    current_mo = {}
                old_keys = list(current_mo.keys())
                new_keys = list(self.module_options.keys())
                for old_key in old_keys:
                    if old_key not in new_keys:
                        current_mo.pop(old_key)
                recursive_copy_dict(self.module_options, current_mo)
                task_data[self.module] = current_mo

        # task options
        if isinstance(self.options, dict):
            current_to = task_data
            old_keys = list(current_to.keys())
            new_keys = list(self.options.keys())
            for old_key in old_keys:
                if old_key in ["name", self.module]:
                    continue
                if old_key not in new_keys:
                    current_to.pop(old_key)
            options_without_name = {k: v for k, v in self.options.items() if k != "name"}
            if is_local_action:
                new_la_opt: YAMLDict = {}
                new_la_opt["module"] = self.module
                recursive_copy_dict(self.module_options, new_la_opt)
                options_without_name["local_action"] = new_la_opt
                recursive_copy_dict(options_without_name, current_to)
        wrapper = task_data_wrapper if task_data_wrapper is not None else []
        if len(wrapper) == 0:
            wrapper.append(current_to)
        else:
            wrapper[0] = current_to
        new_yaml = str(ariyaml.dump(cast(YAMLValue, wrapper)))
        return new_yaml

    # this makes a yaml from task contents such as spec.module,
    # spec.options, spec.module_options in a fixed format
    # NOTE: this will lose comments and indentations in the original YAML
    def formatted_yaml(self) -> str:
        task_data: YAMLDict = {}
        if self.name:
            task_data["name"] = self.name
        if self.module:
            task_data[self.module] = self.module_options
        for key, val in self.options.items():
            if key == "name":
                continue
            task_data[key] = val
        task_data = cast(YAMLDict, self.str2double_quoted_scalar(task_data))
        data = [task_data]
        return str(ariyaml.dump(cast(YAMLValue, data)))

    def str2double_quoted_scalar(self, v: YAMLValue) -> YAMLValue:
        if isinstance(v, dict):
            for key, val in v.items():
                new_val = self.str2double_quoted_scalar(val)
                v[key] = new_val
        elif isinstance(v, list):
            for i, val in enumerate(v):
                new_val = self.str2double_quoted_scalar(val)
                v[i] = new_val
        elif isinstance(v, str):
            v = DoubleQuotedScalarString(v)
        else:
            pass
        return v

    def set_key(self, parent_key: str = "", parent_local_key: str = "") -> None:
        set_task_key(self, parent_key, parent_local_key)

    def children_to_key(self) -> Task:
        return self

    @property
    def defined_vars(self) -> YAMLDict:
        d_vars = self.variables
        d_vars.update(self.registered_variables)
        d_vars.update(self.set_facts)
        return d_vars

    @property
    def tags(self) -> YAMLValue:
        return self.options.get("tags", None)

    @property
    def when(self) -> YAMLValue:
        return self.options.get("when", None)

    @property
    def action(self) -> str:
        return self.executable

    @property
    def resolved_action(self) -> str:
        return self.resolved_name

    @property
    def line_number(self) -> list[int]:
        return self.line_num_in_file

    @property
    def id(self) -> str:
        return json.dumps(
            {
                "path": self.defined_in,
                "index": self.index,
                "play_index": self.play_index,
            }
        )

    @property
    def resolver_targets(self) -> None:
        return None


@dataclass
class MutableContent:
    _yaml: str = ""
    _task_spec: Task | None = None

    def _require_task_spec(self) -> Task:
        if self._task_spec is None:
            raise ValueError("MutableContent has no task spec")
        return self._task_spec

    @staticmethod
    def from_task_spec(task_spec: Task) -> MutableContent:
        mc = MutableContent(
            _yaml=task_spec.yaml_lines,
            _task_spec=deepcopy(task_spec),
        )
        return mc

    def set_task_name(self, task_name: str) -> MutableContent:
        # if `name` is None or empty string, Task.yaml() won't output the field
        spec = self._require_task_spec()
        spec.name = task_name
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        return self

    def get_task_name(self) -> str | None:
        return self._task_spec.name if self._task_spec else None

    def omit_task_name(self) -> MutableContent:
        # if `name` is None or empty string, Task.yaml() won't output the field
        spec = self._require_task_spec()
        spec.name = None
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        return self

    def set_module_name(self, module_name: str) -> MutableContent:
        spec = self._require_task_spec()
        original_module = deepcopy(spec.module)
        spec.module = module_name
        self._yaml = spec.yaml(original_module=original_module)
        spec.yaml_lines = self._yaml
        return self

    def replace_key(self, old_key: str, new_key: str) -> MutableContent:
        spec = self._require_task_spec()
        if old_key in spec.options:
            value = spec.options[old_key]
            spec.options.pop(old_key)
            spec.options[new_key] = value
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        return self

    def replace_value(self, old_value: str, new_value: str) -> MutableContent:
        spec = self._require_task_spec()
        original_new_value = deepcopy(new_value)
        need_restore = False
        keys_to_be_restored = []
        if isinstance(new_value, str):
            new_value = DoubleQuotedScalarString(new_value)
            need_restore = True
        for k, v in spec.options.items():
            if type(v).__name__ != type(old_value).__name__:
                continue
            if v != old_value:
                continue
            spec.options[k] = new_value
            keys_to_be_restored.append(k)
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        if need_restore:
            for k, _ in spec.options.items():
                if k in keys_to_be_restored:
                    spec.options[k] = original_new_value
        return self

    def remove_key(self, key: str) -> MutableContent:
        spec = self._require_task_spec()
        if key in spec.options:
            spec.options.pop(key)
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        return self

    def set_new_module_arg_key(self, key: str, value: YAMLValue) -> MutableContent:
        spec = self._require_task_spec()
        original_value = deepcopy(value)
        need_restore = False
        if isinstance(value, str):
            value = DoubleQuotedScalarString(value)
            need_restore = True
        spec.module_options[key] = value
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        if need_restore:
            spec.module_options[key] = original_value
        return self

    def remove_module_arg_key(self, key: str) -> MutableContent:
        spec = self._require_task_spec()
        if key in spec.module_options:
            spec.module_options.pop(key)
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        return self

    def replace_module_arg_key(self, old_key: str, new_key: str) -> MutableContent:
        spec = self._require_task_spec()
        if old_key in spec.module_options:
            value = spec.module_options[old_key]
            spec.module_options.pop(old_key)
            spec.module_options[new_key] = value
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        return self

    def replace_module_arg_value(
        self, key: str = "", old_value: YAMLValue = None, new_value: YAMLValue = None
    ) -> MutableContent:
        spec = self._require_task_spec()
        original_new_value = deepcopy(new_value)
        need_restore = False
        keys_to_be_restored = []
        if isinstance(new_value, str):
            new_value = DoubleQuotedScalarString(new_value)
            need_restore = True
        for k in spec.module_options:
            # if `key` is specified, skip other keys
            if key and k != key:
                continue
            value = spec.module_options[k]
            if type(value).__name__ == type(old_value).__name__ and value == old_value:
                spec.module_options[k] = new_value
                keys_to_be_restored.append(k)
        self._yaml = spec.yaml()
        spec.yaml_lines = self._yaml
        if need_restore:
            for k in spec.module_options:
                if k in keys_to_be_restored:
                    spec.module_options[k] = original_new_value
        return self

    def replace_with_dict(self, new_dict: YAMLDict) -> MutableContent:
        spec = self._require_task_spec()
        from .model_loader import load_task

        yaml_lines = ariyaml.dump([new_dict])
        new_task = load_task(
            path=spec.defined_in,
            index=spec.index,
            task_block_dict=cast(dict[str, object], new_dict),
            task_jsonpath=spec.jsonpath,
            role_name=spec.role,
            collection_name=spec.collection,
            collections_in_play=spec.collections_in_play,
            play_index=spec.play_index,
            yaml_lines=yaml_lines,
        )
        self._yaml = yaml_lines
        self._task_spec = new_task
        return self

    def replace_module_arg_with_dict(self, new_dict: YAMLDict) -> MutableContent:
        spec = self._require_task_spec()
        spec.module_options = new_dict
        self._yaml = spec.yaml()
        return self

    # this keeps original contents like comments, indentation
    # and quotes for string as much as possible
    def yaml(self) -> str:
        return self._yaml

    # this makes a yaml from task contents such as spec.module,
    # spec.options, spec.module_options in a fixed format
    # NOTE: this will lose comments and indentations in the original YAML
    def formatted_yaml(self) -> str:
        return self._require_task_spec().formatted_yaml()


@dataclass
class TaskCall(CallObject, RunTarget):
    type: str = "taskcall"
    # annotations are used for storing generic analysis data
    # any Annotators in "annotators" dir can add them to this object
    annotations: list[Annotation] = field(default_factory=list)
    args: Arguments = field(default_factory=Arguments)
    variable_set: YAMLDict = field(default_factory=dict)
    variable_use: YAMLDict = field(default_factory=dict)
    become: BecomeInfo | None = None
    module_defaults: YAMLDict = field(default_factory=dict)

    module: Module | None = None
    content: MutableContent | None = None

    def get_annotation_by_type(self, type_str: str = "") -> list[Annotation]:
        matched = [an for an in self.annotations if an.type == type_str]
        return matched

    def get_annotation_by_type_and_attr(
        self, type_str: str = "", key: str = "", val: YAMLValue = None
    ) -> list[Annotation]:
        matched = [
            an
            for an in self.annotations
            if hasattr(an, "type") and an.type == type_str and getattr(an, key, None) == val
        ]
        return matched

    def set_annotation(self, key: str, value: YAMLValue, rule_id: str) -> None:
        end_to_set = False
        for an in self.annotations:
            if not hasattr(an, "key"):
                continue
            if an.key == key:
                an.value = value
                end_to_set = True
                break
        if not end_to_set:
            self.annotations.append(Annotation(key=key, value=value, rule_id=rule_id))
        return

    def get_annotation(self, key: str, __default: YAMLValue = None, rule_id: str = "") -> YAMLValue:
        value = __default
        for an in self.annotations:
            if not hasattr(an, "key"):
                continue
            if rule_id and hasattr(an, "rule_id") and an.rule_id != rule_id:
                continue
            if an.key == key:
                value = getattr(an, "value", __default)
                break
        return value

    def has_annotation_by_condition(self, cond: AnnotationCondition) -> bool:
        anno = self.get_annotation_by_condition(cond)
        return bool(anno)

    def get_annotation_by_condition(self, cond: AnnotationCondition) -> Annotation | RiskAnnotation | None:
        _annotations: list[Annotation] = list(self.annotations)
        if cond.type:
            _annotations = [an for an in _annotations if isinstance(an, RiskAnnotation) and an.risk_type == cond.type]
        if cond.attr_conditions:
            for key, val in cond.attr_conditions:
                _annotations = [an for an in _annotations if hasattr(an, key) and getattr(an, key) == val]
        if _annotations:
            return _annotations[0]
        return None

    def file_info(self) -> tuple[str, str]:
        file = self.spec.defined_in  # type: ignore[attr-defined]
        lines = "?"
        if len(self.spec.line_number) == 2:  # type: ignore[attr-defined]
            l_num = self.spec.line_number  # type: ignore[attr-defined]
            lines = f"L{l_num[0]}-{l_num[1]}"
        return file, lines

    @property
    def resolved_name(self) -> str:
        return getattr(self.spec, "resolved_name", "") if self.spec else ""

    @property
    def resolved_action(self) -> str:
        return self.resolved_name

    @property
    def action_type(self) -> str:
        return getattr(self.spec, "executable_type", "") if self.spec else ""


@dataclass
class AnsibleRunContext:
    sequence: RunTargetList = field(default_factory=RunTargetList)
    root_key: str = ""
    parent: Object | None = None
    ram_client: RAMClient | None = None
    scan_metadata: YAMLDict = field(default_factory=dict)

    # used by rule check
    current: RunTarget | None = None
    _i: int = 0

    # used if ram generate / other data generation by loop
    last_item: bool = False

    # TODO: implement the following attributes
    vars: YAMLDict | None = None
    host_info: YAMLDict | None = None

    def __len__(self) -> int:
        return len(self.sequence)

    def __iter__(self) -> AnsibleRunContext:
        return self

    def __next__(self) -> RunTarget:
        if self._i == len(self.sequence):
            self._i = 0
            self.current = None
            raise StopIteration()
        t = self.sequence[self._i]
        self.current = t
        self._i += 1
        return t

    def __getitem__(self, i: int) -> RunTarget:
        return self.sequence[i]

    @staticmethod
    def from_tree(
        tree: ObjectList,
        parent: Object | None = None,
        last_item: bool = False,
        ram_client: RAMClient | None = None,
        scan_metadata: YAMLDict | None = None,
    ) -> AnsibleRunContext:
        if not tree:
            return AnsibleRunContext(parent=parent, last_item=last_item, scan_metadata=scan_metadata or {})
        if len(tree.items) == 0:
            return AnsibleRunContext(parent=parent, last_item=last_item, scan_metadata=scan_metadata or {})
        scan_metadata = scan_metadata or {}
        first_item = tree.items[0]
        spec = getattr(first_item, "spec", None)
        root_key = getattr(spec, "key", getattr(first_item, "key", "")) if spec else getattr(first_item, "key", "")
        sequence_items: list[RunTarget] = []
        for item in tree.items:
            if isinstance(item, RunTarget):
                sequence_items.append(cast(RunTarget, item))
        tl = RunTargetList(items=sequence_items)
        return AnsibleRunContext(
            sequence=tl,
            root_key=root_key,
            parent=parent,
            last_item=last_item,
            ram_client=ram_client,
            scan_metadata=scan_metadata,
        )

    @staticmethod
    def from_targets(
        targets: list[RunTarget],
        root_key: str = "",
        parent: Object | None = None,
        last_item: bool = False,
        ram_client: RAMClient | None = None,
        scan_metadata: YAMLDict | None = None,
    ) -> AnsibleRunContext:
        if not root_key and len(targets) > 0:
            root_key = (
                getattr(targets[0].spec, "key", "") if hasattr(targets[0], "spec") else getattr(targets[0], "key", "")
            )
        scan_metadata = scan_metadata or {}
        tl = RunTargetList(items=targets)
        return AnsibleRunContext(
            sequence=tl,
            root_key=root_key,
            parent=parent,
            last_item=last_item,
            ram_client=ram_client,
            scan_metadata=scan_metadata,
        )

    def find(self, target: RunTarget) -> RunTarget | None:
        for t in self.sequence:
            if t.key == target.key:
                return t
        return None

    def before(self, target: RunTarget) -> AnsibleRunContext:
        targets = []
        for rt in self.sequence:
            if rt.key == target.key:
                break
            targets.append(rt)
        return AnsibleRunContext.from_targets(
            targets,
            root_key=self.root_key,
            parent=self.parent,
            last_item=self.last_item,
            ram_client=self.ram_client,
            scan_metadata=self.scan_metadata,
        )

    def search(self, cond: AnnotationCondition) -> AnsibleRunContext:
        targets = [t for t in self.sequence if t.type == RunTargetType.Task and t.has_annotation_by_condition(cond)]
        return AnsibleRunContext.from_targets(
            targets,
            root_key=self.root_key,
            parent=self.parent,
            last_item=self.last_item,
            ram_client=self.ram_client,
            scan_metadata=self.scan_metadata,
        )

    def is_end(self, target: RunTarget) -> bool:
        if len(self) == 0:
            return False
        return target.key == self.sequence[-1].key

    def is_last_task(self, target: RunTarget) -> bool:
        if len(self) == 0:
            return False
        taskcalls = self.taskcalls
        if len(taskcalls) == 0:
            return False
        return target.key == taskcalls[-1].key

    def is_begin(self, target: RunTarget) -> bool:
        if len(self) == 0:
            return False
        return target.key == self.sequence[0].key

    def copy(self) -> AnsibleRunContext:
        return AnsibleRunContext.from_targets(
            targets=self.sequence.items,
            root_key=self.root_key,
            parent=self.parent,
            last_item=self.last_item,
            ram_client=self.ram_client,
            scan_metadata=self.scan_metadata,
        )

    @property
    def info(self) -> YAMLDict:
        if not self.root_key:
            return {}
        info = cast(YAMLDict, dict(get_obj_info_by_key(self.root_key)))
        return info

    @property
    def taskcalls(self) -> list[RunTarget]:
        return [t for t in self.sequence if t.type == RunTargetType.Task]

    @property
    def tasks(self) -> list[RunTarget]:
        return self.taskcalls

    @property
    def annotations(self) -> RiskAnnotationList:
        anno_list: list[RiskAnnotation] = []
        for tc in self.taskcalls:
            for a in tc.annotations:
                if isinstance(a, RiskAnnotation):
                    anno_list.append(a)
        return RiskAnnotationList(anno_list)


@dataclass
class TaskFile(Object, Resolvable):
    type: str = "taskfile"
    name: str = ""
    defined_in: str = ""
    key: str = ""
    local_key: str = ""
    tasks: list[Task | str] = field(default_factory=list)
    # role name of this task file
    # this might be empty because a task file can be defined out of roles
    role: str = ""
    collection: str = ""

    yaml_lines: str = ""

    used_in: list[str] = field(default_factory=list)  # resolved later

    annotations: dict[str, YAMLValue] = field(default_factory=dict)

    variables: YAMLDict = field(default_factory=dict)
    module_defaults: YAMLDict = field(default_factory=dict)
    options: YAMLDict = field(default_factory=dict)

    task_loading: YAMLDict = field(default_factory=dict)

    def set_key(self) -> None:
        set_taskfile_key(self)

    def children_to_key(self) -> TaskFile:
        task_keys = [t.key if isinstance(t, Task) else t for t in self.tasks]
        self.tasks = cast(list["Task" | str], sorted(task_keys))
        return self

    @property
    def resolver_targets(self) -> list[Resolvable | str]:
        return list(self.tasks)


@dataclass
class TaskFileCall(CallObject, RunTarget):
    type: str = "taskfilecall"


@dataclass
class Role(Object, Resolvable):
    type: str = "role"
    name: str = ""
    defined_in: str = ""
    key: str = ""
    local_key: str = ""
    fqcn: str = ""
    metadata: YAMLDict = field(default_factory=dict)
    collection: str = ""
    playbooks: list[Playbook | str] = field(default_factory=list)
    # 1 role can have multiple task yamls
    taskfiles: list[TaskFile | str] = field(default_factory=list)
    handlers: list[Task] = field(default_factory=list)
    # roles/xxxx/library/zzzz.py can be called as module zzzz
    modules: list[Module | str] = field(default_factory=list)
    dependency: YAMLDict = field(default_factory=dict)
    requirements: YAMLDict = field(default_factory=dict)

    source: str = ""  # collection/scm repo/galaxy

    annotations: dict[str, YAMLValue] = field(default_factory=dict)

    default_variables: YAMLDict = field(default_factory=dict)
    variables: YAMLDict = field(default_factory=dict)
    # key: loop_var (default "item"), value: list/dict of item value
    loop: YAMLDict = field(default_factory=dict)
    options: YAMLDict = field(default_factory=dict)

    def set_key(self) -> None:
        set_role_key(self)

    def children_to_key(self) -> Role:
        module_keys = [m.key if isinstance(m, Module) else m for m in self.modules]
        self.modules = cast(list["Module" | str], sorted(module_keys))

        playbook_keys = [p.key if isinstance(p, Playbook) else p for p in self.playbooks]
        self.playbooks = cast(list["Playbook" | str], sorted(playbook_keys))

        taskfile_keys = [tf.key if isinstance(tf, TaskFile) else tf for tf in self.taskfiles]
        self.taskfiles = cast(list["TaskFile" | str], sorted(taskfile_keys))
        return self

    @property
    def resolver_targets(self) -> list[Resolvable | str]:
        return cast(list["Resolvable" | str], list(self.taskfiles) + list(self.modules))


@dataclass
class RoleCall(CallObject, RunTarget):
    type: str = "rolecall"


@dataclass
class RoleInPlay(Object, Resolvable):
    type: str = "roleinplay"
    name: str = ""
    options: YAMLDict = field(default_factory=dict)
    defined_in: str = ""
    role_index: int = -1
    play_index: int = -1

    role: str = ""
    collection: str = ""

    resolved_name: str = ""  # resolved later
    # candidates of resovled_name — (fqcn, defined_in_path)
    possible_candidates: list[tuple[str, str]] = field(default_factory=list)

    annotations: dict[str, YAMLValue] = field(default_factory=dict)
    collections_in_play: list[str] = field(default_factory=list)

    # embed this data when role is resolved
    role_info: YAMLDict = field(default_factory=dict)

    @property
    def resolver_targets(self) -> None:
        return None


@dataclass
class RoleInPlayCall(CallObject):
    type: str = "roleinplaycall"


@dataclass
class Play(Object, Resolvable):
    type: str = "play"
    name: str = ""
    defined_in: str = ""
    index: int = -1
    key: str = ""
    local_key: str = ""

    role: str = ""
    collection: str = ""
    import_module: str = ""
    import_playbook: str = ""
    pre_tasks: list[Task | str] = field(default_factory=list)
    tasks: list[Task | str] = field(default_factory=list)
    post_tasks: list[Task | str] = field(default_factory=list)
    handlers: list[Task | str] = field(default_factory=list)
    # not actual Role, but RoleInPlay defined in this playbook
    roles: list[RoleInPlay | str] = field(default_factory=list)
    module_defaults: YAMLDict = field(default_factory=dict)
    options: YAMLDict = field(default_factory=dict)
    collections_in_play: list[str] = field(default_factory=list)
    become: BecomeInfo | None = None
    variables: YAMLDict = field(default_factory=dict)
    vars_files: list[str] = field(default_factory=list)

    jsonpath: str = ""

    task_loading: YAMLDict = field(default_factory=dict)

    def set_key(self, parent_key: str = "", parent_local_key: str = "") -> None:
        set_play_key(self, parent_key, parent_local_key)

    def children_to_key(self) -> Play:
        pre_task_keys = [t.key if isinstance(t, Task) else t for t in self.pre_tasks]
        self.pre_tasks = cast(list["Task" | str], sorted(pre_task_keys))

        task_keys = [t.key if isinstance(t, Task) else t for t in self.tasks]
        self.tasks = cast(list["Task" | str], sorted(task_keys))

        post_task_keys = [t.key if isinstance(t, Task) else t for t in self.post_tasks]
        self.post_tasks = cast(list["Task" | str], sorted(post_task_keys))

        handler_task_keys = [t.key if isinstance(t, Task) else t for t in self.handlers]
        self.handlers = cast(list["Task" | str], sorted(handler_task_keys))
        return self

    @property
    def id(self) -> str:
        return json.dumps({"path": self.defined_in, "index": self.index})

    @property
    def resolver_targets(self) -> list[Resolvable | str]:
        return cast(
            list["Resolvable" | str],
            list(self.pre_tasks) + list(self.tasks) + list(self.roles),
        )


@dataclass
class PlayCall(CallObject, RunTarget):
    type: str = "playcall"


@dataclass
class Playbook(Object, Resolvable):
    type: str = "playbook"
    name: str = ""
    defined_in: str = ""
    key: str = ""
    local_key: str = ""

    yaml_lines: str = ""

    role: str = ""
    collection: str = ""

    plays: list[Play | str] = field(default_factory=list)

    used_in: list[str] = field(default_factory=list)  # resolved later

    annotations: dict[str, YAMLValue] = field(default_factory=dict)

    variables: YAMLDict = field(default_factory=dict)
    options: YAMLDict = field(default_factory=dict)

    def set_key(self) -> None:
        set_playbook_key(self)

    def children_to_key(self) -> Playbook:
        play_keys = [play.key if isinstance(play, Play) else play for play in self.plays]
        self.plays = cast(list["Play" | str], sorted(play_keys))
        return self

    @property
    def resolver_targets(self) -> list[Resolvable | str]:
        if "plays" in self.__dict__:
            return cast(list["Resolvable" | str], self.plays)
        return cast(
            list["Resolvable" | str],
            list(getattr(self, "roles", [])) + list(getattr(self, "tasks", [])),
        )


@dataclass
class PlaybookCall(CallObject, RunTarget):
    type: str = "playbookcall"


class InventoryType:
    GROUP_VARS_TYPE = "group_vars"
    HOST_VARS_TYPE = "host_vars"
    UNKNOWN_TYPE = ""


@dataclass
class Inventory(JSONSerializable):
    type: str = "inventory"
    name: str = ""
    defined_in: str = ""
    inventory_type: str = ""
    group_name: str = ""
    host_name: str = ""
    variables: YAMLDict = field(default_factory=dict)


@dataclass
class Repository(Object, Resolvable):
    type: str = "repository"
    name: str = ""
    path: str = ""
    key: str = ""
    local_key: str = ""

    # if set, this repository is a collection repository
    my_collection_name: str = ""

    playbooks: list[Playbook | str] = field(default_factory=list)
    roles: list[Role | str] = field(default_factory=list)

    # for playbook scan
    target_playbook_path: str = ""

    # for taskfile scan
    target_taskfile_path: str = ""

    requirements: YAMLDict = field(default_factory=dict)

    installed_collections_path: str = ""
    installed_collections: list[Collection | str] = field(default_factory=list)

    installed_roles_path: str = ""
    installed_roles: list[Role | str] = field(default_factory=list)
    modules: list[Module | str] = field(default_factory=list)
    taskfiles: list[TaskFile | str] = field(default_factory=list)

    inventories: list[Inventory | str] = field(default_factory=list)

    files: list[File | str] = field(default_factory=list)

    version: str = ""

    annotations: dict[str, YAMLValue] = field(default_factory=dict)

    def set_key(self) -> None:
        set_repository_key(self)

    def children_to_key(self) -> Repository:
        module_keys = [m.key if isinstance(m, Module) else m for m in self.modules]
        self.modules = cast(list["Module" | str], sorted(module_keys))

        playbook_keys = [p.key if isinstance(p, Playbook) else p for p in self.playbooks]
        self.playbooks = cast(list["Playbook" | str], sorted(playbook_keys))

        taskfile_keys = [tf.key if isinstance(tf, TaskFile) else tf for tf in self.taskfiles]
        self.taskfiles = cast(list["TaskFile" | str], sorted(taskfile_keys))

        role_keys = [r.key if isinstance(r, Role) else r for r in self.roles]
        self.roles = cast(list["Role" | str], sorted(role_keys))
        return self

    @property
    def resolver_targets(self) -> list[Resolvable | str]:
        return cast(
            list["Resolvable" | str],
            list(self.playbooks)
            + list(self.roles)
            + list(self.modules)
            + list(self.installed_roles)
            + list(self.installed_collections),
        )


@dataclass
class RepositoryCall(CallObject):
    type: str = "repositorycall"


def call_obj_from_spec(spec: Object, caller: CallObject | None, index: int = 0) -> CallObject | None:
    if isinstance(spec, Repository):
        return RepositoryCall.from_spec(spec, caller, index)
    elif isinstance(spec, Playbook):
        return PlaybookCall.from_spec(spec, caller, index)
    elif isinstance(spec, Play):
        return PlayCall.from_spec(spec, caller, index)
    elif isinstance(spec, RoleInPlay):
        return RoleInPlayCall.from_spec(spec, caller, index)
    elif isinstance(spec, Role):
        return RoleCall.from_spec(spec, caller, index)
    elif isinstance(spec, TaskFile):
        return TaskFileCall.from_spec(spec, caller, index)
    elif isinstance(spec, Task):
        taskcall = cast(TaskCall, TaskCall.from_spec(spec, caller, index))
        taskcall.content = MutableContent.from_task_spec(task_spec=spec)
        return taskcall
    elif isinstance(spec, Module):
        return ModuleCall.from_spec(spec, caller, index)
    return None


# inherit Repository just for convenience
# this is not a Repository but one or multiple Role / Collection
@dataclass
class GalaxyArtifact(Repository):
    type: str = ""  # Role or Collection

    # make it easier to search a module
    module_dict: dict[str, Module] = field(default_factory=dict)
    # make it easier to search a task
    task_dict: dict[str, Task] = field(default_factory=dict)
    # make it easier to search a taskfile
    taskfile_dict: dict[str, TaskFile] = field(default_factory=dict)
    # make it easier to search a role
    role_dict: dict[str, Role] = field(default_factory=dict)
    # make it easier to search a playbook
    playbook_dict: dict[str, Playbook] = field(default_factory=dict)
    # make it easier to search a collection
    collection_dict: dict[str, Collection] = field(default_factory=dict)


@dataclass
class ModuleMetadata:
    fqcn: str = ""
    # arguments: list = field(default_factory=list)
    type: str = ""
    name: str = ""
    version: str = ""
    hash: str = ""
    deprecated: bool = False

    @staticmethod
    def from_module(m: Module, metadata: YAMLDict) -> ModuleMetadata:
        mm = ModuleMetadata()
        for key in mm.__dict__:
            if hasattr(m, key):
                val = getattr(m, key, None)
                setattr(mm, key, val)

        mm.type = str(metadata.get("type", ""))
        mm.name = str(metadata.get("name", ""))
        mm.version = str(metadata.get("version", ""))
        mm.hash = str(metadata.get("hash", ""))
        return mm

    @staticmethod
    def from_routing(dst: str, metadata: YAMLDict) -> ModuleMetadata:
        mm = ModuleMetadata()
        mm.fqcn = dst
        mm.type = str(metadata.get("type", ""))
        mm.name = str(metadata.get("name", ""))
        mm.version = str(metadata.get("version", ""))
        mm.hash = str(metadata.get("hash", ""))
        mm.deprecated = True
        return mm

    @staticmethod
    def from_dict(d: YAMLDict) -> ModuleMetadata:
        mm = ModuleMetadata()
        mm.fqcn = str(d.get("fqcn", ""))
        mm.type = str(d.get("type", ""))
        mm.name = str(d.get("name", ""))
        mm.version = str(d.get("version", ""))
        mm.hash = str(d.get("hash", ""))
        return mm

    def __eq__(self, mm: object) -> bool:
        if not isinstance(mm, ModuleMetadata):
            return False
        return (
            self.fqcn == mm.fqcn
            and self.name == mm.name
            and self.type == mm.type
            and self.version == mm.version
            and self.hash == mm.hash
        )


@dataclass
class RoleMetadata:
    fqcn: str = ""
    type: str = ""
    name: str = ""
    version: str = ""
    hash: str = ""

    @staticmethod
    def from_role(r: Role, metadata: YAMLDict) -> RoleMetadata:
        rm = RoleMetadata()
        for key in rm.__dict__:
            if hasattr(r, key):
                val = getattr(r, key, None)
                setattr(rm, key, val)

        rm.type = str(metadata.get("type", ""))
        rm.name = str(metadata.get("name", ""))
        rm.version = str(metadata.get("version", ""))
        rm.hash = str(metadata.get("hash", ""))
        return rm

    @staticmethod
    def from_dict(d: YAMLDict) -> RoleMetadata:
        rm = RoleMetadata()
        rm.fqcn = str(d.get("fqcn", ""))
        rm.type = str(d.get("type", ""))
        rm.name = str(d.get("name", ""))
        rm.version = str(d.get("version", ""))
        rm.hash = str(d.get("hash", ""))
        return rm

    def __eq__(self, rm: object) -> bool:
        if not isinstance(rm, RoleMetadata):
            return False
        return (
            self.fqcn == rm.fqcn
            and self.name == rm.name
            and self.type == rm.type
            and self.version == rm.version
            and self.hash == rm.hash
        )


@dataclass
class TaskFileMetadata:
    key: str = ""
    type: str = ""
    name: str = ""
    version: str = ""
    hash: str = ""

    @staticmethod
    def from_taskfile(tf: TaskFile, metadata: YAMLDict) -> TaskFileMetadata:
        tfm = TaskFileMetadata()
        for key in tfm.__dict__:
            if hasattr(tf, key):
                val = getattr(tf, key, None)
                setattr(tfm, key, val)

        tfm.type = str(metadata.get("type", ""))
        tfm.name = str(metadata.get("name", ""))
        tfm.version = str(metadata.get("version", ""))
        tfm.hash = str(metadata.get("hash", ""))
        return tfm

    @staticmethod
    def from_dict(d: YAMLDict) -> TaskFileMetadata:
        tfm = TaskFileMetadata()
        tfm.key = str(d.get("key", ""))
        tfm.type = str(d.get("type", ""))
        tfm.name = str(d.get("name", ""))
        tfm.version = str(d.get("version", ""))
        tfm.hash = str(d.get("hash", ""))
        return tfm

    def __eq__(self, tfm: object) -> bool:
        if not isinstance(tfm, TaskFileMetadata):
            return False
        return (
            self.key == tfm.key
            and self.name == tfm.name
            and self.type == tfm.type
            and self.version == tfm.version
            and self.hash == tfm.hash
        )


@dataclass
class ActionGroupMetadata:
    group_name: str = ""
    group_modules: list[Module] = field(default_factory=list)
    type: str = ""
    name: str = ""
    version: str = ""
    hash: str = ""

    @staticmethod
    def from_action_group(
        group_name: str, group_modules: list[Module], metadata: YAMLDict
    ) -> ActionGroupMetadata | None:
        if not group_name:
            return None

        if not group_modules:
            return None

        agm = ActionGroupMetadata()
        agm.group_name = group_name
        agm.group_modules = group_modules
        agm.type = str(metadata.get("type", ""))
        agm.name = str(metadata.get("name", ""))
        agm.version = str(metadata.get("version", ""))
        agm.hash = str(metadata.get("hash", ""))
        return agm

    @staticmethod
    def from_dict(d: YAMLDict) -> ActionGroupMetadata:
        agm = ActionGroupMetadata()
        agm.group_name = str(d.get("group_name", ""))
        agm.group_modules = cast(list["Module"], d.get("group_modules", []))
        agm.type = str(d.get("type", ""))
        agm.name = str(d.get("name", ""))
        agm.version = str(d.get("version", ""))
        agm.hash = str(d.get("hash", ""))
        return agm

    def __eq__(self, agm: object) -> bool:
        if not isinstance(agm, ActionGroupMetadata):
            return False
        return (
            self.group_name == agm.group_name
            and self.name == agm.name
            and self.type == agm.type
            and self.version == agm.version
            and self.hash == agm.hash
        )


# following ansible-lint severity levels
class Severity:
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    VERY_LOW = "very_low"
    NONE = "none"


_severity_level_mapping = {
    Severity.VERY_HIGH: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.VERY_LOW: 1,
    Severity.NONE: 0,
}


class RuleTag:
    NETWORK = "network"
    COMMAND = "command"
    DEPENDENCY = "dependency"
    SYSTEM = "system"
    PACKAGE = "package"
    CODING = "coding"
    VARIABLE = "variable"
    QUALITY = "quality"
    DEBUG = "debug"


@dataclass
class RuleMetadata:
    rule_id: str = ""
    description: str = ""
    name: str = ""

    version: str = ""
    commit_id: str = ""
    severity: str = ""
    tags: tuple[str, ...] = ()


@dataclass
class SpecMutation:
    key: str | None = None
    changes: list[YAMLValue] = field(default_factory=list)
    object: Object = field(default_factory=Object)
    rule: RuleMetadata = field(default_factory=RuleMetadata)


@dataclass
class RuleResult:
    rule: RuleMetadata | None = None

    verdict: bool = False
    detail: YAMLDict | None = None
    file: tuple[str | int, ...] | None = None
    error: str | None = None

    matched: bool = False
    duration: float | None = None

    def __post_init__(self) -> None:
        if self.verdict:
            self.verdict = True
        else:
            self.verdict = False

    def set_value(self, key: str, value: YAMLValue) -> None:
        if self.detail is not None:
            self.detail[key] = value

    def get_detail(self) -> YAMLDict | None:
        return self.detail


@dataclass
class Rule(RuleMetadata):
    # `enabled` represents if the rule is enabled or not
    enabled: bool = False

    # `precedence` represents the order of the rule evaluation.
    # A rule with a lower number will be evaluated earlier than others.
    precedence: int = 10

    # `spec_mutation` represents if the rule mutates spec objects
    # if there are any spec mutations, re-run the scan later with the mutated spec
    spec_mutation: bool = False

    def __post_init__(self, rule_id: str = "", description: str = "") -> None:
        if rule_id:
            self.rule_id = rule_id
        if description:
            self.description = description

        if not self.rule_id:
            raise ValueError("A rule must have a unique rule_id")

        if not self.description:
            raise ValueError("A rule must have a description")

    def match(self, ctx: AnsibleRunContext) -> bool:
        raise ValueError("this is a base class method")

    def process(self, ctx: AnsibleRunContext) -> RuleResult | None:
        raise ValueError("this is a base class method")

    def print(self, result: RuleResult) -> str:
        output = (
            f"ruleID={self.rule_id}, severity={self.severity}, description={self.description}, result={result.verdict}"
        )

        if result.file:
            output += f", file={result.file}"
        if result.detail:
            output += f", detail={result.detail}"
        return output

    def to_json(self, result: RuleResult) -> str:
        return str(json.dumps(result.detail))

    def error(self, result: RuleResult) -> str | None:
        if result.error:
            return result.error
        return None

    def get_metadata(self) -> RuleMetadata:
        return RuleMetadata(
            rule_id=self.rule_id,
            description=self.description,
            name=self.name,
            version=self.version,
            commit_id=self.commit_id,
            severity=self.severity,
            tags=self.tags,
        )


@dataclass
class NodeResult(JSONSerializable):
    node: RunTarget | YAMLDict | None = None
    rules: list[RuleResult] = field(default_factory=list)

    def results(self) -> list[RuleResult]:
        return self.rules

    def find_result(self, rule_id: str) -> RuleResult | None:
        filtered = [r for r in self.rules if r.rule and r.rule.rule_id == rule_id]
        if not filtered:
            return None
        return filtered[0]

    def search_results(
        self,
        rule_id: str | list[str] | None = None,
        tag: str | list[str] | None = None,
        matched: bool | None = None,
        verdict: bool | None = None,
    ) -> list[RuleResult]:
        if not rule_id and not tag:
            return self.rules

        filtered = self.rules
        if rule_id:
            target_rule_ids = []
            if isinstance(rule_id, str):
                target_rule_ids = [rule_id]
            elif isinstance(rule_id, list):
                target_rule_ids = rule_id
            filtered = [r for r in filtered if r.rule and r.rule.rule_id in target_rule_ids]

        if tag:
            target_tags: list[str] = []
            if isinstance(tag, str):
                target_tags = [tag]
            elif isinstance(tag, list):
                target_tags = tag
            filtered = [r for r in filtered if r.rule is not None and any(t in target_tags for t in r.rule.tags)]

        if matched is not None:
            filtered = [r for r in filtered if r.matched == matched]

        if verdict is not None:
            filtered = [r for r in filtered if r.verdict == verdict]

        return filtered


@dataclass
class TargetResult(JSONSerializable):
    target_type: str = ""  # playbook, role or taskfile
    target_name: str = ""
    nodes: list[NodeResult] = field(default_factory=list)

    def applied_rules(self) -> list[RuleResult]:
        results: list[RuleResult] = []
        for n in self.nodes:
            matched_rules = n.search_results(matched=True)
            if matched_rules:
                results.extend(matched_rules)
        return results

    def matched_rules(self) -> list[RuleResult]:
        results: list[RuleResult] = []
        for n in self.nodes:
            matched_rules = n.search_results(verdict=True)
            if matched_rules:
                results.extend(matched_rules)
        return results

    def tasks(self) -> TargetResult:
        return self._filter(TaskCall)

    def task(self, name: str) -> NodeResult | None:
        return self._find_by_name(name=name, target_type=TaskCall)

    def roles(self) -> TargetResult:
        return self._filter(RoleCall)

    def role(self, name: str) -> NodeResult | None:
        return self._find_by_name(name=name, target_type=RoleCall)

    def playbooks(self) -> TargetResult:
        return self._filter(PlaybookCall)

    def playbook(self, name: str) -> NodeResult | None:
        return self._find_by_name(name=name, target_type=PlaybookCall)

    def plays(self) -> TargetResult:
        return self._filter(PlayCall)

    def play(self, name: str) -> NodeResult | None:
        return self._find_by_name(name=name, target_type=PlayCall)

    def taskfiles(self) -> TargetResult:
        return self._filter(TaskFileCall)

    def taskfile(self, name: str) -> NodeResult | None:
        return self._find_by_name(name=name, target_type=TaskFileCall)

    def _find_by_name(self, name: str, target_type: type[RunTarget] | None = None) -> NodeResult | None:
        nodes = deepcopy(self.nodes)
        if target_type:
            type_only_result = self._filter(target_type)
            if not type_only_result:
                return None
            nodes = type_only_result.nodes
        filtered_nodes = [nr for nr in nodes if nr.node and getattr(getattr(nr.node, "spec", None), "name", "") == name]
        if not filtered_nodes:
            return None
        return filtered_nodes[0]

    def _filter(self, target_type: type[RunTarget]) -> TargetResult:
        filtered_nodes = [nr for nr in self.nodes if isinstance(nr.node, target_type)]
        return TargetResult(target_type=self.target_type, target_name=self.target_name, nodes=filtered_nodes)


@dataclass
class ARIResult(JSONSerializable):
    targets: list[TargetResult] = field(default_factory=list)

    def playbooks(self) -> ARIResult:
        return self._filter("playbook")

    def playbook(self, name: str = "", path: str = "", yaml_str: str = "") -> TargetResult | None:
        if name:
            return self._find_by_name(name)

        # TODO: use path correctly
        if path:
            name = os.path.basename(path)
            return self._find_by_name(name)

        if yaml_str:
            return self._find_by_yaml_str(yaml_str, "playbook")

        return None

    def roles(self) -> ARIResult:
        return self._filter("role")

    def role(self, name: str) -> TargetResult | None:
        return self._find_by_name(name=name, type_str="role")

    def taskfiles(self) -> ARIResult:
        return self._filter("taskfile")

    def taskfile(self, name: str = "", path: str = "", yaml_str: str = "") -> TargetResult | None:
        if name:
            return self._find_by_name(name=name, type_str="taskfile")

        # TODO: use path correctly
        if path:
            name = os.path.basename(path)
            return self._find_by_name(name=name, type_str="taskfile")

        if yaml_str:
            return self._find_by_yaml_str(yaml_str, "taskfile")

        return None

    def find_target(
        self, name: str = "", path: str = "", yaml_str: str = "", target_type: str = ""
    ) -> TargetResult | None:
        if name:
            return self._find_by_name(name=name, type_str=target_type)

        # TODO: use path correctly
        if path:
            name = os.path.basename(path)
            return self._find_by_name(name=name, type_str=target_type)

        if yaml_str:
            return self._find_by_yaml_str(yaml_str, target_type)

        return None

    def _find_by_name(self, name: str, type_str: str = "") -> TargetResult | None:
        targets = deepcopy(self.targets)
        if type_str:
            type_only_result = self._filter(type_str)
            if not type_only_result:
                return None
            targets = type_only_result.targets
        filtered_targets = [tr for tr in targets if tr.target_name == name]
        if not filtered_targets:
            return None
        return filtered_targets[0]

    def _find_by_yaml_str(self, yaml_str: str, type_str: str) -> TargetResult | None:
        type_only_result = self._filter(type_str)
        if not type_only_result:
            return None
        filtered_targets = [
            tr
            for tr in type_only_result.targets
            if tr.nodes
            and tr.nodes[0].node
            and getattr(getattr(tr.nodes[0].node, "spec", None), "yaml_lines", "") == yaml_str
        ]
        if not filtered_targets:
            return None
        return filtered_targets[0]

    def _filter(self, type_str: str) -> ARIResult:
        filtered_targets = [tr for tr in self.targets if tr.target_type == type_str]
        return ARIResult(targets=filtered_targets)
