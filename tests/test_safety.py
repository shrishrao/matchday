"""Tests proving that the load generator refuses anything that is not this computer."""

import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.config import PROJECT_ROOT
from loadgen import safety
from loadgen.safety import UnsafeTargetError, require_local_target, require_safe_run_mode

LOCUSTFILE = PROJECT_ROOT / "loadgen" / "locustfile.py"


# ===== Target check =====
@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("http://[::1]:8000", "http://[::1]:8000"),
        ("https://127.0.0.1", "https://127.0.0.1"),
        ("HTTP://LOCALHOST:8000", "HTTP://LOCALHOST:8000"),
    ],
)
def test_local_targets_are_allowed(target, expected):
    assert require_local_target(target) == expected


@pytest.mark.parametrize(
    "target",
    [
        None,
        "",
        "http://example.com",
        "https://example.com:8000",
        "http://8.8.8.8",
        "http://192.168.1.10:8000",
        "http://10.0.0.1",
        "http://0.0.0.0:8000",
        "http://127.0.0.2:8000",
        "http://127.0.0.1.example.com",
        "http://localhost.example.com",
        "http://localhost.",
        "http://notlocalhost",
        "http://127.0.0.1@example.com",
        "http://user:password@127.0.0.1",
        "http://example.com#@127.0.0.1",
        "http://example.com\\@127.0.0.1",
        "http://example.com?@127.0.0.1",
        "http://127.0.0.1/../example",
        "http://127.0.0.1:8000/path",
        "http://127.0.0.1:8000?x=1",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:0",
        "http://127.0.0.1:not-a-port",
        "http://127.0.0.1 .example.com",
        "http://[::ffff:8.8.8.8]",
        "ftp://127.0.0.1",
        "file:///etc/passwd",
        "127.0.0.1:8000",
        "//example.com",
    ],
)
def test_unsafe_targets_are_refused(target):
    with pytest.raises(UnsafeTargetError):
        require_local_target(target)


def test_localhost_is_refused_if_it_resolves_elsewhere(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_, **__: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))],
    )
    with pytest.raises(UnsafeTargetError, match="not this computer"):
        require_local_target("http://localhost:8000")


def test_localhost_is_refused_if_any_address_is_elsewhere(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_, **__: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
        ],
    )
    with pytest.raises(UnsafeTargetError):
        require_local_target("http://localhost:8000")


def test_name_that_does_not_resolve_is_refused(monkeypatch):
    def fail(*_, **__):
        raise socket.gaierror("no such name")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert safety.resolves_only_to_loopback("localhost") is False


# ===== Run mode check =====
def test_headless_local_mode_is_allowed():
    require_safe_run_mode(headless=True, master=False, worker=False)


@pytest.mark.parametrize(
    "mode",
    [
        {"headless": False, "master": False, "worker": False},
        {"headless": True, "master": True, "worker": False},
        {"headless": True, "master": False, "worker": True},
    ],
)
def test_modes_that_open_a_port_are_refused(mode):
    with pytest.raises(UnsafeTargetError):
        require_safe_run_mode(**mode)


# ===== Real Locust process =====
class CountingHandler(BaseHTTPRequestHandler):
    """Count every request received, to prove that a refused run sends none."""

    requests_seen = 0

    def do_GET(self):
        type(self).requests_seen += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_):
        pass


def run_locust_directly(*arguments):
    """Start Locust without the run command, as someone skipping its checks would."""
    return subprocess.run(
        [sys.executable, "-m", "locust", "-f", str(LOCUSTFILE), *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_direct_locust_sends_nothing_to_a_non_local_target():
    # 127.0.0.2 reaches this computer but is not on the allowed list, so requests can be counted.
    CountingHandler.requests_seen = 0
    server = HTTPServer(("127.0.0.2", 0), CountingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = run_locust_directly("--headless", "--host", f"http://127.0.0.2:{server.server_port}")
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 2
    assert "Refused" in result.stderr
    assert CountingHandler.requests_seen == 0


@pytest.mark.parametrize(
    "arguments",
    [
        ("--host", "http://127.0.0.1:8000"),
        ("--headless", "--master", "--host", "http://127.0.0.1:8000"),
        ("--headless"),
    ],
)
def test_direct_locust_refuses_unsafe_modes_and_a_missing_host(arguments):
    extra = (arguments,) if isinstance(arguments, str) else arguments
    result = run_locust_directly(*extra)
    assert result.returncode == 2
    assert "Refused" in result.stderr
