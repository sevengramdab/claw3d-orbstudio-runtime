from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

import LAUNCH_ORBSTUDIO as orbstudio_launcher


CLAW3D_DIRNAME = "Claw3D-main"
SUPPORTED_CLAW3D_BACKENDS = {"openclaw", "hermes", "demo", "custom"}
DEFAULT_CUSTOM_GATEWAY_URL = "http://localhost:1234"
DEFAULT_HERMES_ADAPTER_PORT = "18789"
DEFAULT_HERMES_ADAPTER_FALLBACK_PORT = "19444"
DEFAULT_DEMO_ADAPTER_PORT = "18890"
DEFAULT_DEMO_ADAPTER_FALLBACK_PORT = "18891"
CLAW3D_FORCE_SELECTION_ENV = "CLAW3D_GATEWAY_FORCE_SELECTION"
DEFAULT_LM_STUDIO_API_URL: Final[str] = "http://127.0.0.1:1234"


def _claw3d_root(repo_root: Path) -> Path:
    return repo_root / CLAW3D_DIRNAME


def _claw3d_ready_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/studio"


def _lm_studio_models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/v1/models"


def _claw3d_creation_flags(args: list[str]) -> int:
    if orbstudio_launcher._has_flag(args, "--new-console"):
        return getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return 0


