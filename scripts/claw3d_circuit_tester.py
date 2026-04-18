"""Claw3D Full-Circuit Diagnostic Tester

Tests the complete connection chain:
    Local LLM (Ollama/LM Studio)
        -> OpenClaw/Hermes Gateway
            -> Claw3D Studio (Next.js)
                -> Browser WebSocket proxy

Each stage is like a breaker in an electrical panel — if one trips,
everything downstream goes dark.  This script walks the circuit from
the power source (your local model) through every relay to the final
load (the browser WebSocket endpoint).

Exit codes:
    0 — full circuit healthy
    1 — local LLM unreachable
    2 — gateway/hermes unreachable
    3 — Claw3D Studio unreachable or misconfigured
    4 — WebSocket proxy broken

Usage:
    python scripts/claw3d_circuit_tester.py
    python scripts/claw3d_circuit_tester.py --llm-port 1234   # LM Studio
    python scripts/claw3d_circuit_tester.py --llm-port 11434  # Ollama
    python scripts/claw3d_circuit_tester.py --skip-llm        # skip LLM check
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.error
import urllib.request

# ═══════════════════════════════════════════════════════════════════════════
# Default wiring — change these to match your panel layout
# ═══════════════════════════════════════════════════════════════════════════

# ELI5: These are the default addresses for each breaker in the circuit.
# Like labeling breakers in a panel: "Kitchen = 20A slot 3".
DEFAULT_LLM_HOST = "127.0.0.1"
DEFAULT_LLM_PORT = 11434          # Ollama default; use 1234 for LM Studio
DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 18789      # Hermes adapter default
DEFAULT_STUDIO_URL = "http://127.0.0.1:3000"

# Known LLM server health endpoints
# ELI5: Each brand of model server has a different "test port" on the panel.
LLM_HEALTH_ROUTES = {
    11434: "/api/tags",            # Ollama — lists loaded models
    1234:  "/v1/models",           # LM Studio — OpenAI-compatible model list
}


# ═══════════════════════════════════════════════════════════════════════════
# Utility helpers (stdlib only — no pip installs needed)
# ═══════════════════════════════════════════════════════════════════════════

class _Colors:
    """ANSI color helpers — auto-disabled on dumb terminals."""
    _enabled = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    @classmethod
    def green(cls, s: str) -> str:
        return f"\033[92m{s}\033[0m" if cls._enabled else s

    @classmethod
    def red(cls, s: str) -> str:
        return f"\033[91m{s}\033[0m" if cls._enabled else s

    @classmethod
    def yellow(cls, s: str) -> str:
        return f"\033[93m{s}\033[0m" if cls._enabled else s

    @classmethod
    def cyan(cls, s: str) -> str:
        return f"\033[96m{s}\033[0m" if cls._enabled else s

    @classmethod
    def bold(cls, s: str) -> str:
        return f"\033[1m{s}\033[0m" if cls._enabled else s


def _tag(ok: bool) -> str:
    return _Colors.green("PASS") if ok else _Colors.red("FAIL")


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 1 — Local LLM (the power source)
# ═══════════════════════════════════════════════════════════════════════════
# ELI5: This is the main breaker. If your model server is off, nothing
# downstream can work — there's no voltage entering the panel.

def probe_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    """Quick TCP SYN check — is anything listening on this port?"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_llm_health(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Hit the LLM's health/model-list endpoint and verify models are loaded.

    ELI5: We're reading the meter on the main breaker to confirm not just
    that it's flipped ON, but that current is actually flowing.
    """
    route = LLM_HEALTH_ROUTES.get(port, "/v1/models")
    url = f"http://{host}:{port}{route}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body.strip().startswith("{") or body.strip().startswith("[") else {}

            # Ollama: {"models": [...]}
            if "models" in data:
                models = data["models"]
                names = [m.get("name", "?") for m in models[:5]]
                return True, f"{len(models)} model(s) loaded: {', '.join(names)}"

            # LM Studio / OpenAI-compatible: {"data": [{"id": "..."}]}
            if "data" in data:
                models = data["data"]
                names = [m.get("id", "?") for m in models[:5]]
                return True, f"{len(models)} model(s) available: {', '.join(names)}"

            # Fallback — server responded but format unknown
            return True, f"server responded (HTTP {resp.getcode()}), but model list format unrecognized"

    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return False, f"unreachable: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def probe_llm_inference(host: str, port: int, timeout: float = 15.0) -> tuple[bool, str]:
    """Send a minimal chat completion to verify the model can actually generate.

    ELI5: We flip the light switch to confirm the bulb lights up, not just
    that the wire has voltage.
    """
    url = f"http://{host}:{port}/v1/chat/completions"
    payload = json.dumps({
        "model": "",  # empty = use default loaded model
        "messages": [{"role": "user", "content": "Say OK"}],
        "max_tokens": 4,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            choices = body.get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content", "").strip()
                model = body.get("model", "?")
                return True, f"model={model}, replied: {text[:60]!r}"
            return False, "empty choices array"
    except urllib.error.HTTPError as exc:
        # 404 is expected on Ollama (it doesn't serve /v1/chat/completions natively)
        if exc.code == 404:
            return True, "inference endpoint not available (Ollama uses /api/chat); TCP+health OK"
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 2 — OpenClaw / Hermes Gateway (the sub-panel)
# ═══════════════════════════════════════════════════════════════════════════
# ELI5: This is the sub-panel that takes raw model power and distributes it
# into the rooms (agents). If this breaker is tripped, the model works but
# Claw3D can't reach it.

EXPECTED_HERMES_BODY = "Hermes Gateway Adapter"


def probe_gateway_http(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    """GET the gateway root and verify the Hermes health banner."""
    url = f"http://{host}:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if body.startswith(EXPECTED_HERMES_BODY):
                return True, body
            return False, f"unexpected response: {body[:80]!r}"
    except Exception as exc:
        return False, str(exc)


# --- Raw WebSocket helpers (stdlib, no pip) --------------------------------

def _ws_key() -> str:
    return base64.b64encode(os.urandom(16)).decode()


def _read_until(sock: socket.socket, sep: bytes, limit: int = 8192) -> bytes:
    buf = b""
    while sep not in buf and len(buf) < limit:
        chunk = sock.recv(1)
        if not chunk:
            break
        buf += chunk
    return buf


def _unmask(mask: bytes, data: bytes) -> bytes:
    return bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def _recv_ws_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Read one WebSocket frame → (opcode, payload)."""
    hdr = sock.recv(2)
    if len(hdr) < 2:
        raise ConnectionError("short WS header")
    opcode = hdr[0] & 0x0F
    masked = bool(hdr[1] & 0x80)
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
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
    """Send one masked WebSocket frame (client→server must be masked)."""
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


