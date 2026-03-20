"""Safe glob implementation that avoids symlink-induced infinite loops."""

from __future__ import annotations

import os
import re


# glob.glob() may cause infinite loop when there is symlink loop
# safe_glob() support the case by `followlink=False` option as default
def safe_glob(
    patterns: str | list[str],
    root_dir: str = "",
    recursive: bool = True,
    type: list[str] | None = None,
    followlinks: bool = False,
) -> list[str]:
    """Match file paths against glob patterns without symlink-induced infinite loops.

    Uses os.walk with followlinks=False by default to avoid infinite loops when
    symlink cycles exist. Supports both recursive and non-recursive matching.

    Args:
        patterns: Glob pattern(s) to match. May be a single pattern or list.
        root_dir: Root directory for search. If empty, derived from pattern.
        recursive: If True, use os.walk; otherwise use os.listdir.
        type: Types to include: "file", "dir", or both. Defaults to both.
        followlinks: Whether to follow symlinks during traversal.

    Returns:
        List of matched file or directory paths.

    Raises:
        ValueError: If patterns is not str or list of str.
    """
    if type is None:
        type = ["file", "dir"]
    pattern_list = []
    if isinstance(patterns, list):
        pattern_list = [p for p in patterns]
    elif isinstance(patterns, str):
        pattern_list = [patterns]
    else:
        raise ValueError("patterns for safe_glob() must be str or list of str")

    matched_files = []
    for pattern in pattern_list:
        # if root dir is not specified, automatically decide it with pattern
        # e.g.) pattern "testdir1/testdir2/*.py"
        #       --> root_dir "testdir1/testdir2"
        root_dir_for_this_pattern = ""
        if root_dir == "":
            root_cand = pattern.split("*")[0]
            root_dir_for_this_pattern = (
                root_cand[:-1] if root_cand.endswith("/") else "/".join(root_cand.split("/")[:-1])
            )
        else:
            root_dir_for_this_pattern = root_dir

        # if recusive, use os.walk to search files recursively
        if recursive:
            for dirpath, dirs, files in os.walk(root_dir_for_this_pattern, followlinks=followlinks):
                if "dir" in type:
                    for dir_name in dirs:
                        dpath = os.path.join(dirpath, dir_name)
                        dpath = os.path.normpath(dpath)
                        if dpath in matched_files:
                            continue
                        if pattern_match(pattern, dpath):
                            matched_files.append(dpath)
                if "file" in type:
                    for file in files:
                        fpath = os.path.join(dirpath, file)
                        fpath = os.path.normpath(fpath)
                        if fpath in matched_files:
                            continue
                        if pattern_match(pattern, fpath):
                            matched_files.append(fpath)
        else:
            # otherwise, just use os.listdir to avoid
            # unnecessary loading time of os.walk
            all_found = os.listdir(root_dir_for_this_pattern)
            for fname in all_found:
                fpath = os.path.join(root_dir, fname)
                fpath = os.path.normpath(fpath)
                if fpath in matched_files:
                    continue
                dirs = []
                files = []
                if os.path.isdir(fpath):
                    dirs.append(fpath)
                else:
                    files.append(fpath)
                if "dir" in type:
                    for fpath in dirs:
                        if pattern_match(pattern, fpath):
                            matched_files.append(fpath)
                if "file" in type:
                    for fpath in files:
                        if pattern_match(pattern, fpath):
                            matched_files.append(fpath)
    return matched_files


def pattern_match(pattern: str, fpath: str) -> re.Match[str] | None:
    """Check if a file path matches a glob-style pattern.

    Converts glob patterns to regex: **/ matches any path segment, * matches
    any characters except slash within a segment.

    Args:
        pattern: Glob pattern (e.g. "**/*.py", "testdir/*.py").
        fpath: File path to test against the pattern.

    Returns:
        Match object if path matches, None otherwise.
    """
    pattern = pattern.replace("**/", "<ANY>")
    pattern = pattern.replace("*", "[^/]*")
    pattern = pattern.replace("<ANY>", ".*")
    regex_pattern = rf"^{pattern}$"
    result = re.match(regex_pattern, fpath)
    return result
