from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from shutil import copy2, rmtree, which


PIXEL_ENGINE_DIRNAME = "orbstudio_pixel_engine"
PIXEL_ENGINE_ENTRYPOINT = Path("dist") / "index.html"
PIXEL_ENGINE_WEB_DIR = Path("web")
PIXEL_ENGINE_MATERIALIZED_WEB_MARKER = 'name="orbstudio-bundle" content="materialized-web"'
LAUNCHER_STATE_PATH = Path("outputs") / "orbstudio" / "launcher_state.json"
CIRCUIT_BREAKER_V2_PATH = Path("ORBSTUDIO CORE") / "goldeneye_circuit_breaker_v2.py"
PIXEL_ENGINE_BUILD_SOURCES = (
    Path("index.html"),
    Path("package.json"),
    Path("tsconfig.json"),
    Path("tsconfig.node.json"),
    Path("vite.config.ts"),
)


def _read_flag_value(args: list[str], flag: str, default: str) -> str:
    for index, value in enumerate(args[:-1]):
        if value == flag:
            return args[index + 1]
    return default


def _has_flag(args: list[str], flag: str) -> bool:
    return any(value == flag for value in args)


def _healthcheck(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _url_available(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= getattr(response, "status", 200) < 300
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def _terminate_server_on_port(port: str) -> bool:
    if os.name != "nt":
        return False

    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError):
        return False

    pids: set[str] = set()
    needle = f":{port}"
    for line in result.stdout.splitlines():
        if needle not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if parts:
            pid = parts[-1].strip()
            if pid.isdigit():
                pids.add(pid)

    terminated = False
    for pid in sorted(pids):
        try:
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], check=False, capture_output=True, text=True)
            terminated = True
        except OSError:
            continue
    return terminated


def _is_port_listening(port: str) -> bool:
    if os.name != "nt":
        return False

    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError):
        return False

    needle = f":{port}"
    for line in result.stdout.splitlines():
        if needle in line and "LISTENING" in line.upper():
            return True
    return False


