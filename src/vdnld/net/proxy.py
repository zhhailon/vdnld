"""SOCKS5 proxy support (Tor)."""

from __future__ import annotations

_TOR_HOST = "127.0.0.1"
_TOR_PORT = 9150  # Tor Browser default; standalone tor daemon uses 9050


def enable_socks5_proxy(host: str = _TOR_HOST, port: int = _TOR_PORT) -> None:
    """Patch the global socket to route all connections through a SOCKS5 proxy.

    Call once at startup before any network activity. Requires PySocks:
        pip install 'vdnld[tor]'
    """
    try:
        import socks  # type: ignore[import-untyped]
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PySocks is not installed. Install the tor extra: pip install 'vdnld[tor]'"
        ) from exc

    import socket

    # Patch create_connection so hostnames are sent to Tor for resolution.
    # This avoids local DNS lookups (no IPv6 issues, no DNS leaks).
    def _proxied_create_connection(
        address: tuple[str, int],
        timeout: object = socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address: object = None,
    ) -> socket.socket:
        resolved_timeout = None if timeout is socket._GLOBAL_DEFAULT_TIMEOUT else timeout
        return socks.create_connection(  # type: ignore[return-value]
            address,
            resolved_timeout,
            source_address,
            proxy_type=socks.SOCKS5,
            proxy_addr=host,
            proxy_port=port,
            proxy_rdns=True,
        )

    socket.create_connection = _proxied_create_connection  # type: ignore[assignment]


def tor_proxy_url(host: str = _TOR_HOST, port: int = _TOR_PORT) -> str:
    return f"socks5://{host}:{port}"
