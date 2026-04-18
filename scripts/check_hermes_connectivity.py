"""Hermes backend connectivity checker.

Validates the full connection chain from TCP port → HTTP health → WebSocket
handshake → method dispatch → Studio proxy awareness.

Exit codes:
    0 — all stages passed
    1 — hermes adapter unreachable (TCP or HTTP)
    2 — WebSocket handshake failed
    3 — Studio proxy misconfigured (wrong adapter type or unreachable)

Usage:
    python scripts/check_hermes_connectivity.py [--port PORT] [--studio-url URL]
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import socket
import struct
import sys
import urllib.error
import urllib.request


DEFAULT_HERMES_PORT = 18789
DEFAULT_STUDIO_URL = "http://127.0.0.1:3000"


# ---------------------------------------------------------------------------
# Stage 1 — TCP probe
# ---------------------------------------------------------------------------

def probe_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if a TCP connection to *host:port* succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Stage 2 — HTTP health probe
# ---------------------------------------------------------------------------

EXPECTED_HTTP_BODY = "Hermes Gateway Adapter"  # prefix of the response body


def probe_http_health(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    """GET ``http://host:port/`` and verify the adapter health response.

    Returns ``(ok, detail)`` where *detail* is the response body or error.
    """
    url = f"http://{host}:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if body.startswith(EXPECTED_HTTP_BODY):
                return True, body
            return False, f"unexpected body: {body!r}"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Stage 3 — Raw WebSocket handshake (stdlib only, no pip dependency)
# ---------------------------------------------------------------------------

def _ws_key() -> str:
    """Generate a random Sec-WebSocket-Key."""
    import base64
    raw = os.urandom(16)
    return base64.b64encode(raw).decode()


def _read_until(sock: socket.socket, sep: bytes, max_bytes: int = 8192) -> bytes:
    buf = b""
    while sep not in buf and len(buf) < max_bytes:
        chunk = sock.recv(1)
        if not chunk:
            break
        buf += chunk
    return buf


def _unmask(mask_bytes: bytes, data: bytes) -> bytes:
    return bytes(b ^ mask_bytes[i % 4] for i, b in enumerate(data))


def _recv_ws_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Read one WebSocket frame and return ``(opcode, payload)``."""
    hdr = sock.recv(2)
    if len(hdr) < 2:
        raise ConnectionError("short WS header")
    opcode = hdr[0] & 0x0F
    masked = bool(hdr[1] & 0x80)
    length = hdr[1] & 0x7F
    if length == 126:
        ext = sock.recv(2)
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = sock.recv(8)
        length = struct.unpack("!Q", ext)[0]
    mask_bytes = sock.recv(4) if masked else b""
    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            break
        payload += chunk
    if masked:
        payload = _unmask(mask_bytes, payload)
    return opcode, payload


