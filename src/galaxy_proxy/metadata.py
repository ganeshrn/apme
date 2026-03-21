"""Translate galaxy.yml metadata into Python wheel metadata files."""

from __future__ import annotations

import csv
import hashlib
import io
from typing import TYPE_CHECKING

from galaxy_proxy.naming import fqcn_to_python

if TYPE_CHECKING:
    from pathlib import Path


def galaxy_to_metadata(galaxy: dict) -> str:
    """Generate PEP 566 METADATA content from parsed galaxy.yml fields.

    Returns the full text of the METADATA file suitable for inclusion in a
    .dist-info directory.
    """
    namespace = galaxy["namespace"]
    name = galaxy["name"]
    version = galaxy["version"]

    lines = [
        "Metadata-Version: 2.1",
        f"Name: ansible-collection-{namespace}-{name}",
        f"Version: {version}",
    ]

    if summary := galaxy.get("description"):
        lines.append(f"Summary: {summary}")

    authors = galaxy.get("authors", [])
    if authors:
        lines.append(f"Author: {authors[0]}")

    if license_val := galaxy.get("license"):
        if isinstance(license_val, list):
            license_val = license_val[0] if license_val else ""
        lines.append(f"License: {license_val}")

    if homepage := galaxy.get("homepage") or galaxy.get("repository"):
        lines.append(f"Home-page: {homepage}")

    lines.append("Requires-Python: >=3.10")

    if requires_ansible := galaxy.get("requires_ansible"):
        lines.append(f"Requires-Dist: ansible-core{requires_ansible}")

    for dep_fqcn, version_spec in galaxy.get("dependencies", {}).items():
        python_name = fqcn_to_python(dep_fqcn)
        if version_spec and version_spec != "*":
            lines.append(f"Requires-Dist: {python_name}{version_spec}")
        else:
            lines.append(f"Requires-Dist: {python_name}")

    return "\n".join(lines) + "\n"


def galaxy_to_metadata_with_python_deps(
    galaxy: dict,
    requirements_txt: str | None = None,
) -> str:
    """Generate METADATA including Python deps from requirements.txt."""
    base = galaxy_to_metadata(galaxy)
    if not requirements_txt:
        return base

    extra_lines = []
    for line in requirements_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        extra_lines.append(f"Requires-Dist: {line}")

    if extra_lines:
        return base + "\n".join(extra_lines) + "\n"
    return base


def generate_wheel_file() -> str:
    """Generate the static WHEEL metadata file."""
    return "Wheel-Version: 1.0\nGenerator: ansible-collection-proxy\nRoot-Is-Purelib: true\nTag: py3-none-any\n"


def generate_top_level(namespace: str) -> str:
    """Generate top_level.txt listing the top-level package."""
    return "ansible_collections\n"


def generate_record(file_entries: list[tuple[str, str, int]]) -> str:
    """Generate RECORD content from a list of (path, sha256_hex, size) tuples.

    The RECORD file's own entry is appended with empty hash and size fields
    per the wheel specification.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for path, digest, size in file_entries:
        writer.writerow([path, f"sha256={digest}", str(size)])
    # RECORD's own entry: no hash, no size
    writer.writerow(["", "", ""])
    return buf.getvalue()


def sha256_digest(data: bytes) -> str:
    """Return hex SHA256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return hex SHA256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
