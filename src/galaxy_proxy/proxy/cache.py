"""Wheel and metadata cache backed by XDG_CACHE_HOME."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


def _default_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "ansible-collection-proxy"


@dataclass
class CachedMetadata:
    """Cached Galaxy version listing for a collection."""

    versions: list[str]
    fetched_at: float


class ProxyCache:
    """Manages cached wheels and version metadata on disk."""

    def __init__(self, cache_dir: Path | None = None, metadata_ttl: float = 600.0) -> None:
        """Initialise cache directories under *cache_dir* (or XDG default)."""
        self.root = cache_dir or _default_cache_dir()
        self.wheels_dir = self.root / "wheels"
        self.metadata_dir = self.root / "metadata"
        self.metadata_ttl = metadata_ttl

        self.wheels_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

    def get_wheel(self, filename: str) -> bytes | None:
        """Return cached wheel bytes, or None if not cached."""
        path = self.wheels_dir / filename
        if path.exists():
            return path.read_bytes()
        return None

    def put_wheel(self, filename: str, data: bytes) -> Path:
        """Write a wheel to the cache and return its path."""
        path = self.wheels_dir / filename
        path.write_bytes(data)
        return path

    def wheel_path(self, filename: str) -> Path | None:
        """Return the path to a cached wheel if it exists."""
        path = self.wheels_dir / filename
        return path if path.exists() else None

    def get_metadata(self, namespace: str, name: str) -> CachedMetadata | None:
        """Return cached version listing if fresh, None otherwise."""
        path = self.metadata_dir / f"{namespace}-{name}.json"
        if not path.exists():
            return None

        data = json.loads(path.read_text())
        cached = CachedMetadata(
            versions=data["versions"],
            fetched_at=data["fetched_at"],
        )

        age = time.time() - cached.fetched_at
        if age > self.metadata_ttl:
            return None

        return cached

    def put_metadata(self, namespace: str, name: str, versions: list[str]) -> None:
        """Cache a version listing for a collection."""
        path = self.metadata_dir / f"{namespace}-{name}.json"
        data = {
            "versions": versions,
            "fetched_at": time.time(),
        }
        path.write_text(json.dumps(data, indent=2))

    def clear(self) -> None:
        """Remove all cached files."""
        import shutil

        if self.root.exists():
            shutil.rmtree(self.root)
        self.wheels_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