def _normalize_claw3d_backend(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if normalized in SUPPORTED_CLAW3D_BACKENDS:
        return normalized
    return None


def _requested_claw3d_backend(args: list[str]) -> str | None:
    requested = orbstudio_launcher._read_flag_value(args, "--backend", "")
    return _normalize_claw3d_backend(requested)


def _port_is_listening(port: str) -> bool:
    try:
        port_num = int(port)
    except (TypeError, ValueError):
        return False

    try:
        with socket.create_connection(("127.0.0.1", port_num), timeout=0.25):
            return True
    except OSError:
        return False


def _find_first_free_port(start_port: int) -> str:
    port = max(start_port, 1)
    while _port_is_listening(str(port)):
        port += 1
    return str(port)


def _resolve_managed_adapter_port(adapter: str, env: dict[str, str]) -> str:
    if adapter == "hermes":
        explicit = env.get("HERMES_ADAPTER_PORT", "").strip()
        if explicit:
            return explicit
        if not _port_is_listening(DEFAULT_HERMES_ADAPTER_PORT):
            return DEFAULT_HERMES_ADAPTER_PORT
        return _find_first_free_port(int(DEFAULT_HERMES_ADAPTER_FALLBACK_PORT))

    if adapter == "demo":
        explicit = env.get("DEMO_ADAPTER_PORT", "").strip()
        if explicit:
            return explicit
        if not _port_is_listening(DEFAULT_DEMO_ADAPTER_PORT):
            return DEFAULT_DEMO_ADAPTER_PORT
        return _find_first_free_port(int(DEFAULT_DEMO_ADAPTER_FALLBACK_PORT))

    return ""


def _claw3d_launch_env(extra_args: list[str]) -> dict[str, str] | None:
    backend = _requested_claw3d_backend(extra_args)
    if not backend:
        return None

    env = dict(os.environ)
    env[CLAW3D_FORCE_SELECTION_ENV] = "1"
    env["CLAW3D_GATEWAY_ADAPTER_TYPE"] = backend
    hermes_port = _resolve_managed_adapter_port("hermes", env)
    demo_port = _resolve_managed_adapter_port("demo", env)

    if backend == "custom":
        env["CLAW3D_GATEWAY_URL"] = orbstudio_launcher._read_flag_value(
            extra_args,
            "--gateway-url",
            env.get("CLAW3D_GATEWAY_URL", DEFAULT_CUSTOM_GATEWAY_URL),
        )
    elif backend == "hermes":
        env["HERMES_ADAPTER_PORT"] = hermes_port
        env["CLAW3D_GATEWAY_URL"] = f"ws://localhost:{hermes_port}"
        env["CLAW3D_GATEWAY_TOKEN"] = ""
    elif backend == "demo":
        env["DEMO_ADAPTER_PORT"] = demo_port
        env["CLAW3D_GATEWAY_URL"] = f"ws://localhost:{demo_port}"
        env["CLAW3D_GATEWAY_TOKEN"] = ""
    else:
        # Override any custom URL from .env.local so Hermes/demo/openclaw can
        # fall back to their gateway-backed defaults cleanly.
        env["CLAW3D_GATEWAY_URL"] = ""
        env["CLAW3D_GATEWAY_TOKEN"] = ""

    return env


def _claw3d_active_backend(base_url: str) -> str | None:
    try:
        with urllib.request.urlopen(_claw3d_ready_url(base_url), timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"[CLAW3D] Could not probe active backend: {type(exc).__name__}: {exc}")
        return None

    gateway = payload.get("settings", {}).get("gateway") if isinstance(payload, dict) else None
    if not isinstance(gateway, dict):
        return None
    adapter_type = gateway.get("adapterType")
    return _normalize_claw3d_backend(adapter_type if isinstance(adapter_type, str) else None)


def inspect_signal_integrity(base_url: str, lm_studio_base_url: str = DEFAULT_LM_STUDIO_API_URL) -> int:
    print("--- SIGNAL INTEGRITY INSPECTION ---")

    status = 0
    try:
        with urllib.request.urlopen(_lm_studio_models_url(lm_studio_base_url), timeout=2) as response:
            headers = response.info()
            cors_header = headers.get("Access-Control-Allow-Origin")
            print(
                f"[CHECK] CORS Shielding: {cors_header if cors_header else 'MISSING (Likely Cause of Failure)'}"
            )

            data = json.loads(response.read().decode("utf-8"))
            models = [model.get("id") for model in data.get("data", []) if isinstance(model, dict) and model.get("id")]
            print(f"[CHECK] Available Blocks in Model Space: {len(models)} loaded.")
    except Exception as exc:
        print(f"[FAULT] Logic Path Interrupted: {exc}")
        status = 1

    try:
        with urllib.request.urlopen(_claw3d_ready_url(base_url), timeout=2) as response:
            config = json.loads(response.read().decode("utf-8"))
            settings = config.get("settings", {}) if isinstance(config, dict) else {}
            gateway = settings.get("gateway", {}) if isinstance(settings, dict) else {}
            route_url = gateway.get("url") or config.get("url") or "<missing>"
            adapter_type = gateway.get("adapterType") or config.get("adapterType") or "<missing>"
            print(f"[CHECK] Studio Routing: Targeting {route_url} via {adapter_type} adapter.")
    except Exception as exc:
        print(f"[FAULT] Studio Control Panel Unreachable: {exc}")
        status = 1

    return status


def _probe_hermes_adapter_http(port: str) -> bool:
    """Probe the hermes adapter HTTP health endpoint on *port*.

    Returns True if the adapter responds with its expected health banner.
    """
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            if body.startswith("Hermes Gateway Adapter"):
                return True
            print(f"[CLAW3D] Hermes adapter on port {port} returned unexpected body: {body!r}")
    except Exception as exc:
        print(f"[CLAW3D] Hermes adapter on port {port} unreachable: {type(exc).__name__}: {exc}")
    return False


def _read_env_local_adapter_type(claw3d_root: Path) -> str | None:
    """Read CLAW3D_GATEWAY_ADAPTER_TYPE from ``.env.local`` (if present)."""
    env_local = claw3d_root / ".env.local"
    if not env_local.exists():
        return None
    try:
        text = env_local.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "CLAW3D_GATEWAY_ADAPTER_TYPE":
            return _normalize_claw3d_backend(value.strip())
    return None


def _warn_env_local_conflict(claw3d_root: Path, requested_backend: str | None) -> None:
    """Warn if ``.env.local`` declares an adapter type that disagrees with *requested_backend*."""
    if not requested_backend:
        return
    env_local = claw3d_root / ".env.local"
    if not env_local.exists():
        return
    try:
        text = env_local.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "CLAW3D_GATEWAY_ADAPTER_TYPE":
            env_adapter = value.strip().lower()
            if env_adapter and env_adapter != requested_backend:
                print(
                    f"[CLAW3D] WARNING: .env.local sets CLAW3D_GATEWAY_ADAPTER_TYPE={env_adapter}"
                    f" but --backend {requested_backend} was requested."
                    f" The --backend flag takes precedence via launch env override."
                )
            break


def _claw3d_dependencies_ready(claw3d_root: Path) -> bool:
    return (
        (claw3d_root / "node_modules").exists()
        and (claw3d_root / "node_modules" / "next" / "package.json").exists()
    )


def _ensure_claw3d_dependencies(repo_root: Path) -> bool:
    claw3d_root = _claw3d_root(repo_root)
    if not claw3d_root.exists():
        print("[CLAW3D] Missing Claw3D-main in the repository root")
        return False

    orbstudio_launcher._ensure_node_tooling_ready(repo_root)
    npm_command = orbstudio_launcher._resolve_npm_command()
    if not npm_command:
        print("[CLAW3D] npm was not found. Install Node.js 20+ with npm 10+ before launching Claw3D.")
        return False

    if _claw3d_dependencies_ready(claw3d_root):
        return True

    print("[CLAW3D] Installing Claw3D dependencies...")
    install_command = [npm_command, "install"]
    install_result = orbstudio_launcher._run_pixel_engine_command(install_command, claw3d_root)
    if not orbstudio_launcher._command_succeeded(install_result):
        print("[CLAW3D] npm install failed for Claw3D-main.")
        orbstudio_launcher._report_command_failure(install_command, install_result)
        if orbstudio_launcher._looks_like_eperm_error(install_result) and orbstudio_launcher._maybe_recover_from_eperm(claw3d_root):
            print("[CLAW3D] Retrying npm install after approved cleanup...")
            install_result = orbstudio_launcher._run_pixel_engine_command(install_command, claw3d_root)
        if not orbstudio_launcher._command_succeeded(install_result):
            return False

    return True


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    claw3d_root = _claw3d_root(repo_root)
    if not claw3d_root.exists():
        print("[CLAW3D] Missing Claw3D-main in the repository root")
        return 1

    extra_args = sys.argv[1:]
    force_restart = orbstudio_launcher._has_flag(extra_args, "--force-restart")
    host = orbstudio_launcher._read_flag_value(extra_args, "--host", "127.0.0.1")
    port = orbstudio_launcher._read_flag_value(extra_args, "--port", "3000")
    base_url = f"http://{host}:{port}"
    if orbstudio_launcher._has_flag(extra_args, "--inspect-signal-integrity"):
        lm_studio_url = orbstudio_launcher._read_flag_value(
            extra_args,
            "--lm-studio-url",
            DEFAULT_LM_STUDIO_API_URL,
        )
        return inspect_signal_integrity(base_url, lm_studio_url)

    ready_url = _claw3d_ready_url(base_url)
    requested_backend = _requested_claw3d_backend(extra_args)
    launch_env = _claw3d_launch_env(extra_args)

    # When no explicit --backend flag was given, check .env.local for an
    # adapter type preference and propagate it as a force-selection so the
    # settings resolution chain in studio-settings.js won't be overridden by
    # stale persisted settings.json entries.
    env_local_adapter = _read_env_local_adapter_type(claw3d_root)
    if not requested_backend and env_local_adapter:
        if launch_env is None:
            launch_env = dict(os.environ)
        launch_env[CLAW3D_FORCE_SELECTION_ENV] = "1"
        launch_env["CLAW3D_GATEWAY_ADAPTER_TYPE"] = env_local_adapter
        if env_local_adapter == "hermes":
            hermes_port = _resolve_managed_adapter_port("hermes", launch_env)
            launch_env["HERMES_ADAPTER_PORT"] = hermes_port
            launch_env["CLAW3D_GATEWAY_URL"] = f"ws://localhost:{hermes_port}"
            launch_env["CLAW3D_GATEWAY_TOKEN"] = ""
        elif env_local_adapter == "demo":
            demo_port = _resolve_managed_adapter_port("demo", launch_env)
            launch_env["DEMO_ADAPTER_PORT"] = demo_port
            launch_env["CLAW3D_GATEWAY_URL"] = f"ws://localhost:{demo_port}"
            launch_env["CLAW3D_GATEWAY_TOKEN"] = ""
        print(f"[CLAW3D] .env.local declares adapter type '{env_local_adapter}' — injecting force-selection.")

    _warn_env_local_conflict(claw3d_root, requested_backend)

    if not _ensure_claw3d_dependencies(repo_root):
        return 1

    if orbstudio_launcher._url_available(ready_url):
        # Detect stale server — if server-side files changed, restart so fixes take effect.
        server_stale = False
        state_file = repo_root / ".claw3d_launcher_state.json"
        try:
            if state_file.exists():
                launch_time = state_file.stat().st_mtime
                server_dir = claw3d_root / "server"
                if server_dir.exists():
                    for f in server_dir.iterdir():
                        if f.is_file() and f.stat().st_mtime > launch_time:
                            server_stale = True
                            print(f"[CLAW3D] Server code changed ({f.name}) since last start — restarting.")
                            break
                env_local = claw3d_root / ".env.local"
                if not server_stale and env_local.exists() and env_local.stat().st_mtime > launch_time:
                    server_stale = True
                    print("[CLAW3D] .env.local changed since last start — restarting.")
        except OSError:
            pass

        active_backend = _claw3d_active_backend(base_url) if requested_backend else None
        if requested_backend and active_backend and active_backend != requested_backend:
            server_stale = True
            print(
                f"[CLAW3D] Active backend is {active_backend}; restarting with requested backend {requested_backend}."
            )

        # Also detect env-local adapter type disagreement even without --backend.
        # This catches stale persisted settings when only .env.local is configured.
        if not requested_backend and env_local_adapter:
            active_backend = active_backend or _claw3d_active_backend(base_url)
            if active_backend and active_backend != env_local_adapter:
                server_stale = True
                print(
                    f"[CLAW3D] Active backend is {active_backend} but .env.local wants {env_local_adapter}; restarting."
                )

        if not force_restart and not server_stale:
            print(f"[CLAW3D] Existing server detected at {base_url}. Opening popout browser.")
            orbstudio_launcher._open_popout_browser(base_url)
            return 0

        print(f"[CLAW3D] Existing server detected at {base_url}. Recycling process on port {port}.")
        # Clear persisted adapter type so fresh .env.local values take clean precedence.
        try:
            reset_req = urllib.request.Request(
                f"{base_url}/api/studio/reset-adapter", method="POST",
            )
            with urllib.request.urlopen(reset_req, timeout=3) as resp:
                if resp.status == 200:
                    print("[CLAW3D] Cleared persisted gateway adapter settings.")
        except Exception:
            pass
        orbstudio_launcher._terminate_server_on_port(port)
        if not orbstudio_launcher._wait_for_port_release(port, probe_url=ready_url):
            print(f"[CLAW3D] Port {port} did not fully release before relaunch.")
            return 1

    npm_command = orbstudio_launcher._resolve_npm_command()
    if not npm_command:
        print("[CLAW3D] npm was not found after dependency setup.")
        return 1

    creation_flags = _claw3d_creation_flags(extra_args)
    process = subprocess.Popen(
        [npm_command, "run", "dev"],
        cwd=claw3d_root,
        creationflags=creation_flags,
        env=launch_env,
    )

    for _ in range(120):
        if orbstudio_launcher._url_available(ready_url):
            # Record launch time for stale detection on next invocation.
            try:
                state_file = repo_root / ".claw3d_launcher_state.json"
                state_file.write_text(json.dumps({"launched_at": time.time()}), encoding="utf-8")
            except OSError:
                pass
            # Verify hermes adapter is alive if that's the target backend.
            if requested_backend == "hermes":
                hermes_port = (launch_env or {}).get("HERMES_ADAPTER_PORT", DEFAULT_HERMES_ADAPTER_PORT)
                if _probe_hermes_adapter_http(hermes_port):
                    print(f"[CLAW3D] Hermes adapter confirmed on port {hermes_port}.")
                else:
                    print(f"[CLAW3D] WARNING: Hermes adapter not responding on port {hermes_port}.")
            print(f"[CLAW3D] Server ready at {base_url}. Opening popout browser.")
            orbstudio_launcher._open_popout_browser(base_url)
            return 0
        if process.poll() is not None:
            print(f"[CLAW3D] Dev server exited early with code {process.returncode}.")
            return int(process.returncode or 1)
        time.sleep(0.5)

    print(f"[CLAW3D] Dev server launch started, but {base_url} did not become ready in time.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())