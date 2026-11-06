"""Keep the load generator local: anything that is not clearly this computer is refused."""

import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_SCHEMES = {"http", "https"}


class UnsafeTargetError(ValueError):
    """The load generator was pointed at a target or mode it must not use."""


# ===== Target check =====
def resolves_only_to_loopback(hostname: str) -> bool:
    """Check that a name resolves, and only to this computer's own addresses."""
    try:
        results = socket.getaddrinfo(hostname, None)
    except OSError:
        return False
    return bool(results) and all(ipaddress.ip_address(row[4][0]).is_loopback for row in results)


def require_local_target(target: str | None) -> str:
    """Return the target if it is exactly a local address, otherwise raise UnsafeTargetError."""
    if not target:
        raise UnsafeTargetError("A target host is required.")
    if any(character == "\\" or character.isspace() for character in target):
        raise UnsafeTargetError("The target contains characters that are not allowed.")

    try:
        parts = urlsplit(target)
        port = parts.port
    except ValueError as error:
        raise UnsafeTargetError("The target is not a valid address.") from error

    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeTargetError("The target must start with http:// or https://.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeTargetError("The target must not contain a username or password.")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise UnsafeTargetError("The target must not contain a path, query or fragment.")
    if parts.hostname not in ALLOWED_HOSTS:
        raise UnsafeTargetError(f"Refusing non-local target: {parts.hostname}")
    if not resolves_only_to_loopback(parts.hostname):
        raise UnsafeTargetError(f"Refusing target that is not this computer: {parts.hostname}")
    if port == 0:
        raise UnsafeTargetError("The target port is not valid.")
    return target.rstrip("/")


# ===== Run mode check =====
def require_safe_run_mode(headless: bool, master: bool, worker: bool) -> None:
    """Refuse Locust modes that open a network port: its web page and distributed runs."""
    if not headless:
        raise UnsafeTargetError("Refusing to run with Locust's web page. Use --headless.")
    if master or worker:
        raise UnsafeTargetError("Refusing a distributed run. Matchday's load generator is local-only.")
