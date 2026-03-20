"""Load project/collection/role/playbook and produce load JSON."""

import contextlib
import json
import os
import pathlib
from importlib.metadata import version as _pkg_version

from .models import LoadType

collection_manifest_json = "MANIFEST.json"
role_meta_main_yml = "meta/main.yml"
role_meta_main_yaml = "meta/main.yaml"


def remove_subdirectories(dir_list: list[str]) -> list[str]:
    """Remove directories that are subdirectories of another in the list.

    Args:
        dir_list: List of directory paths.

    Returns:
        Filtered list with parent paths only.

    """
    sorted_dir_list = sorted(dir_list)
    new_dir_list = []
    for i, dir in enumerate(sorted_dir_list):
        if i >= 1 and dir.startswith(sorted_dir_list[i - 1]):
            continue
        new_dir_list.append(dir)
    return new_dir_list


def trim_suffix(txt: str, suffix_patterns: str | list[str] | None = None) -> str:
    """Remove the first matching suffix from txt.

    Args:
        txt: String to trim.
        suffix_patterns: Single suffix or list of suffixes to try.

    Returns:
        txt with one matching suffix removed, or unchanged if none match.

    """
    if suffix_patterns is None:
        suffix_patterns = []
    if isinstance(suffix_patterns, str):
        suffix_patterns = [suffix_patterns]
    if not isinstance(suffix_patterns, list):
        return txt
    for suffix in suffix_patterns:
        if txt.endswith(suffix):
            return txt[: -len(suffix)]
    return txt


def get_loader_version() -> str:
    """Return apme-engine package version, or empty string if unavailable.

    Returns:
        Version string from package metadata.

    """
    version = ""
    with contextlib.suppress(Exception):
        version = _pkg_version("apme-engine")
    if version != "":
        return version
    # try to get version from commit ID in source code repository
    with contextlib.suppress(Exception):
        # TODO: consider how to get git version if it is needed
        _ = pathlib.Path(__file__).parent.resolve()
        # repo = pygit2.Repository(script_dir)
        # version = repo.head.target
    return version


def get_target_name(target_type: str, target_path: str) -> str:
    """Derive a target name from type and path (project/collection/role/playbook).

    Args:
        target_type: One of LoadType.PROJECT, COLLECTION, ROLE, PLAYBOOK.
        target_path: Path to the target.

    Returns:
        Human-readable target name.

    """
    target_name = ""
    if target_type == LoadType.PROJECT:
        project_name = os.path.normpath(target_path).split("/")[-1]
        target_name = project_name
    elif target_type == LoadType.COLLECTION:
        meta_file = os.path.join(target_path, collection_manifest_json)
        metadata = {}
        with open(meta_file) as file:
            metadata = json.load(file)
        collection_namespace = metadata.get("collection_info", {}).get("namespace", "")
        collection_name = metadata.get("collection_info", {}).get("name", "")
        target_name = f"{collection_namespace}.{collection_name}"
    elif target_type == LoadType.ROLE:
        # any better approach?
        target_name = target_path.split("/")[-1]
    elif target_type == LoadType.PLAYBOOK:
        target_name = filepath_to_target_name(target_path)
    return target_name


def filepath_to_target_name(filepath: str) -> str:
    """Convert a file path to a safe target name (spaces/slashes/dots replaced).

    Args:
        filepath: Path string.

    Returns:
        Sanitized string for use as a target name.

    """
    return filepath.translate(
        str.maketrans({" ": "___", "/": "---", ".": "_dot_"})  # type: ignore[arg-type]
    )
