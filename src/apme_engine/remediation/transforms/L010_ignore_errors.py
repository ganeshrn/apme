"""L010: Replace ignore_errors with failed_when: false."""

from __future__ import annotations

from apme_engine.engine.models import ViolationDict
from apme_engine.remediation.structured import StructuredFile
from apme_engine.remediation.transforms._helpers import violation_line_to_int


def fix_ignore_errors(sf: StructuredFile, violation: ViolationDict) -> bool:
    """Replace ``ignore_errors: true`` with ``failed_when: false``.

    Note that these are not semantically identical: ``ignore_errors: true``
    allows a task to fail but still records a failed result (which can
    influence follow-up logic such as ``when: result is failed``), whereas
    ``failed_when: false`` forces the task result to be treated as successful.
    This transform intentionally applies the ansible-lint ``ignore-errors``
    recommendation and may change behavior in plays that inspect failure
    status explicitly.

    Args:
        sf: Parsed YAML file to modify in-place.
        violation: Violation dict with line.

    Returns:
        True if a change was applied.
    """
    task = sf.find_task(violation_line_to_int(violation), violation)
    if task is None:
        return False

    if "ignore_errors" not in task:
        return False

    ignore_val = task["ignore_errors"]
    if ignore_val is not True:
        return False

    del task["ignore_errors"]
    if "failed_when" not in task:
        task["failed_when"] = False

    return True