def _ws_upgrade(sock: socket.socket, host: str, port: int, path: str = "/") -> bytes:
    """Send HTTP Upgrade request, return the raw response headers."""
    key = _ws_key()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    sock.sendall(request.encode())
    return _read_until(sock, b"\r\n\r\n")


def probe_gateway_ws_handshake(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Full Hermes WS handshake: upgrade → connect.challenge → connect → hello-ok.

    ELI5: We're testing the contactor relay inside the sub-panel — it must
    close (connect.challenge) and latch (hello-ok) before current flows.
    """
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        resp = _ws_upgrade(sock, host, port)
        if b"101" not in resp:
            return False, f"upgrade rejected: {resp[:120]!r}"

        # Server sends connect.challenge
        opcode, payload = _recv_ws_frame(sock)
        if opcode != 1:
            return False, f"expected text frame, got opcode {opcode}"
        challenge = json.loads(payload)
        if challenge.get("event") != "connect.challenge":
            return False, f"expected connect.challenge, got {challenge.get('event')}"

        # Client sends connect request
        _send_ws_frame(sock, 1, json.dumps({
            "type": "req",
            "id": "circuit-test-1",
            "method": "connect",
            "params": {},
        }).encode())

        # Server responds with hello-ok
        opcode, payload = _recv_ws_frame(sock)
        if opcode != 1:
            return False, f"expected text frame for hello-ok, got opcode {opcode}"
        hello = json.loads(payload)
        hello_payload = hello.get("payload", {})

        if hello_payload.get("type") != "hello-ok":
            return False, f"expected hello-ok, got {hello_payload.get('type')}"

        adapter_type = hello_payload.get("adapterType", "?")
        protocol = hello_payload.get("protocol", "?")
        return True, f"adapterType={adapter_type}, protocol={protocol}"

    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def probe_gateway_model_routing(
    host: str, port: int, llm_host: str, llm_port: int, timeout: float = 5.0
) -> tuple[bool, str]:
    """Check what model the gateway will route to, and whether that backend is reachable.

    ELI5: We check the wiring label on the breaker to make sure it actually
    goes to a live circuit, not a disconnected wire.
    """
    # Probe the gateway HTTP root for model info
    url = f"http://{host}:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return False, "gateway unreachable"

    # Check if the LLM backend is reachable
    llm_reachable = probe_tcp(llm_host, llm_port, timeout=2.0)

    # Try to detect model routing from env
    # We read the .env file if accessible
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    env_path = os.path.join(repo_root, "Claw3D-main", ".env")
    hermes_model = "(unknown)"
    anthropic_key_set = False
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("HERMES_MODEL="):
                    hermes_model = line.split("=", 1)[1].strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    anthropic_key_set = bool(line.split("=", 1)[1].strip())

    warnings = []
    if hermes_model.startswith("anthropic/") and not anthropic_key_set:
        warnings.append(f"{_Colors.red('FAULT')}: HERMES_MODEL={hermes_model} but ANTHROPIC_API_KEY is empty — all chat will fail!")
        warnings.append(f"FIX: Set HERMES_MODEL=lmstudio/qwen2.5-coder:14b in .env to use local LM Studio")
    if not llm_reachable:
        warnings.append(f"{_Colors.yellow('WARN')}: LLM backend on {llm_host}:{llm_port} is not reachable")

    detail = f"model={hermes_model}, llm_backend={'up' if llm_reachable else 'down'}"
    if warnings:
        detail += " | " + " | ".join(warnings)

    ok = not (hermes_model.startswith("anthropic/") and not anthropic_key_set)
    return ok, detail


def probe_gateway_agents(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """After handshake, call agents.list to verify the orchestrator is wired up.

    ELI5: We verified the relay latched — now we check that the branch
    circuits downstream (agents) have power too.
    """
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        resp = _ws_upgrade(sock, host, port)
        if b"101" not in resp:
            return False, f"upgrade rejected"

        # Drain challenge + connect + hello-ok
        _recv_ws_frame(sock)
        _send_ws_frame(sock, 1, json.dumps({
            "type": "req", "id": "ct-connect", "method": "connect", "params": {},
        }).encode())
        _recv_ws_frame(sock)

        # Request agents list
        _send_ws_frame(sock, 1, json.dumps({
            "type": "req", "id": "ct-agents", "method": "agents.list", "params": {},
        }).encode())

        opcode, payload = _recv_ws_frame(sock)
        if opcode != 1:
            return False, f"expected text, got opcode {opcode}"
        result = json.loads(payload)
        if not result.get("ok"):
            return False, f"agents.list error: {json.dumps(result)[:100]}"
        agents = result.get("payload", {}).get("agents", [])
        names = [a.get("name", "?") for a in agents[:5]]
        return True, f"{len(agents)} agent(s): {', '.join(names) if names else '(none registered)'}"

    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 3 — Claw3D Studio (the room panel / outlets)
# ═══════════════════════════════════════════════════════════════════════════
# ELI5: The room panel takes sub-panel power and feeds the outlets. If this
# trips, the gateway is fine but the browser has no power.

def probe_studio_http(studio_url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """GET /api/studio and verify the adapter configuration returned to browser.

    This is the endpoint the React client calls on page load to decide
    which adapter type to connect through.
    """
    url = f"{studio_url.rstrip('/')}/api/studio"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return False, f"studio unreachable: {exc}"

    # Extract gateway config the browser will use
    settings = data.get("settings", {})
    gateway = settings.get("gateway", {})
    local_defaults = data.get("localGatewayDefaults", {})

    adapter_type = gateway.get("adapterType", "?")
    gateway_url = gateway.get("url", "?")
    last_known = gateway.get("lastKnownGood", {})
    lkg_adapter = last_known.get("adapterType", "none")

    # Collect profiles
    profiles = gateway.get("profiles", {})
    profile_names = list(profiles.keys()) if profiles else []

    detail_parts = [
        f"adapterType={adapter_type}",
        f"url={gateway_url}",
        f"lastKnownGood={lkg_adapter}",
        f"profiles=[{', '.join(profile_names)}]" if profile_names else "profiles=[]",
    ]
    if local_defaults:
        detail_parts.append(f"envDefault={local_defaults.get('adapterType', '?')}")

    # Warn about known misconfigurations
    warnings = []
    if adapter_type == "custom":
        warnings.append("WARN: adapterType='custom' — may block WS-based adapters")
    if gateway_url and gateway_url.startswith("http://") and adapter_type in ("hermes", "openclaw", "demo"):
        warnings.append("WARN: gateway URL is http:// but adapter expects ws://")
    if lkg_adapter and lkg_adapter != adapter_type:
        warnings.append(f"WARN: lastKnownGood ({lkg_adapter}) differs from active ({adapter_type})")

    detail = "; ".join(detail_parts)
    if warnings:
        detail += " | " + " | ".join(warnings)

    return True, detail


def probe_studio_diagnose(studio_url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """GET /api/gateway/diagnose — the server-side self-test endpoint."""
    url = f"{studio_url.rstrip('/')}/api/gateway/diagnose"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return True, "diagnose endpoint not available (older Claw3D build)"
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, f"unreachable: {exc}"

    # Parse the diagnose payload (actual shape: ports, probes, env, hint)
    ports = data.get("ports", {})
    probes = data.get("probes", {})
    env_info = data.get("env", {})
    hint = data.get("hint", "")

    hermes_up = ports.get("18789_hermes", False)
    lmstudio_up = ports.get("1234_lmstudio", False)
    hermes_probe_ok = (probes.get("hermes") or {}).get("ok", False)

    detail_parts = [
        f"hermes={'up' if hermes_up else 'down'}",
        f"lmstudio={'up' if lmstudio_up else 'down'}",
        f"hermesHTTP={'ok' if hermes_probe_ok else 'fail'}",
        f"adapter={env_info.get('CLAW3D_GATEWAY_ADAPTER_TYPE', '?')}",
    ]
    if hint:
        detail_parts.append(f"hint={hint[:80]}")

    ok = hermes_up and hermes_probe_ok
    return ok, "; ".join(detail_parts)


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 4 — Browser WebSocket Proxy (the outlet under load)
# ═══════════════════════════════════════════════════════════════════════════
# ELI5: We're plugging in a test device (voltmeter) at the outlet to see
# if end-to-end power reaches the appliance (browser).

def probe_studio_ws_proxy(studio_url: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Perform a raw WebSocket upgrade to /api/gateway/ws through the Studio
    proxy and verify the upstream handshake completes end-to-end.

    This is the EXACT path the browser takes.
    """
    from urllib.parse import urlparse
    parsed = urlparse(studio_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3000

    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        # Upgrade request to the proxy path
        key = _ws_key()
        request = (
            f"GET /api/gateway/ws HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Origin: http://{host}:{port}\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode())

        resp = _read_until(sock, b"\r\n\r\n")
        if b"101" not in resp:
            # Check for common error patterns
            if b"426" in resp:
                return False, "upgrade required but rejected (check STUDIO_ACCESS_TOKEN)"
            if b"403" in resp:
                return False, "forbidden — STUDIO_ACCESS_TOKEN mismatch or CORS blocked"
            if b"502" in resp or b"503" in resp:
                return False, "proxy error — upstream gateway unreachable from Studio server"
            return False, f"upgrade rejected: {resp[:160]!r}"

        # Read first frame from proxied upstream
        sock.settimeout(timeout)
        opcode, payload = _recv_ws_frame(sock)
        if opcode == 8:  # close frame
            code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 0
            reason = payload[2:].decode("utf-8", errors="replace") if len(payload) > 2 else ""
            return False, f"upstream closed immediately: code={code} reason={reason!r}"
        if opcode != 1:
            return False, f"unexpected first frame opcode={opcode}"

        msg = json.loads(payload)

        # Could be connect.challenge (hermes) or hello (demo) or error
        event = msg.get("event", msg.get("type", "?"))
        if event == "connect.challenge":
            return True, f"proxied connect.challenge received (hermes adapter)"
        if event == "hello":
            return True, f"proxied hello received (demo/openclaw adapter)"
        if "error" in str(msg).lower():
            return False, f"upstream error: {json.dumps(msg)[:120]}"

        return True, f"first proxied frame: event={event}"

    except socket.timeout:
        return False, "timeout waiting for proxied upstream frame (gateway may be down)"
    except ConnectionError as exc:
        return False, f"connection error: {exc}"
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def probe_studio_full_handshake(studio_url: str, timeout: float = 12.0) -> tuple[bool, str]:
    """Perform the FULL browser-style handshake through the Studio proxy:
    WS upgrade → connect.challenge → connect request → hello-ok response.

    This is the most comprehensive test — it mirrors exactly what the browser
    does and will catch protocol-level failures that simpler checks miss.
    """
    from urllib.parse import urlparse
    parsed = urlparse(studio_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3000

    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        # Step 1: WebSocket upgrade
        key = _ws_key()
        request = (
            f"GET /api/gateway/ws HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Origin: http://{host}:{port}\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode())
        resp = _read_until(sock, b"\r\n\r\n")
        if b"101" not in resp:
            return False, f"WS upgrade rejected: {resp[:120]!r}"

        # Step 2: Receive connect.challenge
        sock.settimeout(timeout)
        opcode, payload = _recv_ws_frame(sock)
        if opcode != 1:
            return False, f"expected text frame, got opcode={opcode}"
        challenge = json.loads(payload)
        if challenge.get("event") != "connect.challenge":
            return False, f"expected connect.challenge, got: {json.dumps(challenge)[:120]}"
        nonce = challenge.get("payload", {}).get("nonce", "")

        # Step 3: Send connect request (mirrors GatewayBrowserClient.sendConnect)
        connect_frame = {
            "type": "req",
            "id": "circuit-test-connect",
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "circuit-tester",
                    "version": "1.0",
                    "platform": sys.platform,
                    "mode": "webchat",
                },
                "role": "operator",
                "scopes": ["operator.admin"],
                "auth": {},
            },
        }
        _send_ws_frame(sock, 1, json.dumps(connect_frame).encode())

        # Step 4: Receive hello-ok response
        opcode, payload = _recv_ws_frame(sock)
        if opcode == 8:
            code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 0
            reason = payload[2:].decode("utf-8", errors="replace") if len(payload) > 2 else ""
            return False, f"server closed after connect: code={code} reason={reason!r}"
        if opcode != 1:
            return False, f"expected text response, got opcode={opcode}"

        hello = json.loads(payload)
        if hello.get("type") != "res":
            return False, f"expected response frame, got type={hello.get('type')}"
        if not hello.get("ok"):
            err = hello.get("error", {})
            return False, f"connect rejected: {err.get('code', '?')} — {err.get('message', '?')}"

        adapter_type = hello.get("payload", {}).get("adapterType", "?")
        features = hello.get("payload", {}).get("features", {})
        method_count = len(features.get("methods", []))
        return True, f"full handshake OK — adapter={adapter_type}, {method_count} methods available"

    except socket.timeout:
        return False, "timeout during full handshake (>12s) — same failure the browser sees"
    except ConnectionError as exc:
        return False, f"connection error: {exc}"
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            # Send WS close frame
            _send_ws_frame(sock, 8, struct.pack("!H", 1000))
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 5 — Configuration & Environment Audit
# ═══════════════════════════════════════════════════════════════════════════
# ELI5: Check the wiring diagram (config files) for known faults before
# blaming the components.

def audit_env_files() -> list[str]:
    """Scan for common .env misconfigurations in the Claw3D project."""
    findings: list[str] = []

    # Find Claw3D-main directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    claw3d_dir = os.path.join(repo_root, "Claw3D-main")

    env_local = os.path.join(claw3d_dir, ".env.local")
    env_file = os.path.join(claw3d_dir, ".env")

    for filepath in [env_local, env_file]:
        label = os.path.basename(filepath)
        if not os.path.isfile(filepath):
            findings.append(f"  {label}: not found (OK if using defaults)")
            continue

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        findings.append(f"  {label}:")
        lines = content.strip().splitlines()
        env_vars = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                env_vars[key.strip()] = val.strip()

        # Check gateway URL
        gw_url = env_vars.get("CLAW3D_GATEWAY_URL", "")
        gw_type = env_vars.get("CLAW3D_GATEWAY_ADAPTER_TYPE", "")

        if gw_url:
            findings.append(f"    CLAW3D_GATEWAY_URL = {gw_url}")
            if gw_type in ("hermes", "openclaw", "demo") and gw_url.startswith("http://"):
                findings.append(f"    {_Colors.yellow('WARN')}: URL is http:// but adapter type '{gw_type}' expects ws://")
            if gw_type == "custom" and gw_url.startswith("ws://"):
                findings.append(f"    {_Colors.yellow('WARN')}: URL is ws:// but adapter type 'custom' expects http://")
        if gw_type:
            findings.append(f"    CLAW3D_GATEWAY_ADAPTER_TYPE = {gw_type}")

        # Check for stale / conflicting vars
        if "NEXT_PUBLIC_GATEWAY_URL" in env_vars:
            findings.append(f"    {_Colors.yellow('WARN')}: NEXT_PUBLIC_GATEWAY_URL is build-time only; use CLAW3D_GATEWAY_URL instead")

        # Check model keys
        if "HERMES_MODEL" in env_vars:
            model = env_vars["HERMES_MODEL"]
            findings.append(f"    HERMES_MODEL = {model}")
            if "anthropic" in model.lower() and not env_vars.get("ANTHROPIC_API_KEY"):
                findings.append(f"    {_Colors.yellow('WARN')}: HERMES_MODEL references Anthropic but ANTHROPIC_API_KEY is empty")

        if "STUDIO_ACCESS_TOKEN" in env_vars:
            findings.append(f"    STUDIO_ACCESS_TOKEN = {'(set)' if env_vars['STUDIO_ACCESS_TOKEN'] else '(empty)'}")

    # Check persisted settings
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    settings_path = os.path.join(home, ".openclaw", "claw3d", "settings.json")
    if os.path.isfile(settings_path):
        findings.append(f"  settings.json ({settings_path}):")
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            gw = settings.get("gateway", {})
            findings.append(f"    adapterType = {gw.get('adapterType', '(not set)')}")
            findings.append(f"    url = {gw.get('url', '(not set)')}")
            lkg = gw.get("lastKnownGood", {})
            if lkg:
                findings.append(f"    lastKnownGood.adapterType = {lkg.get('adapterType', '?')}")
            profiles = list(gw.get("profiles", {}).keys())
            if profiles:
                findings.append(f"    profiles = [{', '.join(profiles)}]")

            # Known issue: persisted 'custom' blocks env-var overrides
            if gw.get("adapterType") == "custom":
                findings.append(f"    {_Colors.red('FAULT')}: Persisted adapterType='custom' will override env vars!")
                findings.append(f"    FIX: Delete this file or change adapterType to 'hermes'")

        except Exception as exc:
            findings.append(f"    Error reading: {exc}")
    else:
        findings.append(f"  settings.json: not found at {settings_path} (using defaults)")

    return findings


# ═══════════════════════════════════════════════════════════════════════════
# Test Runner — walk the circuit breaker-by-breaker
# ═══════════════════════════════════════════════════════════════════════════

def run_full_circuit(
    llm_host: str,
    llm_port: int,
    gw_host: str,
    gw_port: int,
    studio_url: str,
    skip_llm: bool = False,
    skip_inference: bool = False,
    verbose: bool = False,
) -> int:
    """Run all stages and return an exit code."""

    results: list[tuple[str, bool, str]] = []
    exit_code = 0

    print()
    print(_Colors.bold("  ╔══════════════════════════════════════════════════════════╗"))
    print(_Colors.bold("  ║       Claw3D Full-Circuit Diagnostic Tester             ║"))
    print(_Colors.bold("  ╚══════════════════════════════════════════════════════════╝"))
    print()
    print(f"  Target LLM:     http://{llm_host}:{llm_port}")
    print(f"  Target Gateway: ws://{gw_host}:{gw_port}")
    print(f"  Target Studio:  {studio_url}")
    print()

    # ── Stage 1: Local LLM ──────────────────────────────────────────────
    if not skip_llm:
        print(_Colors.cyan("  ── Stage 1: Local LLM (Power Source) ──"))

        ok = probe_tcp(llm_host, llm_port)
        detail = "listening" if ok else "connection refused — is the model server running?"
        results.append(("1a. LLM TCP", ok, detail))
        print(f"  [{_tag(ok)}] TCP port {llm_port}: {detail}")

        if ok:
            ok, detail = probe_llm_health(llm_host, llm_port)
            results.append(("1b. LLM Health", ok, detail))
            print(f"  [{_tag(ok)}] Health check: {detail}")

            if ok and not skip_inference:
                ok, detail = probe_llm_inference(llm_host, llm_port)
                results.append(("1c. LLM Inference", ok, detail))
                print(f"  [{_tag(ok)}] Inference test: {detail}")
        else:
            exit_code = 1

        print()
    else:
        print(_Colors.yellow("  ── Stage 1: Local LLM — SKIPPED ──"))
        print()

    # ── Stage 2: Gateway / Hermes ───────────────────────────────────────
    print(_Colors.cyan("  ── Stage 2: OpenClaw/Hermes Gateway (Sub-Panel) ──"))

    ok = probe_tcp(gw_host, gw_port)
    detail = "listening" if ok else "connection refused — is the hermes adapter running?"
    results.append(("2a. Gateway TCP", ok, detail))
    print(f"  [{_tag(ok)}] TCP port {gw_port}: {detail}")

    if ok:
        ok, detail = probe_gateway_http(gw_host, gw_port)
        results.append(("2b. Gateway HTTP", ok, detail))
        print(f"  [{_tag(ok)}] HTTP health: {detail}")

        ok, detail = probe_gateway_ws_handshake(gw_host, gw_port)
        results.append(("2c. Gateway WS", ok, detail))
        print(f"  [{_tag(ok)}] WS handshake: {detail}")

        if ok:
            ok, detail = probe_gateway_agents(gw_host, gw_port)
            results.append(("2d. Agents list", ok, detail))
            print(f"  [{_tag(ok)}] agents.list: {detail}")

        ok, detail = probe_gateway_model_routing(gw_host, gw_port, llm_host, llm_port)
        results.append(("2e. Model routing", ok, detail))
        print(f"  [{_tag(ok)}] Model routing: {detail}")
    else:
        if exit_code == 0:
            exit_code = 2

    print()

    # ── Stage 3: Claw3D Studio ──────────────────────────────────────────
    print(_Colors.cyan("  ── Stage 3: Claw3D Studio (Room Panel) ──"))

    # TCP check on Studio port
    from urllib.parse import urlparse
    parsed = urlparse(studio_url)
    studio_host = parsed.hostname or "127.0.0.1"
    studio_port = parsed.port or 3000

    ok = probe_tcp(studio_host, studio_port)
    detail = "listening" if ok else "connection refused — is the Claw3D dev server running?"
    results.append(("3a. Studio TCP", ok, detail))
    print(f"  [{_tag(ok)}] TCP port {studio_port}: {detail}")

    if ok:
        ok, detail = probe_studio_http(studio_url)
        results.append(("3b. Studio /api/studio", ok, detail))
        print(f"  [{_tag(ok)}] /api/studio config: {detail}")

        ok, detail = probe_studio_diagnose(studio_url)
        results.append(("3c. Studio /diagnose", ok, detail))
        print(f"  [{_tag(ok)}] /api/gateway/diagnose: {detail}")
    else:
        if exit_code == 0:
            exit_code = 3

    print()

    # ── Stage 4: Browser WS Proxy ──────────────────────────────────────
    print(_Colors.cyan("  ── Stage 4: Browser WebSocket Proxy (Outlet Test) ──"))

    if probe_tcp(studio_host, studio_port):
        ok, detail = probe_studio_ws_proxy(studio_url)
        results.append(("4a. WS Proxy /api/gateway/ws", ok, detail))
        print(f"  [{_tag(ok)}] WS upgrade + challenge: {detail}")

        if ok:
            ok, detail = probe_studio_full_handshake(studio_url)
            results.append(("4b. Full protocol handshake", ok, detail))
            print(f"  [{_tag(ok)}] Full handshake (challenge→connect→hello): {detail}")

        if not ok and exit_code == 0:
            exit_code = 4
    else:
        results.append(("4a. WS Proxy", False, "Studio not reachable"))
        print(f"  [{_tag(False)}] Studio not reachable — skipping WS proxy test")

    print()

    # ── Stage 5: Configuration Audit ───────────────────────────────────
    print(_Colors.cyan("  ── Stage 5: Configuration & Environment Audit ──"))
    audit = audit_env_files()
    for line in audit:
        print(line)
    print()

    # ── Summary ────────────────────────────────────────────────────────
    print(_Colors.bold("  ══════════════════════════════════════════════════════════"))
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    failed = [(name, detail) for name, ok, detail in results if not ok]

    if not failed:
        print(_Colors.green(f"  ✓ All {total} checks passed — full circuit is live!"))
    else:
        print(_Colors.red(f"  ✗ {len(failed)}/{total} checks failed:"))
        for name, detail in failed:
            print(f"    • {name}: {detail}")

    print()

    # ── Troubleshooting Checklist ──────────────────────────────────────
    if failed:
        print_troubleshooting_checklist(results, llm_port, gw_port, studio_port)

    return exit_code


# ═══════════════════════════════════════════════════════════════════════════
# Troubleshooting Checklist (printed when failures are detected)
# ═══════════════════════════════════════════════════════════════════════════

def print_troubleshooting_checklist(
    results: list[tuple[str, bool, str]],
    llm_port: int,
    gw_port: int,
    studio_port: int,
) -> None:
    """Print a targeted checklist based on which stages failed."""

    failed_names = {name for name, ok, _ in results if not ok}
    passed_names = {name for name, ok, _ in results if ok}

    print(_Colors.bold("  ┌──────────────────────────────────────────────────────┐"))
    print(_Colors.bold("  │          TROUBLESHOOTING CHECKLIST                   │"))
    print(_Colors.bold("  └──────────────────────────────────────────────────────┘"))
    print()

    step = 1

    # --- LLM failures ---
    if any("LLM" in n for n in failed_names):
        server_name = "LM Studio" if llm_port == 1234 else "Ollama"
        alt_port = 1234 if llm_port == 11434 else 11434
        alt_name = "LM Studio" if alt_port == 1234 else "Ollama"

        print(f"  {step}. {_Colors.yellow('LOCAL MODEL SERVER IS DOWN')}")
        print(f"     Your {server_name} server on port {llm_port} is not responding.")
        print()
        print(f"     Quick fixes:")
        print(f"     a) Start {server_name}:")
        if llm_port == 11434:
            print(f"        $ ollama serve")
            print(f"        Then load a model: $ ollama run llama3.2")
        else:
            print(f"        Open LM Studio → Server tab → Start Server")
            print(f"        Ensure a model is loaded in the Models tab")
        print()
        print(f"     b) Wrong port? Try the other server:")
        print(f"        $ python scripts/claw3d_circuit_tester.py --llm-port {alt_port}")
        print()
        print(f"     c) Check if something else is using port {llm_port}:")
        print(f"        $ netstat -ano | findstr :{llm_port}")
        print()
        print(f"     d) Ensure the server binds to 0.0.0.0 (not just 127.0.0.1)")
        print(f"        for LAN access. For local-only testing, 127.0.0.1 is fine.")
        print()
        step += 1

    # --- Model routing failures ---
    if any("Model routing" in n for n in failed_names):
        print(f"  {step}. {_Colors.yellow('MODEL ROUTING MISCONFIGURED')}")
        print(f"     The gateway's HERMES_MODEL routes chat to a backend with no API key.")
        print()
        print(f"     Quick fixes:")
        print(f"     a) Use LM Studio as the default model (recommended for local use):")
        print(f"        In Claw3D-main/.env, set:")
        print(f"          HERMES_MODEL=lmstudio/qwen2.5-coder:14b")
        print()
        print(f"     b) If you want to use Anthropic/Claude, add your API key:")
        print(f"        In Claw3D-main/.env, set:")
        print(f"          ANTHROPIC_API_KEY=sk-ant-your-key-here")
        print()
        print(f"     c) After changing .env, restart the Hermes adapter:")
        print(f"        Kill the node process and re-run:")
        print(f"        $ cd Claw3D-main && node server/hermes-gateway-adapter.js")
        print()
        step += 1

    # --- Gateway failures ---
    if any("Gateway" in n for n in failed_names):
        print(f"  {step}. {_Colors.yellow('HERMES GATEWAY ADAPTER IS DOWN')}")
        print(f"     The OpenClaw/Hermes adapter on port {gw_port} is not responding.")
        print()
        print(f"     Quick fixes:")
        print(f"     a) Start the Hermes adapter:")
        print(f"        $ cd Claw3D-main")
        print(f"        $ node server/hermes-gateway-adapter.js")
        print()
        print(f"     b) Or use the built-in demo adapter (no external model needed):")
        print(f"        The demo adapter auto-starts on port 18890 when Claw3D launches.")
        print(f"        Set CLAW3D_GATEWAY_ADAPTER_TYPE=demo in .env.local")
        print()
        print(f"     c) Check if the adapter crashed (look for error output in its terminal)")
        print()
        print(f"     d) Verify port {gw_port} is not blocked by firewall:")
        print(f"        $ netstat -ano | findstr :{gw_port}")
        print()
        step += 1

    if any("WS" in n and "Gateway" in n for n in failed_names) and "2a. Gateway TCP" in passed_names:
        print(f"  {step}. {_Colors.yellow('GATEWAY WS HANDSHAKE FAILING')}")
        print(f"     TCP connects but WebSocket upgrade or Hermes handshake fails.")
        print()
        print(f"     This usually means:")
        print(f"     a) Something else is on port {gw_port} (not the Hermes adapter)")
        print(f"     b) The adapter version is too old (protocol < 3)")
        print(f"     c) Adapter type mismatch (e.g., demo adapter on hermes port)")
        print()
        step += 1

    # --- Studio failures ---
    if any("Studio" in n for n in failed_names):
        print(f"  {step}. {_Colors.yellow('CLAW3D STUDIO SERVER IS DOWN OR MISCONFIGURED')}")
        print(f"     The Next.js dev server on port {studio_port} is not responding.")
        print()
        print(f"     Quick fixes:")
        print(f"     a) Start the dev server:")
        print(f"        $ cd Claw3D-main")
        print(f"        $ npm run dev")
        print()
        print(f"     b) Or use the launcher:")
        print(f"        $ python LAUNCH_CLAW3D.py")
        print()
        print(f"     c) Check .env.local for misconfigurations:")
        print(f"        Required: CLAW3D_GATEWAY_URL=ws://localhost:{gw_port}")
        print(f"        Required: CLAW3D_GATEWAY_ADAPTER_TYPE=hermes  (or demo)")
        print()
        print(f"     d) If /api/studio returns wrong adapterType, reset persisted settings:")
        print(f"        $ curl http://localhost:{studio_port}/api/studio/reset-adapter")
        print(f"        Or delete ~/.openclaw/claw3d/settings.json")
        print()
        step += 1

    # --- WS Proxy failures ---
    if any("WS Proxy" in n for n in failed_names):
        print(f"  {step}. {_Colors.yellow('BROWSER WEBSOCKET PROXY BROKEN')}")
        print(f"     The Studio server is up, but the /api/gateway/ws proxy")
        print(f"     cannot reach the upstream gateway.")
        print()
        print(f"     Quick fixes:")
        print(f"     a) Verify the gateway is running (Stage 2 checks above)")
        print()
        print(f"     b) Check CSP headers — in dev mode, ensure upgrade-insecure-requests")
        print(f"        is NOT in the Content-Security-Policy (it forces ws:// → wss://).")
        print(f"        File: Claw3D-main/next.config.ts")
        print()
        print(f"     c) If using STUDIO_ACCESS_TOKEN, ensure it matches your browser session.")
        print()
        print(f"     d) Check the Node.js server console for [upgrade] debug logs.")
        print()
        step += 1

    # --- All server-side tests pass but browser still failing ---
    all_passed = not failed_names
    if all_passed:
        print(f"  {step}. {_Colors.green('ALL SERVER-SIDE CHECKS PASSED')}")
        print(f"     The full circuit (LLM → Gateway → Proxy → Handshake) is healthy!")
        print(f"     If the browser still shows \"Timed out connecting to the gateway\",")
        print(f"     the issue is browser-side. Try these steps in order:")
        print()
        print(f"     a) {_Colors.cyan('Hard-refresh the page')}: Ctrl+Shift+R (or Cmd+Shift+R on Mac)")
        print(f"        This clears stale JS state from a prior failed connection.")
        print(f"        The browser only auto-retries AFTER a first successful connect.")
        print()
        print(f"     b) {_Colors.cyan('Clear browser localStorage')}:")
        print(f"        DevTools → Application → Local Storage → localhost:3000 → Clear All")
        print(f"        This removes stale device auth tokens and session state.")
        print()
        print(f"     c) {_Colors.cyan('Check browser DevTools Console')} for these debug messages:")
        print(f"        • [gateway-client] auto-connect  → auto-connect triggered")
        print(f"        • [gateway-browser] socket:open   → WS opened to proxy")
        print(f"        • [gateway-browser] connect-challenge → challenge received")
        print(f"        • [gateway-browser] send-connect  → connect frame sent")
        print(f"        • [gateway-browser] hello-ok      → handshake complete!")
        print(f"        If any of these are missing, the failure is between those steps.")
        print()
        print(f"     d) {_Colors.cyan('Check DevTools Network → WS tab')}:")
        print(f"        Filter: /api/gateway/ws")
        print(f"        • If no WS request appears: auto-connect gate not firing")
        print(f"        • If WS shows 101 but closes: upstream handshake issue")
        print(f"        • If WS shows 4008: connect rejected (auth issue)")
        print()
        print(f"     e) {_Colors.cyan('Restart the Next.js dev server')}:")
        print(f"        $ cd Claw3D-main && npm run dev")
        print(f"        The dev server caches process.env at startup — a restart")
        print(f"        picks up any .env changes made since last start.")
        print()
        print(f"     f) {_Colors.cyan('Reset persisted gateway settings')}:")
        print(f"        $ curl -X POST http://localhost:{studio_port}/api/studio/reset-adapter")
        print(f"        Then hard-refresh. This forces re-detection of the adapter type.")
        print()
        step += 1

    # --- General advice ---
    print(f"  {step}. {_Colors.cyan('GENERAL TROUBLESHOOTING')}")
    print(f"     • Run this script after starting each service to track progress.")
    print(f"     • Use --skip-llm if your model server is on a different machine.")
    print(f"     • Check browser DevTools → Console and Network tabs for WS errors.")
    print(f"     • If 'custom' adapter is persisted but you want 'hermes',")
    print(f"       reset via: curl http://localhost:{studio_port}/api/studio/reset-adapter")
    print(f"     • Verify no stale processes: netstat -ano | findstr \":{gw_port} :{studio_port}\"")
    print()


# ═══════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test the full Claw3D connection circuit: LLM → Gateway → Studio → Browser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Test with defaults (Ollama:11434 → Hermes:18789 → Studio:3000)
  %(prog)s --llm-port 1234          # Use LM Studio instead of Ollama
  %(prog)s --skip-llm               # Skip LLM checks (model on different machine)
  %(prog)s --gw-port 18890          # Test demo adapter directly
  %(prog)s --studio-url http://192.168.1.50:3000  # Remote studio
        """,
    )
    parser.add_argument("--llm-host", default=DEFAULT_LLM_HOST, help="Local LLM host (default: %(default)s)")
    parser.add_argument("--llm-port", type=int, default=DEFAULT_LLM_PORT, help="Local LLM port (default: %(default)s)")
    parser.add_argument("--gw-host", default=DEFAULT_GATEWAY_HOST, help="Gateway host (default: %(default)s)")
    parser.add_argument("--gw-port", type=int, default=DEFAULT_GATEWAY_PORT, help="Gateway port (default: %(default)s)")
    parser.add_argument("--studio-url", default=DEFAULT_STUDIO_URL, help="Claw3D Studio base URL (default: %(default)s)")
    parser.add_argument("--skip-llm", action="store_true", help="Skip local LLM checks")
    parser.add_argument("--skip-inference", action="store_true", help="Skip the inference test (faster)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    return run_full_circuit(
        llm_host=args.llm_host,
        llm_port=args.llm_port,
        gw_host=args.gw_host,
        gw_port=args.gw_port,
        studio_url=args.studio_url,
        skip_llm=args.skip_llm,
        skip_inference=args.skip_inference,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    sys.exit(main())
