"""Deterministic, reversible mapping between Galaxy FQCN and Python package names.

Convention: ``ansible.utils`` <-> ``ansible-collection-ansible-utils``

Galaxy restricts namespace and collection names to ``[a-z0-9_]``, so the
single-hyphen split after removing the prefix is always unambiguous.
"""

from __future__ import annotations

import re

PREFIX = "ansible-collection-"

_PEP503_NORMALIZE = re.compile(r"[-_.]+")


def fqcn_to_python(fqcn: str) -> str:
    """Convert a Galaxy FQCN to a PEP 503 normalized Python package name.

    >>> fqcn_to_python("ansible.utils")
    'ansible-collection-ansible-utils'
    >>> fqcn_to_python("community.general")
    'ansible-collection-community-general'
    """
    namespace, name = fqcn.split(".", 1)
    return normalize_pep503(f"{PREFIX}{namespace}-{name}")


def python_to_fqcn(package_name: str) -> tuple[str, str]:
    """Convert a Python package name back to (namespace, name).

    >>> python_to_fqcn("ansible-collection-ansible-utils")
    ('ansible', 'utils')
    >>> python_to_fqcn("ansible_collection_community_general")
    ('community', 'general')
    """
    normalized = normalize_pep503(package_name)
    if not normalized.startswith(PREFIX):
        msg = f"Package name {package_name!r} does not start with {PREFIX!r}"
        raise ValueError(msg)
    stripped = normalized.removeprefix(PREFIX)
    parts = stripped.split("-", 1)
    if len(parts) != 2:
        msg = f"Cannot extract namespace and name from {package_name!r}"
        raise ValueError(msg)
    return parts[0], parts[1]


def is_collection_package(package_name: str) -> bool:
    """Check whether a package name looks like an Ansible collection."""
    return normalize_pep503(package_name).startswith(PREFIX)


def normalize_pep503(name: str) -> str:
    """Normalize a package name per PEP 503.

    >>> normalize_pep503("Ansible_Collection.Ansible.Utils")
    'ansible-collection-ansible-utils'
    """
    return _PEP503_NORMALIZE.sub("-", name).lower()


def wheel_filename(namespace: str, name: str, version: str) -> str:
    """Build the wheel filename for a collection version.

    Wheel filenames use underscores per PEP 427.

    >>> wheel_filename("ansible", "utils", "3.1.0")
    'ansible_collection_ansible_utils-3.1.0-py3-none-any.whl'
    """
    dist_name = f"ansible_collection_{namespace}_{name}"
    return f"{dist_name}-{version}-py3-none-any.whl"


def dist_info_dirname(namespace: str, name: str, version: str) -> str:
    """Build the .dist-info directory name for a collection version.

    >>> dist_info_dirname("ansible", "utils", "3.1.0")
    'ansible_collection_ansible_utils-3.1.0.dist-info'
    """
    dist_name = f"ansible_collection_{namespace}_{name}"
    return f"{dist_name}-{version}.dist-info"
