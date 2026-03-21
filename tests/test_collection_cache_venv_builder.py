"""Tests for collection cache venv builder."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apme_engine.collection_cache.venv_builder import (
    _proxy_url,
    _resolve_collection_path,
    _spec_to_pip,
    _venv_key,
    _venv_site_packages,
    build_venv,
    get_venv_python,
)


class TestVenvKey:
    """Tests for _venv_key."""

    def test_stable_for_same_inputs(self) -> None:
        """Same version and collections produce same key."""
        assert _venv_key("2.15.0", ["ansible.builtin.debug"]) == _venv_key("2.15.0", ["ansible.builtin.debug"])

    def test_different_version_different_key(self) -> None:
        """Different ansible-core versions produce different keys."""
        k1 = _venv_key("2.14.0", [])
        k2 = _venv_key("2.15.0", [])
        assert k1 != k2

    def test_different_collections_different_key(self) -> None:
        """Different collection lists produce different keys."""
        k1 = _venv_key("2.15.0", ["a.b"])
        k2 = _venv_key("2.15.0", ["a.b", "c.d"])
        assert k1 != k2

    def test_order_of_collections_irrelevant(self) -> None:
        """Collection order does not affect key."""
        k1 = _venv_key("2.15.0", ["c.d", "a.b"])
        k2 = _venv_key("2.15.0", ["a.b", "c.d"])
        assert k1 == k2


class TestVenvSitePackages:
    """Tests for _venv_site_packages."""

    def test_returns_site_packages_under_lib_python(self, tmp_path: Path) -> None:
        """Returns site-packages path under lib/pythonX.Y.

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        (tmp_path / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
        assert _venv_site_packages(tmp_path) == tmp_path / "lib" / "python3.12" / "site-packages"

    def test_creates_site_packages_if_missing(self, tmp_path: Path) -> None:
        """Creates site-packages dir if lib/pythonX.Y exists.

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        (tmp_path / "lib" / "python3.11").mkdir(parents=True)
        out = _venv_site_packages(tmp_path)
        assert out.is_dir()
        assert out == tmp_path / "lib" / "python3.11" / "site-packages"

    def test_no_lib_raises(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when no lib dir.

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        with pytest.raises(FileNotFoundError, match="no lib dir"):
            _venv_site_packages(tmp_path)


class TestResolveCollectionPath:
    """Tests for _resolve_collection_path."""

    def test_returns_none_when_not_in_cache(self, tmp_path: Path) -> None:
        """Returns None when collection not in cache.

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        assert _resolve_collection_path("namespace.collection", tmp_path) is None

    def test_returns_path_when_in_galaxy_cache(self, tmp_path: Path) -> None:
        """Returns path when collection exists in galaxy cache.

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        ac = tmp_path / "galaxy" / "ansible_collections" / "ns" / "coll"
        ac.mkdir(parents=True)
        path = _resolve_collection_path("ns.coll", tmp_path)
        assert path == ac


class TestGetVenvPython:
    """Tests for get_venv_python."""

    def test_returns_bin_python_on_unix(self, tmp_path: Path) -> None:
        """Returns bin/python on Unix.

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").touch()
        assert get_venv_python(tmp_path) == tmp_path / "bin" / "python"

    @pytest.mark.skipif(os.name != "nt", reason="Windows only")  # type: ignore[untyped-decorator]
    def test_returns_scripts_python_on_windows(self, tmp_path: Path) -> None:
        """Returns Scripts/python.exe on Windows.

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        scripts = tmp_path / "Scripts"
        scripts.mkdir()
        (scripts / "python.exe").touch()
        assert get_venv_python(tmp_path) == tmp_path / "Scripts" / "python.exe"


class TestBuildVenv:
    """Tests for build_venv."""

    def test_missing_collection_raises(self, tmp_path: Path) -> None:
        """When a collection spec is not in cache, build_venv raises FileNotFoundError.

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        base = tmp_path / "v"
        base.mkdir()

        def run_side_effect(*args: object, **kwargs: object) -> object:
            cmd = list(args[0]) if args else list(kwargs.get("args", []))  # type: ignore[call-overload]
            if not cmd:
                return MagicMock(returncode=0)
            # First run: venv create (uv venv <path> or python -m venv <path>)
            if "venv" in str(cmd) or (len(cmd) >= 2 and cmd[1] == "-m" and cmd[2] == "venv"):
                venv_path = Path(cmd[-1])
                venv_path.mkdir(parents=True)
                (venv_path / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
                (venv_path / "pyvenv.cfg").write_text("[venv]")
            return MagicMock(returncode=0)

        with (
            patch("subprocess.run", side_effect=run_side_effect),
            pytest.raises(FileNotFoundError, match="Collection not in cache"),
        ):
            build_venv(
                "2.15.0",
                ["ns.missing"],
                cache_root=tmp_path,
                venvs_root=base,
            )

    @pytest.mark.integration  # type: ignore[untyped-decorator]
    def test_build_venv_empty_collections(self, tmp_path: Path) -> None:
        """With no collections, build_venv creates venv with ansible-core only (needs network).

        Args:
            tmp_path: Pytest temporary directory fixture.

        """
        venv_root = build_venv(
            "2.15.0",
            [],
            cache_root=tmp_path,
            venvs_root=tmp_path / "venvs",
        )
        assert venv_root.is_dir()
        assert (venv_root / "pyvenv.cfg").is_file()
        py = get_venv_python(venv_root)
        assert py.is_file()
        ac = _venv_site_packages(venv_root) / "ansible_collections"
        assert ac.is_dir()


class TestSpecToPip:
    """Tests for _spec_to_pip."""

    def test_bare_spec(self) -> None:
        """Bare namespace.collection becomes ansible-collection-ns-coll."""
        assert _spec_to_pip("ansible.posix") == "ansible-collection-ansible-posix"

    def test_versioned_spec(self) -> None:
        """namespace.collection:version becomes ansible-collection-ns-coll==version."""
        assert _spec_to_pip("community.general:9.0.0") == "ansible-collection-community-general==9.0.0"

    def test_whitespace_in_version(self) -> None:
        """Trailing whitespace in version is stripped."""
        assert _spec_to_pip("ansible.utils:4.1.0 ") == "ansible-collection-ansible-utils==4.1.0"

    def test_empty_version_after_colon(self) -> None:
        """Colon with no version is treated as bare spec."""
        assert _spec_to_pip("ansible.posix:") == "ansible-collection-ansible-posix"


class TestProxyUrl:
    """Tests for _proxy_url."""

    def test_returns_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when APME_GALAXY_PROXY_URL is not set."""
        monkeypatch.delenv("APME_GALAXY_PROXY_URL", raising=False)
        assert _proxy_url() is None

    def test_returns_none_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when APME_GALAXY_PROXY_URL is empty/whitespace."""
        monkeypatch.setenv("APME_GALAXY_PROXY_URL", "  ")
        assert _proxy_url() is None

    def test_returns_url_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns the URL when APME_GALAXY_PROXY_URL is set."""
        monkeypatch.setenv("APME_GALAXY_PROXY_URL", "http://localhost:8765")
        assert _proxy_url() == "http://localhost:8765"


class TestVenvKeyProxyMarker:
    """Tests that _venv_key differs when proxy is active."""

    def test_proxy_produces_different_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same inputs produce different keys with/without proxy."""
        monkeypatch.delenv("APME_GALAXY_PROXY_URL", raising=False)
        k_no_proxy = _venv_key("2.18.0", ["ansible.posix"])

        monkeypatch.setenv("APME_GALAXY_PROXY_URL", "http://localhost:8765")
        k_with_proxy = _venv_key("2.18.0", ["ansible.posix"])

        assert k_no_proxy != k_with_proxy

    def test_proxy_key_stable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Proxy key is stable across calls."""
        monkeypatch.setenv("APME_GALAXY_PROXY_URL", "http://localhost:8765")
        k1 = _venv_key("2.18.0", ["ansible.posix"])
        k2 = _venv_key("2.18.0", ["ansible.posix"])
        assert k1 == k2


class TestBuildVenvProxyPath:
    """Tests for build_venv when APME_GALAXY_PROXY_URL is set."""

    def _mock_subprocess_run(self, *args: object, **kwargs: object) -> MagicMock:
        """Mock subprocess.run that creates venv structure and records pip install calls."""
        cmd = list(args[0]) if args else list(kwargs.get("args", []))  # type: ignore[call-overload]
        if not cmd:
            return MagicMock(returncode=0)
        if "venv" in str(cmd[0:3]):
            venv_path = Path(cmd[-1])
            venv_path.mkdir(parents=True, exist_ok=True)
            (venv_path / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
            (venv_path / "pyvenv.cfg").write_text("[venv]")
            (venv_path / "bin").mkdir(parents=True, exist_ok=True)
            (venv_path / "bin" / "python").touch()
        self.subprocess_calls.append(cmd)
        return MagicMock(returncode=0)

    def setup_method(self) -> None:
        self.subprocess_calls: list[list[str]] = []

    def test_proxy_path_calls_uv_pip_install_with_extra_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When proxy is set, build_venv uses uv pip install --extra-index-url."""
        monkeypatch.setenv("APME_GALAXY_PROXY_URL", "http://localhost:8765")

        with patch("subprocess.run", side_effect=self._mock_subprocess_run):
            with patch("apme_engine.collection_cache.venv_builder._uv_available", return_value=True):
                build_venv(
                    "2.18.0",
                    ["ansible.posix", "community.general:9.0.0"],
                    cache_root=tmp_path,
                    venvs_root=tmp_path / "venvs",
                )

        pip_calls = [c for c in self.subprocess_calls if "--extra-index-url" in c]
        assert len(pip_calls) == 1
        pip_cmd = pip_calls[0]
        assert "http://localhost:8765/simple/" in pip_cmd
        assert "ansible-collection-ansible-posix" in pip_cmd
        assert "ansible-collection-community-general==9.0.0" in pip_cmd

    def test_proxy_path_skips_symlink_logic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When proxy is set, build_venv does NOT call _resolve_collection_path."""
        monkeypatch.setenv("APME_GALAXY_PROXY_URL", "http://localhost:8765")

        with (
            patch("subprocess.run", side_effect=self._mock_subprocess_run),
            patch("apme_engine.collection_cache.venv_builder._uv_available", return_value=True),
            patch(
                "apme_engine.collection_cache.venv_builder._resolve_collection_path",
            ) as mock_resolve,
        ):
            build_venv(
                "2.18.0",
                ["ansible.posix"],
                cache_root=tmp_path,
                venvs_root=tmp_path / "venvs",
            )

        mock_resolve.assert_not_called()

    def test_no_proxy_still_uses_symlink_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When proxy is not set, build_venv uses the original symlink path."""
        monkeypatch.delenv("APME_GALAXY_PROXY_URL", raising=False)

        with (
            patch("subprocess.run", side_effect=self._mock_subprocess_run),
            patch("apme_engine.collection_cache.venv_builder._uv_available", return_value=True),
            pytest.raises(FileNotFoundError, match="Collection not in cache"),
        ):
            build_venv(
                "2.18.0",
                ["ansible.posix"],
                cache_root=tmp_path,
                venvs_root=tmp_path / "venvs",
            )
