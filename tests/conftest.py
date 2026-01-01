import os
import socket
from typing import Any, Tuple


def pytest_configure(config: Any) -> None:
    # Ensure that importing LLM/embedding integrations doesn't fail on missing keys,
    # while still preventing any real outbound requests.
    os.environ.setdefault("GOOGLE_API_KEY", "test")
    os.environ.setdefault("OPENAI_API_KEY", "test")


def _is_localhost(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"}


def _block_non_localhost_create_connection(orig_create_connection):
    def _wrapped(address: Tuple[str, int], *args: Any, **kwargs: Any):
        host, _port = address
        if not _is_localhost(host):
            raise RuntimeError(
                f"Outbound network blocked during tests (attempted {host})."
            )
        return orig_create_connection(address, *args, **kwargs)

    return _wrapped


def pytest_sessionstart(session: Any) -> None:
    # Hard block any accidental outbound network usage.
    socket.create_connection = _block_non_localhost_create_connection(socket.create_connection)  # type: ignore[assignment]
