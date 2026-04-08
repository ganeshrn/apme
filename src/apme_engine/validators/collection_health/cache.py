"""Persistent cache for collection health scan results (ADR-051).

Collection content is immutable at a given FQCN+version, but findings
also depend on the scan schema (engine version, curated rule-set hash).
Cache entries are keyed on ``(fqcn, version, cache_schema)`` and stored
as JSON files under ``~/.apme-data/collection-health/``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import cast

logger = logging.getLogger("apme.collection_health")

_CACHE_DIR = Path(os.environ.get("APME_DATA_DIR", "~/.apme-data")).expanduser() / "collection-health"


def _cache_key(fqcn: str, version: str, cache_schema: str) -> str:
    """Build a filesystem-safe cache key.

    Args:
        fqcn: Collection fully-qualified name.
        version: Collection version string.
        cache_schema: Opaque schema identifier (engine version + rule hash).

    Returns:
        SHA-256 hex digest used as the cache filename.
    """
    raw = f"{fqcn}|{version}|{cache_schema}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached(
    fqcn: str,
    version: str,
    cache_schema: str,
) -> list[dict[str, str | int | list[int] | bool | None]] | None:
    """Look up cached findings for a collection.

    Args:
        fqcn: Collection fully-qualified name.
        version: Collection version string.
        cache_schema: Opaque schema identifier.

    Returns:
        Cached violation dicts, or None if no valid cache entry exists.
    """
    key = _cache_key(fqcn, version, cache_schema)
    path = _CACHE_DIR / f"{key}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return None
        if data.get("schema") != cache_schema:
            return None
        findings = data.get("findings")
        if not isinstance(findings, list):
            return None
        return cast(list[dict[str, str | int | list[int] | bool | None]], findings)
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Cache read error for %s %s: %s", fqcn, version, exc)
        return None


def put_cached(
    fqcn: str,
    version: str,
    cache_schema: str,
    findings: list[dict[str, str | int | list[int] | bool | None]],
) -> None:
    """Store findings in the persistent cache.

    Args:
        fqcn: Collection fully-qualified name.
        version: Collection version string.
        cache_schema: Opaque schema identifier.
        findings: Violation dicts to cache.
    """
    key = _cache_key(fqcn, version, cache_schema)
    path = _CACHE_DIR / f"{key}.json"
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "fqcn": fqcn,
            "version": version,
            "schema": cache_schema,
            "findings": findings,
        }
        content = (json.dumps(payload, indent=2) + "\n").encode()
        fd, tmp_path = tempfile.mkstemp(dir=str(_CACHE_DIR), suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp_path, str(path))
    except OSError as exc:
        logger.warning("Cache write error for %s %s: %s", fqcn, version, exc)


@lru_cache(maxsize=1)
def compute_cache_schema(rule_ids: tuple[str, ...]) -> str:
    """Compute the cache schema identifier from the curated rule set.

    The schema changes whenever the curated rule list changes, which
    invalidates all cached entries.

    Args:
        rule_ids: Sorted tuple of curated rule IDs.

    Returns:
        Hex digest representing the current scan schema.
    """
    from importlib.metadata import version as pkg_version

    try:
        engine_version = pkg_version("apme-engine")
    except Exception:
        engine_version = "0.0.0-dev"

    raw = f"v2|{engine_version}|{'|'.join(rule_ids)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
