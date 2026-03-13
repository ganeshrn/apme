# Test helpers for colocated native rule tests. Build minimal Python context/task objects.

from typing import cast

from apme_engine.engine.models import (
    AnsibleRunContext,
    ExecutableType,
    Role,
    RoleCall,
    RunTarget,
    Task,
    TaskCall,
    YAMLDict,
)


def make_task_spec(
    name: str | None = None,
    module: str = "",
    executable: str = "",
    executable_type: str = ExecutableType.MODULE_TYPE,
    resolved_name: str = "",
    options: YAMLDict | None = None,
    module_options: YAMLDict | None = None,
    defined_in: str = "tasks/main.yml",
    line_num_in_file: list[int] | None = None,
    key: str | None = None,
    possible_candidates: list[tuple[str, str]] | None = None,
) -> Task:
    """Build a minimal Task spec for rule tests."""
    # Key must be "type rest" (space-separated) for set_call_object_key.
    if key is None:
        key = "task task:{}:[0]".format(defined_in.replace("/", ":"))
    spec = Task(
        name=name or "",
        module=module or executable or "",
        executable=executable or module or "",
        executable_type=executable_type,
        resolved_name=resolved_name or module or executable or "",
        options=cast(YAMLDict, options or {}),
        module_options=cast(YAMLDict, module_options or {}),
        defined_in=defined_in,
        line_num_in_file=line_num_in_file or [1, 2],
        key=key,
    )
    if possible_candidates is not None:
        spec.possible_candidates = possible_candidates
    return spec


def make_task_call(spec: Task) -> TaskCall:
    """Build a TaskCall from a Task spec."""
    return cast(TaskCall, TaskCall.from_spec(spec, None, 0))


def make_role_spec(
    name: str = "",
    defined_in: str = "roles/foo/meta/main.yml",
    key: str | None = None,
    metadata: YAMLDict | None = None,
) -> Role:
    """Build a minimal Role spec for rule tests."""
    # Key must be "type rest" (space-separated) for set_call_object_key.
    if key is None:
        key = "role role:{}".format(name or "test")
    return Role(
        name=name,
        defined_in=defined_in,
        key=key,
        metadata=metadata if metadata is not None else {},
    )


def make_role_call(spec: Role) -> RoleCall:
    """Build a RoleCall from a Role spec."""
    return cast(RoleCall, RoleCall.from_spec(spec, None, 0))


def make_context(
    current: RunTarget | None,
    sequence: list[RunTarget] | None = None,
) -> AnsibleRunContext:
    """Build an AnsibleRunContext with current set (task or role). Optionally set sequence for is_begin/is_end."""
    ctx = AnsibleRunContext(root_key="playbook.yml")
    ctx.current = current
    if sequence is not None:
        ctx.sequence.items = list(sequence)
    return ctx
