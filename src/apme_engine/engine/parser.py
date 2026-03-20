"""Parser for Ansible content (collections, roles, playbooks, taskfiles)."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import cast

from . import logger
from .model_loader import (
    load_collection,
    load_file,
    load_module,
    load_playbook,
    load_repository,
    load_role,
    load_taskfile,
)
from .models import (
    Collection,
    File,
    Load,
    LoadType,
    Module,
    Object,
    Play,
    Playbook,
    PlaybookFormatError,
    Repository,
    Role,
    Task,
    TaskFile,
    TaskFormatError,
    YAMLValue,
)
from .utils import (
    get_module_specs_by_ansible_doc,
    split_target_playbook_fullpath,
    split_target_taskfile_fullpath,
)


class Parser:
    """Parses Ansible content (collections, roles, playbooks, taskfiles) into definitions."""

    def __init__(
        self,
        do_save: bool = False,
        use_ansible_doc: bool = True,
        skip_playbook_format_error: bool = True,
        skip_task_format_error: bool = True,
    ) -> None:
        """Initialize the parser with load and error-handling options.

        Args:
            do_save: Whether to save parsed definitions.
            use_ansible_doc: Use ansible-doc for module specs.
            skip_playbook_format_error: Skip playbooks with format errors.
            skip_task_format_error: Skip tasks with format errors.
        """
        self.do_save = do_save
        self.use_ansible_doc = use_ansible_doc
        self.skip_playbook_format_error = skip_playbook_format_error
        self.skip_task_format_error = skip_task_format_error

    def run(
        self,
        load_data: Load | None = None,
        load_json_path: str = "",
        collection_name_of_project: str = "",
    ) -> tuple[dict[str, list[Object]], Load] | None:
        """Parse Ansible content and return definitions plus Load metadata.

        Loads from Load object, JSON file, or both. Supports collections, roles,
        projects, playbooks, and taskfiles. Returns mappings of object types to
        parsed definitions.

        Args:
            load_data: Pre-built Load object. If None, load_json_path used.
            load_json_path: Path to Load JSON file.
            collection_name_of_project: Override collection name for projects.

        Returns:
            Tuple of (definitions dict, Load) or None on load failure.

        Raises:
            ValueError: If file not found or load type unsupported.
            PlaybookFormatError: If skip_playbook_format_error is False.
            TaskFormatError: If skip_task_format_error is False.
        """
        ld: Load = Load()
        if load_data is not None:
            ld = load_data
        elif load_json_path != "":
            if not os.path.exists(load_json_path):
                raise ValueError(f"file not found: {load_json_path}")
            ld = cast(Load, Load.from_json(Path(load_json_path).read_text()))

        collection_name = ""
        role_name = ""
        obj: Collection | Role | Repository | Playbook | TaskFile | None = None
        if ld.target_type == LoadType.COLLECTION:
            collection_name = ld.target_name
            try:
                obj = load_collection(
                    collection_dir=ld.path,
                    basedir=ld.path,
                    use_ansible_doc=self.use_ansible_doc,
                    skip_playbook_format_error=self.skip_playbook_format_error,
                    skip_task_format_error=self.skip_task_format_error,
                    include_test_contents=ld.include_test_contents,
                    load_children=False,
                )
            except PlaybookFormatError:
                if not self.skip_playbook_format_error:
                    raise
            except TaskFormatError:
                if not self.skip_task_format_error:
                    raise
            except Exception:
                logger.exception(f"failed to load the collection {collection_name}")
                return None
        elif ld.target_type == LoadType.ROLE:
            role_name = ld.target_name
            try:
                obj = load_role(
                    path=ld.path,
                    basedir=ld.path,
                    use_ansible_doc=self.use_ansible_doc,
                    skip_playbook_format_error=self.skip_playbook_format_error,
                    skip_task_format_error=self.skip_task_format_error,
                    include_test_contents=ld.include_test_contents,
                    load_children=False,
                )
                # use fqcn as role_name when the original target_name is a local path
                if role_name != obj.fqcn:
                    role_name = obj.fqcn
            except PlaybookFormatError:
                if not self.skip_playbook_format_error:
                    raise
            except TaskFormatError:
                if not self.skip_task_format_error:
                    raise
            except Exception:
                logger.exception(f"failed to load the role {role_name}")
                return None
        elif ld.target_type == LoadType.PROJECT:
            repo_name = ld.target_name
            try:
                obj = load_repository(
                    path=ld.path,
                    basedir=ld.path,
                    use_ansible_doc=self.use_ansible_doc,
                    skip_playbook_format_error=self.skip_playbook_format_error,
                    skip_task_format_error=self.skip_task_format_error,
                    include_test_contents=ld.include_test_contents,
                    yaml_label_list=cast("list[tuple[str, str, YAMLValue]] | None", ld.yaml_label_list),
                )
            except PlaybookFormatError:
                if not self.skip_playbook_format_error:
                    raise
            except TaskFormatError:
                if not self.skip_task_format_error:
                    raise
            except Exception:
                logger.exception(f"failed to load the project {repo_name}")
                return None
            if isinstance(obj, Repository) and obj.my_collection_name:
                collection_name = obj.my_collection_name
            if collection_name == "" and collection_name_of_project != "":
                collection_name = collection_name_of_project
        elif ld.target_type == LoadType.PLAYBOOK:
            basedir = ""
            target_playbook_path = ""
            if ld.playbook_yaml:
                target_playbook_path = ld.path
            else:
                if ld.base_dir:
                    basedir = ld.base_dir
                    target_playbook_path = ld.path.replace(basedir, "")
                    if target_playbook_path[0] == "/":
                        target_playbook_path = target_playbook_path[1:]
                else:
                    basedir, target_playbook_path = split_target_playbook_fullpath(ld.path)
            playbook_name = ld.target_name
            try:
                if ld.playbook_only:
                    obj = load_playbook(
                        path=target_playbook_path,
                        yaml_str=ld.playbook_yaml,
                        basedir=basedir,
                        skip_playbook_format_error=self.skip_playbook_format_error,
                        skip_task_format_error=self.skip_task_format_error,
                    )
                else:
                    obj = load_repository(
                        path=basedir,
                        basedir=basedir,
                        target_playbook_path=target_playbook_path,
                        use_ansible_doc=self.use_ansible_doc,
                        skip_playbook_format_error=self.skip_playbook_format_error,
                        skip_task_format_error=self.skip_task_format_error,
                        include_test_contents=ld.include_test_contents,
                    )
            except PlaybookFormatError:
                if not self.skip_playbook_format_error:
                    raise
            except TaskFormatError:
                if not self.skip_task_format_error:
                    raise
            except Exception:
                logger.exception(f"failed to load the playbook {playbook_name}")
                return None
        elif ld.target_type == LoadType.TASKFILE:
            basedir = ""
            target_taskfile_path = ""
            if ld.taskfile_yaml:
                target_taskfile_path = ld.path
            else:
                if ld.base_dir:
                    basedir = ld.base_dir
                    target_taskfile_path = ld.path.replace(basedir, "")
                    if target_taskfile_path[0] == "/":
                        target_taskfile_path = target_taskfile_path[1:]
                else:
                    basedir, target_taskfile_path = split_target_taskfile_fullpath(ld.path)
            taskfile_name = ld.target_name
            try:
                if ld.taskfile_only:
                    obj = load_taskfile(
                        path=target_taskfile_path,
                        yaml_str=ld.taskfile_yaml,
                        basedir=basedir,
                        skip_task_format_error=self.skip_task_format_error,
                    )
                else:
                    obj = load_repository(
                        path=basedir,
                        basedir=basedir,
                        target_taskfile_path=target_taskfile_path,
                        use_ansible_doc=self.use_ansible_doc,
                        skip_playbook_format_error=self.skip_playbook_format_error,
                        skip_task_format_error=self.skip_task_format_error,
                        include_test_contents=ld.include_test_contents,
                    )
            except TaskFormatError:
                if not self.skip_task_format_error:
                    raise
            except Exception:
                logger.exception(f"failed to load the taskfile {taskfile_name}")
                return None
        else:
            raise ValueError(f"unsupported type: {ld.target_type}")

        mappings: dict[str, list[list[str]]] = {
            "roles": [],
            "taskfiles": [],
            "modules": [],
            "playbooks": [],
            "files": [],
        }

        basedir = ld.path
        if ld.target_type == LoadType.PLAYBOOK:
            if ld.base_dir:
                basedir = ld.base_dir
            else:
                basedir, _ = split_target_playbook_fullpath(ld.path)
        elif ld.target_type == LoadType.TASKFILE:
            if ld.base_dir:
                basedir = ld.base_dir
            else:
                basedir, _ = split_target_taskfile_fullpath(ld.path)

        roles = []
        for role_path in ld.roles:
            try:
                r = load_role(
                    path=role_path,
                    collection_name=collection_name,
                    basedir=basedir,
                    use_ansible_doc=self.use_ansible_doc,
                    skip_playbook_format_error=self.skip_playbook_format_error,
                    skip_task_format_error=self.skip_task_format_error,
                    include_test_contents=ld.include_test_contents,
                )
                roles.append(r)
            except PlaybookFormatError:
                if not self.skip_playbook_format_error:
                    raise
            except TaskFormatError:
                if not self.skip_task_format_error:
                    raise
            except Exception as e:
                logger.debug(f"failed to load a role: {e}")
                continue
            mappings["roles"].append([role_path, r.key])

        taskfiles = [tf for r in roles for tf in r.taskfiles if r.fqcn != ld.target_name and isinstance(tf, TaskFile)]
        loaded_absolute_path_list = []
        for r in roles:
            for tf in r.taskfiles:
                if r.fqcn != ld.target_name and isinstance(tf, TaskFile):
                    loaded_absolute_path_list.append(os.path.join(basedir, r.defined_in, tf.defined_in))
        for taskfile_path in ld.taskfiles:
            try:
                abs_path = os.path.join(basedir, taskfile_path)
                if abs_path in loaded_absolute_path_list:
                    continue
                tf = load_taskfile(
                    path=taskfile_path,
                    yaml_str=ld.taskfile_yaml,
                    role_name=role_name,
                    collection_name=collection_name,
                    basedir=basedir,
                    skip_task_format_error=self.skip_task_format_error,
                )
            except TaskFormatError:
                if not self.skip_task_format_error:
                    raise
            except Exception as e:
                logger.debug(f"failed to load a taskfile: {e}")
                continue
            if tf is not None and isinstance(tf, TaskFile):
                taskfiles.append(tf)
                mappings["taskfiles"].append([taskfile_path, tf.key])

        playbooks = [p for r in roles for p in r.playbooks if isinstance(p, Playbook)]
        for playbook_path in ld.playbooks:
            p = None
            try:
                p = load_playbook(
                    path=playbook_path,
                    yaml_str=ld.playbook_yaml,
                    role_name=role_name,
                    collection_name=collection_name,
                    basedir=basedir,
                    skip_playbook_format_error=self.skip_playbook_format_error,
                    skip_task_format_error=self.skip_task_format_error,
                )
            except PlaybookFormatError:
                if not self.skip_playbook_format_error:
                    raise
            except TaskFormatError:
                if not self.skip_task_format_error:
                    raise
            except Exception as e:
                logger.debug(f"failed to load a playbook: {e}")
                continue
            if p is not None:
                playbooks.append(p)
                mappings["playbooks"].append([playbook_path, p.key])

        plays = [play for p in playbooks for play in p.plays if isinstance(play, Play)]

        tasks = [t for tf in taskfiles for t in (tf.tasks if isinstance(tf, TaskFile) else [])]
        pre_tasks_in_plays = [t for p in plays for t in (p.pre_tasks if isinstance(p, Play) else [])]
        tasks_in_plays = [t for p in plays for t in (p.tasks if isinstance(p, Play) else [])]
        post_tasks_in_plays = [t for p in plays for t in (p.post_tasks if isinstance(p, Play) else [])]
        handlers_in_plays = [t for p in plays for t in (p.handlers if isinstance(p, Play) else [])]
        tasks.extend(pre_tasks_in_plays)
        tasks.extend(tasks_in_plays)
        tasks.extend(post_tasks_in_plays)
        tasks.extend(handlers_in_plays)

        modules = [m for r in roles for m in r.modules if isinstance(m, Module)]
        module_specs = {}
        if self.use_ansible_doc:
            module_specs = get_module_specs_by_ansible_doc(
                module_files=[fpath for fpath in ld.modules],
                fqcn_prefix=collection_name,
                search_path=ld.path,
            )

        for module_path in ld.modules:
            m = None
            try:
                m = load_module(
                    module_file_path=module_path,
                    role_name=role_name,
                    collection_name=collection_name,
                    basedir=basedir,
                    use_ansible_doc=self.use_ansible_doc,
                    module_specs=module_specs,
                )
            except Exception as e:
                logger.debug(f"failed to load a module: {e}")
                continue
            if m is not None:
                modules.append(m)
                mappings["modules"].append([module_path, m.key])

        files = []
        for file_path in ld.files:
            f = None
            try:
                label = "others"
                if ld.yaml_label_list:
                    yaml_labels = ld.yaml_label_list
                    for item in yaml_labels:
                        if isinstance(item, list | tuple) and len(item) >= 2:
                            _fpath, _label = str(item[0]), str(item[1])
                            if _fpath == file_path:
                                label = _label
                                break
                f = load_file(
                    path=file_path,
                    basedir=basedir,
                    label=label,
                    role_name=role_name,
                    collection_name=collection_name,
                )
            except Exception as e:
                logger.debug(f"failed to load a file: {e}")
                continue
            if f is not None:
                files.append(f)
                mappings["files"].append([file_path, f.key])

        logger.debug(f"roles: {len(roles)}")
        logger.debug(f"taskfiles: {len(taskfiles)}")
        logger.debug(f"modules: {len(modules)}")
        logger.debug(f"playbooks: {len(playbooks)}")
        logger.debug(f"plays: {len(plays)}")
        logger.debug(f"tasks: {len(tasks)}")
        logger.debug(f"files: {len(files)}")

        collections = []
        projects = []
        if ld.target_type == LoadType.COLLECTION:
            collections = [obj]
        elif (
            ld.target_type == LoadType.ROLE
            or ld.target_type == LoadType.PLAYBOOK
            or ld.target_type == LoadType.TASKFILE
        ):
            pass
        elif ld.target_type == LoadType.PROJECT:
            projects = [obj]

        if len(collections) > 0 and obj is not None:
            collections = [obj.children_to_key()]
        if len(projects) > 0 and obj is not None:
            projects = [obj.children_to_key()]
        if len(roles) > 0:
            roles = [r.children_to_key() for r in roles if isinstance(r, Role)]
        if len(taskfiles) > 0:
            taskfiles = [tf.children_to_key() for tf in taskfiles if isinstance(tf, TaskFile)]
        if len(modules) > 0:
            modules = [m.children_to_key() for m in modules if isinstance(m, Module)]
        if len(playbooks) > 0:
            playbooks = [p.children_to_key() for p in playbooks if isinstance(p, Playbook)]
        if len(plays) > 0:
            plays = [p.children_to_key() for p in plays if isinstance(p, Play)]
        if len(tasks) > 0:
            tasks = [t.children_to_key() for t in tasks if isinstance(t, Task)]
        if len(files) > 0:
            files = [f.children_to_key() for f in files if isinstance(f, File)]

        # save mappings (Load stores as list for JSON; structure is [path, key] pairs)
        ld.roles = cast(list[str], mappings["roles"])
        ld.taskfiles = cast(list[str], mappings["taskfiles"])
        ld.playbooks = cast(list[str], mappings["playbooks"])
        ld.modules = cast(list[str], mappings["modules"])
        ld.files = cast(list[str], mappings["files"])

        definitions = {
            "collections": collections,
            "projects": projects,
            "roles": roles,
            "taskfiles": taskfiles,
            "modules": modules,
            "playbooks": playbooks,
            "plays": plays,
            "tasks": tasks,
            "files": files,
        }

        return cast(tuple[dict[str, list[Object]], Load], (definitions, ld))

    @classmethod
    def restore_definition_objects(cls: type[Parser], input_dir: str) -> tuple[dict[str, list[Object]], Load]:
        """Load previously dumped definition objects from JSON files in a directory.

        Args:
            input_dir: Directory containing collections.json, roles.json, etc.

        Returns:
            Tuple of (definitions dict, Load from mappings.json).

        Raises:
            ValueError: If mappings.json not found.
        """
        collections = _load_object_list(Collection, os.path.join(input_dir, "collections.json"))

        # TODO: only repository?
        projects = _load_object_list(Repository, os.path.join(input_dir, "projects.json"))

        roles = _load_object_list(Role, os.path.join(input_dir, "roles.json"))

        taskfiles = _load_object_list(TaskFile, os.path.join(input_dir, "taskfiles.json"))

        modules = _load_object_list(Module, os.path.join(input_dir, "modules.json"))

        playbooks = _load_object_list(Playbook, os.path.join(input_dir, "playbooks.json"))

        plays = _load_object_list(Play, os.path.join(input_dir, "plays.json"))

        tasks = _load_object_list(Task, os.path.join(input_dir, "tasks.json"))

        definitions = {
            "collections": collections,
            "projects": projects,
            "roles": roles,
            "taskfiles": taskfiles,
            "modules": modules,
            "playbooks": playbooks,
            "plays": plays,
            "tasks": tasks,
        }

        mapping_path = os.path.join(input_dir, "mappings.json")
        if not os.path.exists(mapping_path):
            raise ValueError(f"file not found: {mapping_path}")
        ld = cast(Load, Load.from_json(Path(mapping_path).read_text()))
        return definitions, ld

    @classmethod
    def dump_definition_objects(
        cls: type[Parser], output_dir: str, definitions: dict[str, list[Object]], ld: Load
    ) -> None:
        """Write definition objects and Load to JSON files in a directory.

        Args:
            output_dir: Directory to write JSON files.
            definitions: Dict mapping object type names to lists of Object.
            ld: Load object to write as mappings.json.
        """
        collections = definitions.get("collections", [])
        if len(collections) > 0:
            _dump_object_list(collections, os.path.join(output_dir, "collections.json"))
        projects = definitions.get("projects", [])
        if len(projects) > 0:
            _dump_object_list(projects, os.path.join(output_dir, "projects.json"))

        roles = definitions.get("roles", [])
        if len(roles) > 0:
            _dump_object_list(roles, os.path.join(output_dir, "roles.json"))

        taskfiles = definitions.get("taskfiles", [])
        if len(taskfiles) > 0:
            _dump_object_list(taskfiles, os.path.join(output_dir, "taskfiles.json"))

        modules = definitions.get("modules", [])
        if len(modules) > 0:
            _dump_object_list(modules, os.path.join(output_dir, "modules.json"))

        playbooks = definitions.get("playbooks", [])
        if len(playbooks) > 0:
            _dump_object_list(playbooks, os.path.join(output_dir, "playbooks.json"))

        plays = definitions.get("plays", [])
        if len(plays) > 0:
            _dump_object_list(plays, os.path.join(output_dir, "plays.json"))

        tasks = definitions.get("tasks", [])
        if len(tasks) > 0:
            _dump_object_list(tasks, os.path.join(output_dir, "tasks.json"))

        mapping_path = os.path.join(output_dir, "mappings.json")
        Path(mapping_path).write_text(ld.dump())


def _dump_object_list(obj_list: list[Object], output_path: str) -> None:
    """Write a list of Object instances to a file as newline-delimited JSON.

    Args:
        obj_list: List of Object instances with dump() method.
        output_path: Path to write the output file.
    """
    tmp_obj_list = copy.deepcopy(obj_list)
    lines = []
    for i in range(len(tmp_obj_list)):
        lines.append(tmp_obj_list[i].dump())
    Path(output_path).write_text("\n".join(lines))
    return


def _load_object_list(cls: type[Object], input_path: str) -> list[Object]:
    """Load Object instances from newline-delimited JSON file.

    Args:
        cls: Object subclass with from_json class method.
        input_path: Path to the JSON file.

    Returns:
        List of Object instances.
    """
    obj_list: list[Object] = []
    if os.path.exists(input_path):
        with open(input_path) as f:
            for line in f:
                obj = cls.from_json(line)
                obj_list.append(cast(Object, obj))
    return obj_list


def load_name2target_name(path: str) -> str:
    """Extract target name from a load JSON filename (e.g. load-foo.json -> foo).

    Args:
        path: Path to a load JSON file.

    Returns:
        Target name with "load-" prefix stripped.
    """
    filename = os.path.basename(path)
    parts = os.path.splitext(filename)
    prefix = "load-"
    target_name = parts[0]
    if target_name.startswith(prefix):
        target_name = target_name[len(prefix) :]
    return target_name
