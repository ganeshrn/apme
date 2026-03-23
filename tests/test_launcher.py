"""Tests for apme_engine.daemon.launcher port-conflict guard."""

from __future__ import annotations

import socket

import pytest

from apme_engine.daemon.launcher import _assert_ports_free, _check_port_available


def _ephemeral_port() -> int:
    """Allocate and release an ephemeral port, returning its number.

    Returns:
        An unused TCP port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def test_check_port_available_on_free_port() -> None:
    """A port that nobody is listening on should report as available."""
    port = _ephemeral_port()
    assert _check_port_available("127.0.0.1", port) is True


def test_check_port_available_on_bound_port() -> None:
    """A port that is already bound should report as unavailable."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        assert _check_port_available("127.0.0.1", port) is False
    finally:
        sock.close()


def test_assert_ports_free_raises_on_conflict() -> None:
    """_assert_ports_free raises RuntimeError when a port is in use."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        with pytest.raises(RuntimeError, match="already in use"):
            _assert_ports_free("127.0.0.1", {"test_svc": port})
    finally:
        sock.close()


def test_assert_ports_free_passes_when_clear() -> None:
    """_assert_ports_free succeeds when no ports are occupied."""
    port_a = _ephemeral_port()
    port_b = _ephemeral_port()
    _assert_ports_free("127.0.0.1", {"a": port_a, "b": port_b})
