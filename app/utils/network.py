"""Host and network address helpers shared by the boot banner and the API."""

from __future__ import annotations

import socket


def lan_ip() -> str | None:
    """
    Best-effort address other devices on the LAN can use.

    Opens a UDP socket to a public address to discover the outbound interface; no
    packets are sent (UDP ``connect`` only binds a route). Returns ``None`` when the
    interface cannot be determined — offline, VPN-only, or a restricted container.

    Called at request time by ``GET /api/network`` and once at boot for the banner, so a
    changed network is picked up on the next request rather than cached forever.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host, _port = sock.getsockname()
            if isinstance(host, str) and host:
                return host
    except OSError:
        return None
    return None


def is_loopback_host(host: str) -> bool:
    """Whether a bind host only accepts connections from this machine."""
    return host in {"127.0.0.1", "localhost", "::1"}