def _wait_for_port_release(
    port: str,
    *,
    probe_url: str | None = None,
    timeout: float = 20.0,
    poll_interval: float = 0.5,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        port_held = _is_port_listening(port)
        url_live = _url_available(probe_url, timeout=0.75) if probe_url else False
        if not port_held and not url_live:
          return True
        time.sleep(poll_interval)
    return not _is_port_listening(port)


def _browser_search_roots() -> list[Path]:
    return [
        Path.home() / "AppData" / "Local",
        Path(r"C:/Program Files"),
        Path(r"C:/Program Files (x86)"),
    ]


def _iter_browser_candidates() -> list[Path]:
    browser_paths = [
        ("Microsoft/Edge/Application/msedge.exe"),
        ("Google/Chrome/Application/chrome.exe"),
        ("BraveSoftware/Brave-Browser/Application/brave.exe"),
    ]
    candidates: list[Path] = []
    for root in _browser_search_roots():
        for relative in browser_paths:
            candidate = root / relative
            if candidate.exists():
                candidates.append(candidate)

    for command in ("msedge", "chrome", "brave", "chromium", "chromium-browser"):
        resolved = which(command)
        if resolved:
            candidates.append(Path(resolved))

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(candidate)
    return deduped


def _open_popout_browser(url: str) -> bool:
    creation_flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    # Append a cache-buster so Chrome --app mode does not reuse a stale app
    # window that was previously opened at a different path on the same origin.
    bust = f"{'&' if '?' in url else '?'}_t={int(time.time())}"
    app_url = url + bust
    for browser_path in _iter_browser_candidates():
        command = [
            str(browser_path),
            f"--app={app_url}",
            "--new-window",
            "--window-size=1680,1050",
        ]
        try:
            subprocess.Popen(command, creationflags=creation_flags)
            return True
        except OSError:
            continue
    return webbrowser.open(url)


def _pixel_engine_root(repo_root: Path) -> Path:
    return repo_root / PIXEL_ENGINE_DIRNAME


def _launcher_state_file(repo_root: Path) -> Path:
    return repo_root / LAUNCHER_STATE_PATH


def _load_launcher_state(repo_root: Path) -> dict[str, object]:
    state_path = _launcher_state_file(repo_root)
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_launcher_state(repo_root: Path, state: dict[str, object]) -> None:
    state_path = _launcher_state_file(repo_root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _prompt_yes_no(message: str, *, default: bool = False) -> bool | None:
    stdin = getattr(sys, "stdin", None)
    if stdin is None or not stdin.isatty():
        return None

    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        try:
            response = input(message + suffix).strip().lower()
        except EOFError:
            return None

        if not response:
            return default
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        print("[ORBSTUDIO] Please answer yes or no.")


def _load_circuit_breaker_v2_module(repo_root: Path):
    module_path = repo_root / CIRCUIT_BREAKER_V2_PATH
    if not module_path.exists():
        return None

    spec = importlib.util.spec_from_file_location("goldeneye_circuit_breaker_v2", module_path)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_node_tooling_ready(repo_root: Path):
    try:
        module = _load_circuit_breaker_v2_module(repo_root)
    except Exception as exc:
        print(f"[ORBSTUDIO] Failed to load circuit breaker v2: {exc}")
        return None

    if module is None:
        return None

    assess = getattr(module, "assess_node_tooling", None)
    if not callable(assess):
        print("[ORBSTUDIO] Circuit breaker v2 is present but does not expose assess_node_tooling().")
        return None

    try:
        status = assess()
    except Exception as exc:
        print(f"[ORBSTUDIO] Circuit breaker v2 failed while probing Node.js: {exc}")
        return None

    for issue in getattr(status, "issues", []):
        print(f"[ORBSTUDIO] {issue}")

    state = _load_launcher_state(repo_root)
    if getattr(status, "persist_recommended", False) and not state.get("node_path_persistence_prompted"):
        decision = _prompt_yes_no(
            "[ORBSTUDIO] Node.js works for this launcher session, but your user PATH is still missing the discovered Node.js directories. Persist them for future terminals?"
        )
        if decision is not None:
            state["node_path_persistence_prompted"] = True
            if decision:
                try:
                    status = assess(persist=True)
                except Exception as exc:
                    print(f"[ORBSTUDIO] Failed to persist Node.js PATH entries: {exc}")
                else:
                    if getattr(status, "user_path_updated", False):
                        print("[ORBSTUDIO] User PATH updated for future terminals.")
                    elif getattr(status, "user_path_contains_discovered", False):
                        print("[ORBSTUDIO] User PATH already included the discovered Node.js directories.")
                    state["node_path_persisted"] = bool(getattr(status, "user_path_contains_discovered", False))
            else:
                state["node_path_persisted"] = False
            _save_launcher_state(repo_root, state)

    return status


def _pixel_engine_entrypoint(repo_root: Path) -> Path:
    return _pixel_engine_root(repo_root) / PIXEL_ENGINE_ENTRYPOINT


def _iter_pixel_engine_sources(pixel_engine_root: Path) -> list[Path]:
    sources: list[Path] = []
    for relative_path in PIXEL_ENGINE_BUILD_SOURCES:
        candidate = pixel_engine_root / relative_path
        if candidate.exists():
            sources.append(candidate)

    src_root = pixel_engine_root / "src"
    if src_root.exists():
        for candidate in src_root.rglob("*"):
            if candidate.is_file():
                sources.append(candidate)

    web_root = pixel_engine_root / PIXEL_ENGINE_WEB_DIR
    if web_root.exists():
        for candidate in web_root.rglob("*"):
            if candidate.is_file():
                sources.append(candidate)

    return sources


def _materialize_pixel_engine_web_bundle(repo_root: Path) -> bool:
    pixel_engine_root = _pixel_engine_root(repo_root)
    web_root = pixel_engine_root / PIXEL_ENGINE_WEB_DIR
    entrypoint = web_root / "index.html"
    if not entrypoint.exists():
        return False

    dist_root = pixel_engine_root / "dist"
    dist_root.mkdir(parents=True, exist_ok=True)

    for asset in web_root.rglob("*"):
        if not asset.is_file():
            continue
        target = dist_root / asset.relative_to(web_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(asset, target)

    return (dist_root / "index.html").exists()


def _pixel_engine_build_needed(repo_root: Path) -> bool:
    entrypoint = _pixel_engine_entrypoint(repo_root)
    if not entrypoint.exists():
        return True

    try:
        dist_mtime = entrypoint.stat().st_mtime
    except OSError:
        return True

    for source_path in _iter_pixel_engine_sources(_pixel_engine_root(repo_root)):
        try:
            if source_path.stat().st_mtime > dist_mtime:
                return True
        except OSError:
            return True
    return False


def _pixel_engine_dist_is_materialized_fallback(repo_root: Path) -> bool:
    entrypoint = _pixel_engine_entrypoint(repo_root)
    if not entrypoint.exists():
        return False

    try:
        html = entrypoint.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    has_legacy_marker = "Browser renderer for the OrbStudio room scene" in html and "/pixel_engine.js" in html
    has_materialized_marker = PIXEL_ENGINE_MATERIALIZED_WEB_MARKER in html and "/pixel_engine.js" in html
    return has_legacy_marker or has_materialized_marker


def _resolve_npm_command() -> str | None:
    for command in ("npm.cmd", "npm.exe", "npm"):
        resolved = which(command)
        if resolved:
            return resolved

    if os.name != "nt":
        return None

    candidates = [
        Path(r"C:/Program Files/nodejs/npm.cmd"),
        Path(r"C:/Program Files (x86)/nodejs/npm.cmd"),
        Path.home() / "AppData" / "Roaming" / "npm" / "npm.cmd",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _run_pixel_engine_command(command: list[str], cwd: Path):
    try:
        result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    return result


def _command_succeeded(result) -> bool:
    if isinstance(result, bool):
        return result
    if result is None:
        return False
    return getattr(result, "returncode", 1) == 0


def _command_output(result) -> str:
    if result is None or isinstance(result, bool):
        return ""

    output_parts = []
    stdout = getattr(result, "stdout", "")
    stderr = getattr(result, "stderr", "")
    if stdout:
        output_parts.append(stdout.strip())
    if stderr:
        output_parts.append(stderr.strip())
    return "\n".join(part for part in output_parts if part)


def _report_command_failure(command: list[str], result) -> None:
    print(f"[ORBSTUDIO] Command failed: {' '.join(command)}")
    output = _command_output(result)
    if output:
        print(output)


def _looks_like_eperm_error(result) -> bool:
    return "eperm" in _command_output(result).lower()


def _maybe_recover_from_eperm(cwd: Path) -> bool:
    node_modules = cwd / "node_modules"
    print(
        "[ORBSTUDIO] npm reported an EPERM-style permission lock. Close VS Code, file search, or Explorer windows that may still be holding node_modules open."
    )
    decision = _prompt_yes_no(
        f"[ORBSTUDIO] Remove {node_modules} and retry once?",
        default=False,
    )
    if decision is not True:
        return False

    try:
        if node_modules.exists():
            rmtree(node_modules)
        return True
    except OSError as exc:
        print(f"[ORBSTUDIO] Failed to remove {node_modules}: {exc}")
        return False


def _ensure_pixel_engine_bundle(repo_root: Path) -> bool:
    pixel_engine_root = _pixel_engine_root(repo_root)
    if not pixel_engine_root.exists():
        return _pixel_engine_entrypoint(repo_root).exists()

    build_needed = _pixel_engine_build_needed(repo_root)
    dist_is_fallback = _pixel_engine_dist_is_materialized_fallback(repo_root)
    if not build_needed and not dist_is_fallback:
        return _pixel_engine_entrypoint(repo_root).exists()

    _ensure_node_tooling_ready(repo_root)
    npm_command = _resolve_npm_command()
    if not npm_command:
        print(
            "[ORBSTUDIO] Pixel engine bundle is missing or stale, but npm was not found. "
            "Materializing the browser renderer instead."
        )
        return _materialize_pixel_engine_web_bundle(repo_root)

    if dist_is_fallback:
        print("[ORBSTUDIO] Replacing fallback pixel engine bundle with the full frontend build...")

    if not (pixel_engine_root / "node_modules").exists():
        print("[ORBSTUDIO] Installing OrbStudio pixel engine dependencies...")
        install_command = [npm_command, "install"]
        install_result = _run_pixel_engine_command(install_command, pixel_engine_root)
        if not _command_succeeded(install_result):
            print("[ORBSTUDIO] npm install failed for orbstudio_pixel_engine.")
            _report_command_failure(install_command, install_result)
            if _looks_like_eperm_error(install_result) and _maybe_recover_from_eperm(pixel_engine_root):
                print("[ORBSTUDIO] Retrying npm install after approved cleanup...")
                install_result = _run_pixel_engine_command(install_command, pixel_engine_root)
            if not _command_succeeded(install_result):
                if dist_is_fallback:
                    print("[ORBSTUDIO] Refusing to reopen the materialized browser bundle as a silent fallback.")
                    return False
                return _pixel_engine_entrypoint(repo_root).exists()

    print("[ORBSTUDIO] Building OrbStudio pixel engine bundle...")
    build_command = [npm_command, "run", "build"]
    build_result = _run_pixel_engine_command(build_command, pixel_engine_root)
    if not _command_succeeded(build_result):
        print("[ORBSTUDIO] npm run build failed for orbstudio_pixel_engine.")
        _report_command_failure(build_command, build_result)
        if _looks_like_eperm_error(build_result) and _maybe_recover_from_eperm(pixel_engine_root):
            print("[ORBSTUDIO] Retrying OrbStudio pixel engine build after approved cleanup...")
            build_result = _run_pixel_engine_command(build_command, pixel_engine_root)
        if not _command_succeeded(build_result):
            if dist_is_fallback:
                print("[ORBSTUDIO] Refusing to reopen the materialized browser bundle as a silent fallback.")
                return False
            return _pixel_engine_entrypoint(repo_root).exists()

    if _pixel_engine_entrypoint(repo_root).exists() and not _pixel_engine_dist_is_materialized_fallback(repo_root):
        return True

    print("[ORBSTUDIO] Pixel engine build did not produce a usable frontend bundle.")
    return False


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    update_script = repo_root / "update_game_ini.py"

    if not venv_python.exists():
        print("[ORBSTUDIO] Missing virtual environment at .venv\\Scripts\\python.exe")
        return 1

    if not update_script.exists():
        print("[ORBSTUDIO] Missing update_game_ini.py in the repository root")
        return 1

    extra_args = sys.argv[1:]
    teleprinter_requested = _has_flag(extra_args, "--teleprinter")
    pixel_engine_requested = not teleprinter_requested or _has_flag(extra_args, "--pixel-engine")
    force_restart = _has_flag(extra_args, "--force-restart")
    with_gateway = _has_flag(extra_args, "--with-gateway")
    forwarded_args = [arg for arg in extra_args if arg not in {"--pixel-engine", "--teleprinter", "--force-restart", "--with-gateway"}]
    host = _read_flag_value(extra_args, "--host", "127.0.0.1")
    port = _read_flag_value(extra_args, "--port", "8765")
    gateway_port = _read_flag_value(extra_args, "--gateway-port", "18890")
    base_url = f"http://{host}:{port}"
    target_url = f"{base_url}/pixel-engine" if pixel_engine_requested else base_url

    # --- Demo gateway co-launch ---
    gateway_process = None
    if with_gateway:
        gateway_script = repo_root / "Claw3D-main" / "server" / "demo-gateway-adapter.js"
        if gateway_script.exists():
            if _is_port_listening(gateway_port):
                print(f"[ORBSTUDIO] Demo gateway already running on port {gateway_port}.")
            else:
                node_cmd = which("node") or which("node.exe")
                if node_cmd:
                    print(f"[ORBSTUDIO] Starting demo gateway on port {gateway_port}...")
                    gateway_env = os.environ.copy()
                    gateway_env["DEMO_ADAPTER_PORT"] = gateway_port
                    creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                    try:
                        gateway_process = subprocess.Popen(
                            [node_cmd, str(gateway_script)],
                            cwd=str(repo_root / "Claw3D-main"),
                            env=gateway_env,
                            creationflags=creation_flags,
                        )
                        # Wait briefly for it to start
                        for _ in range(10):
                            if _is_port_listening(gateway_port):
                                print(f"[ORBSTUDIO] Demo gateway ready on ws://localhost:{gateway_port}")
                                break
                            time.sleep(0.3)
                    except OSError as exc:
                        print(f"[ORBSTUDIO] Failed to start demo gateway: {exc}")
                else:
                    print("[ORBSTUDIO] Node.js not found — cannot start demo gateway.")
        else:
            print(f"[ORBSTUDIO] Demo gateway script not found at {gateway_script}")


    if pixel_engine_requested:
        if not _ensure_pixel_engine_bundle(repo_root):
            print("[ORBSTUDIO] Pixel engine bundle is unavailable. Falling back to the teleprinter route.")
            pixel_engine_requested = False
            target_url = base_url
        elif _pixel_engine_dist_is_materialized_fallback(repo_root):
            print("[ORBSTUDIO] Only the materialized browser bundle is available. Using the teleprinter route instead.")
            pixel_engine_requested = False
            target_url = base_url

    if _healthcheck(base_url):
        target_ready = _url_available(target_url)

        # Detect stale server — if the backend script has been modified since the
        # server process started, auto-restart so code changes take effect.
        server_stale = False
        if target_ready:
            try:
                server_mtime = update_script.stat().st_mtime
                # Compare against the launcher state file which is written at launch.
                state_file = repo_root / ".orbstudio_launcher_state.json"
                if state_file.exists():
                    launch_time = state_file.stat().st_mtime
                    if server_mtime > launch_time:
                        server_stale = True
                        print(f"[ORBSTUDIO] Backend code changed since last server start — restarting.")
            except OSError:
                pass

        if not force_restart and not server_stale and target_ready:
            print(f"[ORBSTUDIO] Existing server detected at {base_url}. Opening popout browser.")
            _open_popout_browser(target_url)
            return 0

        print(f"[ORBSTUDIO] Existing server at {base_url} is stale for {target_url}. Recycling process on port {port}.")
        _terminate_server_on_port(port)
        if not _wait_for_port_release(port, probe_url=base_url):
            print(f"[ORBSTUDIO] Port {port} did not fully release before relaunch.")
            return 1

    cmd = [
        str(venv_python),
        str(update_script),
        "--serve",
        "--host",
        host,
        "--port",
        port,
        "--recovery-policy",
        "cautious",
        "--bootstrap-report",
    ]

    if forwarded_args:
        cmd.extend(forwarded_args)

    creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    process = subprocess.Popen(cmd, cwd=repo_root, creationflags=creation_flags)

    for _ in range(30):
        if _healthcheck(base_url):
            # Record launch time so the next invocation can detect stale code.
            try:
                state_file = repo_root / ".orbstudio_launcher_state.json"
                state_file.write_text(json.dumps({"launched_at": time.time()}), encoding="utf-8")
            except OSError:
                pass
            print(f"[ORBSTUDIO] Server ready at {base_url}. Opening popout browser.")
            _open_popout_browser(target_url)
            return 0
        if process.poll() is not None:
            return int(process.returncode or 1)
        time.sleep(0.5)

    print(f"[ORBSTUDIO] Server launch started, but {base_url} did not become ready in time.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())