def _send_ws_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    """Send one masked WebSocket frame (client frames must be masked)."""
    mask_key = os.urandom(4)
    masked_payload = _unmask(mask_key, payload)
    header = bytes([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header += bytes([0x80 | length])
    elif length < 65536:
        header += bytes([0x80 | 126]) + struct.pack("!H", length)
    else:
        header += bytes([0x80 | 127]) + struct.pack("!Q", length)
    sock.sendall(header + mask_key + masked_payload)


def probe_ws_handshake(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Perform a raw WebSocket upgrade and exchange connect/hello-ok frames.

    Returns ``(ok, detail)``.
    """
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        key = _ws_key()
        request = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode())

        # Read HTTP upgrade response
        resp = _read_until(sock, b"\r\n\r\n")
        if b"101" not in resp:
            return False, f"upgrade rejected: {resp[:120]!r}"

        # Expect connect.challenge event from server
        opcode, payload = _recv_ws_frame(sock)
        if opcode != 1:  # text frame
            return False, f"expected text frame, got opcode {opcode}"
        try:
            challenge = json.loads(payload)
        except json.JSONDecodeError:
            return False, f"invalid JSON in challenge: {payload[:120]!r}"
        if challenge.get("event") != "connect.challenge":
            return False, f"expected connect.challenge, got {challenge.get('event')}"

        # Send connect request
        connect_frame = json.dumps({
            "type": "req",
            "id": "health-check-1",
            "method": "connect",
            "params": {},
        })
        _send_ws_frame(sock, 1, connect_frame.encode())

        # Read hello-ok response
        opcode, payload = _recv_ws_frame(sock)
        if opcode != 1:
            return False, f"expected text frame for hello-ok, got opcode {opcode}"
        try:
            hello = json.loads(payload)
        except json.JSONDecodeError:
            return False, f"invalid JSON in hello: {payload[:120]!r}"

        hello_payload = hello.get("payload", {})
        if hello_payload.get("type") != "hello-ok":
            return False, f"expected hello-ok, got {hello_payload.get('type')}"
        if hello_payload.get("adapterType") != "hermes":
            return False, f"wrong adapter type: {hello_payload.get('adapterType')}"
        protocol = hello_payload.get("protocol")
        if not isinstance(protocol, int) or protocol < 3:
            return False, f"unexpected protocol version: {protocol}"

        return True, f"protocol={protocol}, adapterType=hermes"

    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Stage 4 — agents.list method probe (reuses a fresh WS connection)
# ---------------------------------------------------------------------------

def probe_agents_list(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Connect, authenticate, then call ``agents.list`` and validate the response."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        key = _ws_key()
        request = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode())
        resp = _read_until(sock, b"\r\n\r\n")
        if b"101" not in resp:
            return False, f"upgrade rejected: {resp[:120]!r}"

        # Drain connect.challenge
        _recv_ws_frame(sock)

        # Send connect
        _send_ws_frame(sock, 1, json.dumps({
            "type": "req", "id": "hc-connect", "method": "connect", "params": {},
        }).encode())
        _recv_ws_frame(sock)  # drain hello-ok

        # Send agents.list
        _send_ws_frame(sock, 1, json.dumps({
            "type": "req", "id": "hc-agents", "method": "agents.list", "params": {},
        }).encode())

        opcode, payload = _recv_ws_frame(sock)
        if opcode != 1:
            return False, f"expected text frame, got opcode {opcode}"
        result = json.loads(payload)
        if not result.get("ok"):
            return False, f"agents.list failed: {result}"
        agents = result.get("payload", {}).get("agents", [])
        return True, f"{len(agents)} agent(s) registered"

    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Stage 5 — Studio proxy probe
# ---------------------------------------------------------------------------

def probe_studio_proxy(studio_url: str, expected_adapter: str = "hermes", timeout: float = 3.0) -> tuple[bool, str]:
    """GET ``/api/studio`` from the Next.js dev server and verify adapter type."""
    url = f"{studio_url.rstrip('/')}/api/studio"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return False, f"studio unreachable: {exc}"

    adapter_type = (
        data.get("settings", {}).get("gateway", {}).get("adapterType")
        if isinstance(data, dict)
        else None
    )
    if adapter_type == expected_adapter:
        return True, f"adapterType={adapter_type}"
    return False, f"expected {expected_adapter}, got {adapter_type}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_STAGES = [
    ("TCP probe",        1),
    ("HTTP health",      1),
    ("WS handshake",     2),
    ("agents.list",      2),
    ("Studio proxy",     3),
]


def run_all(host: str, port: int, studio_url: str) -> int:
    results: list[tuple[str, bool, str]] = []

    # Stage 1 — TCP
    ok = probe_tcp(host, port)
    detail = "listening" if ok else "connection refused"
    results.append(("TCP probe", ok, detail))
    if not ok:
        _print_results(results)
        return 1

    # Stage 2 — HTTP health
    ok, detail = probe_http_health(host, port)
    results.append(("HTTP health", ok, detail))
    if not ok:
        _print_results(results)
        return 1

    # Stage 3 — WS handshake
    ok, detail = probe_ws_handshake(host, port)
    results.append(("WS handshake", ok, detail))
    if not ok:
        _print_results(results)
        return 2

    # Stage 4 — agents.list
    ok, detail = probe_agents_list(host, port)
    results.append(("agents.list", ok, detail))
    if not ok:
        _print_results(results)
        return 2

    # Stage 5 — Studio proxy
    ok, detail = probe_studio_proxy(studio_url)
    results.append(("Studio proxy", ok, detail))
    if not ok:
        _print_results(results)
        return 3

    _print_results(results)
    return 0


def _print_results(results: list[tuple[str, bool, str]]) -> None:
    print()
    print("  Hermes Connectivity Report")
    print("  " + "=" * 50)
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {detail}")
    print()
    all_ok = all(ok for _, ok, _ in results)
    if all_ok:
        print("  All stages passed.")
    else:
        failed = [name for name, ok, _ in results if not ok]
        print(f"  Failed: {', '.join(failed)}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Hermes backend connectivity")
    parser.add_argument("--host", default="127.0.0.1", help="Hermes adapter host")
    parser.add_argument("--port", type=int, default=DEFAULT_HERMES_PORT, help="Hermes adapter port")
    parser.add_argument("--studio-url", default=DEFAULT_STUDIO_URL, help="Claw3D Studio base URL")
    args = parser.parse_args()

    return run_all(args.host, args.port, args.studio_url)


if __name__ == "__main__":
    raise SystemExit(main())
