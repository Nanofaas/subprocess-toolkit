"""Stdlib-only socket utilities for port availability and free-port selection."""

from __future__ import annotations

import errno
import socket


def _can_bind(family: int, address: str, port: int) -> bool | None:
    """Try to bind a socket and report whether the port is usable.

    Returns True when the bind succeeded, False when the port is genuinely in
    use, and None when the address family itself is unavailable on this host -
    a distinction callers need so that a machine without IPv6 is not treated as
    having every IPv6 port occupied.
    """
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.bind((address, port))
    except OSError as exc:
        if family == socket.AF_INET6 and getattr(exc, "errno", None) in {
            errno.EAFNOSUPPORT,
            errno.EPROTONOSUPPORT,
            errno.EINVAL,
        }:
            return None
        message = str(exc).lower()
        markers = (
            "address family not supported",
            "protocol not supported",
            "invalid argument",
        )
        if family == socket.AF_INET6 and any(m in message for m in markers):
            return None
        return False
    return True


def is_port_free(port: int) -> bool:
    """Return True if port is bindable on loopback.

    Checks IPv4 loopback, and IPv6 loopback when the host supports IPv6. A
    missing IPv6 stack does not make the port look occupied.
    """
    if _can_bind(socket.AF_INET, "127.0.0.1", port) is False:
        return False
    ipv6_available = _can_bind(socket.AF_INET6, "::1", port)
    return ipv6_available is not False


def pick_local_port(
    preferred: int, blocked: set[int] | None = None, *, _max_retries: int = 16
) -> int:
    """Return preferred if free and not blocked, otherwise an OS-assigned port.

    Raises:
        RuntimeError: if no free port was found within the retry budget.

    """
    blocked = blocked or set()
    if preferred not in blocked and is_port_free(preferred):
        return preferred
    for _ in range(_max_retries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            candidate = int(sock.getsockname()[1])
        if candidate not in blocked:
            return candidate
    message = (
        f"Could not find a free port outside {len(blocked)} blocked ports "
        f"after {_max_retries} attempts"
    )
    raise RuntimeError(message)
