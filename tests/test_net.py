from __future__ import annotations

import errno
import socket
from unittest.mock import MagicMock, patch

import pytest

from subprocess_toolkit.net import is_port_free, pick_local_port


def test_is_port_free_returns_true_when_port_available() -> None:
    with patch("subprocess_toolkit.net.socket.socket") as ms:
        instance = MagicMock()
        instance.__enter__ = lambda _s: instance
        instance.__exit__ = MagicMock(return_value=False)
        instance.bind = MagicMock()
        ms.return_value = instance
        result = is_port_free(9999)
    assert result is True


def test_is_port_free_returns_false_when_port_in_use() -> None:
    with patch("subprocess_toolkit.net.socket.socket") as ms:
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

    with patch("subprocess_toolkit.net.socket.socket", side_effect=_fake_socket):
        result = is_port_free(8080)

    assert result is False


def test_pick_local_port_returns_preferred_when_free() -> None:
    with patch("subprocess_toolkit.net.is_port_free", return_value=True):
        port = pick_local_port(preferred=9000)
    assert port == 9000


def test_pick_local_port_skips_preferred_when_taken() -> None:
    with patch("subprocess_toolkit.net.is_port_free", return_value=False):
        port = pick_local_port(preferred=9000)
    assert port != 9000
    assert 1024 < port < 65536


def test_pick_local_port_skips_blocked_ports() -> None:
    with patch("subprocess_toolkit.net.is_port_free", return_value=True):
        port = pick_local_port(preferred=9000, blocked={9000})
    assert port != 9000
    assert port not in {9000}
    assert 1024 <= port <= 65535


def test_pick_local_port_returns_preferred_not_in_blocked() -> None:
    with patch("subprocess_toolkit.net.is_port_free", return_value=True):
        port = pick_local_port(preferred=9001, blocked={9000})
    assert port == 9001


def _socket_returning(ipv6_bind: MagicMock) -> MagicMock:
    """Build a socket double: IPv4 bind succeeds, IPv6 bind behaves as given."""
    instance = MagicMock()
    instance.__enter__ = lambda _s: instance
    instance.__exit__ = MagicMock(return_value=False)
    instance.bind = MagicMock()

    def _fake_socket(family: int, socktype: int) -> MagicMock:  # noqa: ARG001
        if family == socket.AF_INET6:
            instance.bind = ipv6_bind
        else:
            instance.bind = MagicMock()
        return instance

    return MagicMock(side_effect=_fake_socket)


def test_is_port_free_ignores_hosts_without_an_ipv6_stack() -> None:
    """A host with no IPv6 must not look like it has every IPv6 port occupied."""
    unsupported = OSError("address family not supported")
    unsupported.errno = errno.EAFNOSUPPORT

    with patch(
        "subprocess_toolkit.net.socket.socket",
        _socket_returning(MagicMock(side_effect=unsupported)),
    ):
        assert is_port_free(8080) is True


def test_is_port_free_ignores_ipv6_when_only_the_message_says_unsupported() -> None:
    """Some platforms report an unavailable family without a sentinel errno."""
    unsupported = OSError("Address family not supported by protocol")
    unsupported.errno = errno.EACCES  # deliberately not one of the known sentinels

    with patch(
        "subprocess_toolkit.net.socket.socket",
        _socket_returning(MagicMock(side_effect=unsupported)),
    ):
        assert is_port_free(8080) is True


def test_pick_local_port_raises_when_every_candidate_is_blocked() -> None:
    """Exhausting the retry budget is a hard error, not a silently blocked port."""
    instance = MagicMock()
    instance.__enter__ = lambda _s: instance
    instance.__exit__ = MagicMock(return_value=False)
    instance.getsockname.return_value = ("127.0.0.1", 4242)

    with (
        patch("subprocess_toolkit.net.is_port_free", return_value=False),
        patch("subprocess_toolkit.net.socket.socket", return_value=instance),
        pytest.raises(RuntimeError, match="Could not find a free port"),
    ):
        pick_local_port(preferred=9000, blocked={4242}, _max_retries=3)
