from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

from shellcraft.net import is_port_free, pick_local_port


def test_is_port_free_returns_true_when_port_available() -> None:
    with patch("shellcraft.net.socket.socket") as ms:
        instance = MagicMock()
        instance.__enter__ = lambda _s: instance
        instance.__exit__ = MagicMock(return_value=False)
        instance.bind = MagicMock()
        ms.return_value = instance
        result = is_port_free(9999)
    assert result is True


def test_is_port_free_returns_false_when_port_in_use() -> None:
    with patch("shellcraft.net.socket.socket") as ms:
        instance = MagicMock()
        instance.__enter__ = lambda _s: instance
        instance.__exit__ = MagicMock(return_value=False)
        instance.bind = MagicMock(side_effect=OSError("address in use"))
        ms.return_value = instance
        result = is_port_free(80)
    assert result is False


def test_is_port_free_returns_false_when_port_in_use_on_ipv6() -> None:
    def _fake_socket(family: int, socktype: int) -> MagicMock:  # noqa: ARG001
        instance = MagicMock()
        instance.__enter__ = lambda _s: instance
        instance.__exit__ = MagicMock(return_value=False)
        if family == socket.AF_INET:
            instance.bind = MagicMock()
        elif family == socket.AF_INET6:
            instance.bind = MagicMock(side_effect=OSError("address in use"))
        else:
            raise AssertionError(f"unexpected family: {family}")
        return instance

    with patch("shellcraft.net.socket.socket", side_effect=_fake_socket):
        result = is_port_free(8080)

    assert result is False


def test_pick_local_port_returns_preferred_when_free() -> None:
    with patch("shellcraft.net.is_port_free", return_value=True):
        port = pick_local_port(preferred=9000)
    assert port == 9000


def test_pick_local_port_skips_preferred_when_taken() -> None:
    with patch("shellcraft.net.is_port_free", return_value=False):
        port = pick_local_port(preferred=9000)
    assert port != 9000
    assert 1024 < port < 65536


def test_pick_local_port_skips_blocked_ports() -> None:
    with patch("shellcraft.net.is_port_free", return_value=True):
        port = pick_local_port(preferred=9000, blocked={9000})
    assert port != 9000
    assert port not in {9000}
    assert 1024 <= port <= 65535


def test_pick_local_port_returns_preferred_not_in_blocked() -> None:
    with patch("shellcraft.net.is_port_free", return_value=True):
        port = pick_local_port(preferred=9001, blocked={9000})
    assert port == 9001
