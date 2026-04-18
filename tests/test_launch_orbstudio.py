from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


_MODULE_PATH = Path(__file__).resolve().parents[1] / "LAUNCH_ORBSTUDIO.py"
_SPEC = importlib.util.spec_from_file_location("launch_orbstudio", _MODULE_PATH)
assert _SPEC and _SPEC.loader
launch_orbstudio = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launch_orbstudio)

_CIRCUIT_BREAKER_MODULE_PATH = Path(__file__).resolve().parents[1] / "ORBSTUDIO CORE" / "goldeneye_circuit_breaker_v2.py"
_CIRCUIT_BREAKER_SPEC = importlib.util.spec_from_file_location(
    "goldeneye_circuit_breaker_v2",
    _CIRCUIT_BREAKER_MODULE_PATH,
)
assert _CIRCUIT_BREAKER_SPEC and _CIRCUIT_BREAKER_SPEC.loader
goldeneye_circuit_breaker_v2 = importlib.util.module_from_spec(_CIRCUIT_BREAKER_SPEC)
import sys
sys.modules[_CIRCUIT_BREAKER_SPEC.name] = goldeneye_circuit_breaker_v2
_CIRCUIT_BREAKER_SPEC.loader.exec_module(goldeneye_circuit_breaker_v2)


class LaunchOrbStudioTests(unittest.TestCase):
    def test_wait_for_port_release_returns_true_after_listener_clears(self) -> None:
        with patch.object(launch_orbstudio, "_is_port_listening", side_effect=[True, False]), patch.object(
            launch_orbstudio,
            "_url_available",
            return_value=False,
        ), patch.object(launch_orbstudio.time, "sleep", return_value=None):
            released = launch_orbstudio._wait_for_port_release("8765", probe_url="http://127.0.0.1:8765", timeout=1.0, poll_interval=0.01)

        self.assertTrue(released)

    def test_detects_materialized_fallback_dist_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dist_root = root / "orbstudio_pixel_engine" / "dist"
            dist_root.mkdir(parents=True, exist_ok=True)
            (dist_root / "index.html").write_text(
                '<html><meta name="orbstudio-bundle" content="materialized-web" /><script type="module" src="/pixel_engine.js"></script></html>',
                encoding="utf-8",
            )

            self.assertTrue(launch_orbstudio._pixel_engine_dist_is_materialized_fallback(root))

    def test_ensure_pixel_engine_bundle_materializes_web_bundle_without_npm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixel_root = root / "orbstudio_pixel_engine"
            web_root = pixel_root / "web"
            web_root.mkdir(parents=True, exist_ok=True)
            (pixel_root / "package.json").write_text("{}", encoding="utf-8")
            (web_root / "index.html").write_text("<html>web</html>", encoding="utf-8")
            (web_root / "pixel_engine.js").write_text("console.log('web');", encoding="utf-8")
            (web_root / "pixel_engine.css").write_text("body{}", encoding="utf-8")

            with patch.object(launch_orbstudio, "_resolve_npm_command", return_value=None):
                ready = launch_orbstudio._ensure_pixel_engine_bundle(root)

            self.assertTrue(ready)
            self.assertEqual((pixel_root / "dist" / "index.html").read_text(encoding="utf-8"), "<html>web</html>")

    def test_ensure_pixel_engine_bundle_builds_missing_dist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixel_root = root / "orbstudio_pixel_engine"
            src_root = pixel_root / "src"
            src_root.mkdir(parents=True, exist_ok=True)
            (pixel_root / "package.json").write_text("{}", encoding="utf-8")
            (pixel_root / "index.html").write_text("<html></html>", encoding="utf-8")
            (src_root / "main.ts").write_text("console.log('ok');", encoding="utf-8")

            commands: list[list[str]] = []

            def fake_run(
                command: list[str],
                cwd: Path,
                check: bool = False,
                capture_output: bool = False,
                text: bool = False,
            ) -> SimpleNamespace:
                commands.append(command)
                if command[-1] == "install":
                    (cwd / "node_modules").mkdir(exist_ok=True)
                if command[-2:] == ["run", "build"]:
                    dist_root = cwd / "dist"
                    dist_root.mkdir(exist_ok=True)
                    (dist_root / "index.html").write_text("<html>built</html>", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(launch_orbstudio, "_resolve_npm_command", return_value="npm.cmd"), patch.object(
                launch_orbstudio.subprocess,
                "run",
                side_effect=fake_run,
            ):
                ready = launch_orbstudio._ensure_pixel_engine_bundle(root)

        self.assertTrue(ready)
        self.assertEqual(commands, [["npm.cmd", "install"], ["npm.cmd", "run", "build"]])

    def test_ensure_pixel_engine_bundle_rebuilds_materialized_fallback_when_npm_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixel_root = root / "orbstudio_pixel_engine"
            src_root = pixel_root / "src"
            dist_root = pixel_root / "dist"
            src_root.mkdir(parents=True, exist_ok=True)
            dist_root.mkdir(parents=True, exist_ok=True)
            (pixel_root / "package.json").write_text("{}", encoding="utf-8")
            (pixel_root / "index.html").write_text("<html><body><div id=\"app\"></div><script type=\"module\" src=\"/src/main.ts\"></script></body></html>", encoding="utf-8")
            (src_root / "main.ts").write_text("console.log('built');", encoding="utf-8")
            (dist_root / "index.html").write_text(
                '<html><meta name="orbstudio-bundle" content="materialized-web" /><script type="module" src="/pixel_engine.js"></script></html>',
                encoding="utf-8",
            )

            commands: list[list[str]] = []

            def fake_run(
                command: list[str],
                cwd: Path,
                check: bool = False,
                capture_output: bool = False,
                text: bool = False,
            ) -> SimpleNamespace:
                commands.append(command)
                if command[-1] == "install":
                    (cwd / "node_modules").mkdir(exist_ok=True)
                if command[-2:] == ["run", "build"]:
                    (cwd / "dist" / "index.html").write_text("<html>built</html>", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(launch_orbstudio, "_resolve_npm_command", return_value="npm.cmd"), patch.object(
                launch_orbstudio.subprocess,
                "run",
                side_effect=fake_run,
            ):
                ready = launch_orbstudio._ensure_pixel_engine_bundle(root)

        self.assertTrue(ready)
        self.assertEqual(commands, [["npm.cmd", "install"], ["npm.cmd", "run", "build"]])

    def test_ensure_pixel_engine_bundle_refuses_existing_fallback_if_build_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixel_root = root / "orbstudio_pixel_engine"
            dist_root = pixel_root / "dist"
            dist_root.mkdir(parents=True, exist_ok=True)
            (pixel_root / "package.json").write_text("{}", encoding="utf-8")
            (dist_root / "index.html").write_text(
                '<html><meta name="orbstudio-bundle" content="materialized-web" /><script type="module" src="/pixel_engine.js"></script></html>',
                encoding="utf-8",
            )

            with patch.object(launch_orbstudio, "_resolve_npm_command", return_value="npm.cmd"), patch.object(
                launch_orbstudio,
                "_run_pixel_engine_command",
                return_value=False,
            ):
                ready = launch_orbstudio._ensure_pixel_engine_bundle(root)

        self.assertFalse(ready)

    def test_main_falls_back_to_teleprinter_when_pixel_engine_bundle_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_ORBSTUDIO.py"
            launcher_path.write_text("", encoding="utf-8")
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")
            update_script = root / "update_game_ini.py"
            update_script.write_text("", encoding="utf-8")

            with patch.object(launch_orbstudio, "__file__", str(launcher_path)), patch.object(
                launch_orbstudio,
                "_ensure_pixel_engine_bundle",
                return_value=False,
            ), patch.object(
                launch_orbstudio,
                "_healthcheck",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_url_available",
                return_value=True,
            ), patch.object(launch_orbstudio.subprocess, "Popen") as popen_mock, patch.object(
                launch_orbstudio,
                "_open_popout_browser",
                return_value=True,
            ) as open_mock:
                result = launch_orbstudio.main()

        self.assertEqual(result, 0)
        popen_mock.assert_not_called()
        open_mock.assert_called_once_with("http://127.0.0.1:8765")

    def test_main_falls_back_to_teleprinter_when_only_materialized_bundle_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_ORBSTUDIO.py"
            launcher_path.write_text("", encoding="utf-8")
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")
            update_script = root / "update_game_ini.py"
            update_script.write_text("", encoding="utf-8")

            with patch.object(launch_orbstudio, "__file__", str(launcher_path)), patch.object(
                launch_orbstudio,
                "_ensure_pixel_engine_bundle",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_pixel_engine_dist_is_materialized_fallback",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_healthcheck",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_url_available",
                return_value=True,
            ), patch.object(launch_orbstudio.subprocess, "Popen") as popen_mock, patch.object(
                launch_orbstudio,
                "_open_popout_browser",
                return_value=True,
            ) as open_mock:
                result = launch_orbstudio.main()

        self.assertEqual(result, 0)
        popen_mock.assert_not_called()
        open_mock.assert_called_once_with("http://127.0.0.1:8765")

    def test_ensure_pixel_engine_bundle_returns_false_without_npm_and_without_web_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixel_root = root / "orbstudio_pixel_engine"
            pixel_root.mkdir(parents=True, exist_ok=True)
            (pixel_root / "package.json").write_text("{}", encoding="utf-8")

            with patch.object(launch_orbstudio, "_resolve_npm_command", return_value=None):
                ready = launch_orbstudio._ensure_pixel_engine_bundle(root)

        self.assertFalse(ready)

    def test_assess_node_tooling_recommends_persistence_when_user_path_missing(self) -> None:
        with patch.object(
            goldeneye_circuit_breaker_v2,
            "discover_node_paths",
            return_value=[r"C:\Program Files\nodejs", r"C:\Users\Shadow\AppData\Roaming\npm"],
        ), patch.object(
            goldeneye_circuit_breaker_v2,
            "get_user_path",
            return_value="",
        ), patch.object(
            goldeneye_circuit_breaker_v2,
            "update_process_path",
            return_value=r"C:\Program Files\nodejs;C:\Users\Shadow\AppData\Roaming\npm",
        ), patch.object(
            goldeneye_circuit_breaker_v2,
            "validate_node_tools",
            return_value=("v22.0.0", "10.1.0", []),
        ):
            status = goldeneye_circuit_breaker_v2.assess_node_tooling()

        self.assertTrue(status.npm_ready)
        self.assertTrue(status.persist_recommended)
        self.assertFalse(status.user_path_contains_discovered)

    def test_ensure_node_tooling_ready_persists_user_path_after_prompt_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assess = Mock(
                side_effect=[
                    SimpleNamespace(
                        issues=[],
                        persist_recommended=True,
                        user_path_updated=False,
                        user_path_contains_discovered=False,
                    ),
                    SimpleNamespace(
                        issues=[],
                        persist_recommended=False,
                        user_path_updated=True,
                        user_path_contains_discovered=True,
                    ),
                ]
            )
            module = SimpleNamespace(assess_node_tooling=assess)

            with patch.object(launch_orbstudio, "_load_circuit_breaker_v2_module", return_value=module), patch.object(
                launch_orbstudio,
                "_prompt_yes_no",
                return_value=True,
            ):
                status = launch_orbstudio._ensure_node_tooling_ready(root)

            state = json.loads((root / "outputs" / "orbstudio" / "launcher_state.json").read_text(encoding="utf-8"))

        self.assertTrue(status.user_path_contains_discovered)
        self.assertEqual(assess.call_count, 2)
        self.assertEqual(assess.call_args_list[1].kwargs, {"persist": True})
        self.assertTrue(state["node_path_persisted"])
        self.assertTrue(state["node_path_persistence_prompted"])

    def test_ensure_node_tooling_ready_skips_prompt_when_user_path_already_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assess = Mock(
                return_value=SimpleNamespace(
                    issues=[],
                    persist_recommended=False,
                    user_path_updated=False,
                    user_path_contains_discovered=True,
                )
            )
            module = SimpleNamespace(assess_node_tooling=assess)

            with patch.object(launch_orbstudio, "_load_circuit_breaker_v2_module", return_value=module), patch.object(
                launch_orbstudio,
                "_prompt_yes_no",
            ) as prompt_mock:
                status = launch_orbstudio._ensure_node_tooling_ready(root)

        self.assertTrue(status.user_path_contains_discovered)
        self.assertEqual(assess.call_count, 1)
        prompt_mock.assert_not_called()

    def test_ensure_pixel_engine_bundle_retries_install_after_eperm_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pixel_root = root / "orbstudio_pixel_engine"
            src_root = pixel_root / "src"
            src_root.mkdir(parents=True, exist_ok=True)
            (pixel_root / "package.json").write_text("{}", encoding="utf-8")
            (pixel_root / "index.html").write_text("<html></html>", encoding="utf-8")
            (src_root / "main.ts").write_text("console.log('ok');", encoding="utf-8")

            command_results = iter(
                [
                    SimpleNamespace(returncode=1, stdout="", stderr="npm ERR! code EPERM"),
                    SimpleNamespace(returncode=0, stdout="", stderr=""),
                    SimpleNamespace(returncode=0, stdout="", stderr=""),
                ]
            )

            def fake_run_pixel_engine_command(command: list[str], cwd: Path) -> SimpleNamespace:
                result = next(command_results)
                if command[-1] == "install" and result.returncode != 0:
                    (cwd / "node_modules").mkdir(exist_ok=True)
                if command[-1] == "install" and result.returncode == 0:
                    (cwd / "node_modules").mkdir(exist_ok=True)
                if command[-2:] == ["run", "build"] and result.returncode == 0:
                    dist_root = cwd / "dist"
                    dist_root.mkdir(exist_ok=True)
                    (dist_root / "index.html").write_text("<html>built</html>", encoding="utf-8")
                return result

            with patch.object(launch_orbstudio, "_ensure_node_tooling_ready", return_value=None), patch.object(
                launch_orbstudio,
                "_resolve_npm_command",
                return_value="npm.cmd",
            ), patch.object(
                launch_orbstudio,
                "_run_pixel_engine_command",
                side_effect=fake_run_pixel_engine_command,
            ) as run_mock, patch.object(
                launch_orbstudio,
                "_prompt_yes_no",
                return_value=True,
            ), patch.object(launch_orbstudio, "rmtree") as rmtree_mock:
                ready = launch_orbstudio._ensure_pixel_engine_bundle(root)

        self.assertTrue(ready)
        self.assertEqual(run_mock.call_count, 3)
        rmtree_mock.assert_called_once_with(pixel_root / "node_modules")

    def test_iter_browser_candidates_prefers_known_chromium_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_root = Path(tmp)
            edge_path = local_root / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            edge_path.parent.mkdir(parents=True, exist_ok=True)
            edge_path.write_text("", encoding="utf-8")

            with patch.object(launch_orbstudio, "which", return_value=None), patch.object(
                launch_orbstudio,
                "_browser_search_roots",
                return_value=[local_root],
            ):
                candidates = launch_orbstudio._iter_browser_candidates()

        self.assertIn(edge_path, candidates)

    def test_open_popout_browser_uses_chromium_app_mode_when_available(self) -> None:
        browser_path = Path(r"C:/Program Files/Microsoft/Edge/Application/msedge.exe")
        with patch.object(launch_orbstudio, "_iter_browser_candidates", return_value=[browser_path]), patch.object(
            launch_orbstudio.subprocess,
            "Popen",
        ) as popen_mock, patch.object(launch_orbstudio.webbrowser, "open") as web_open_mock:
            opened = launch_orbstudio._open_popout_browser("http://127.0.0.1:8765")

        self.assertTrue(opened)
        popen_mock.assert_called_once()
        command = popen_mock.call_args.args[0]
        self.assertEqual(command[0], str(browser_path))
        app_arg = [arg for arg in command if arg.startswith("--app=")]
        self.assertEqual(len(app_arg), 1)
        self.assertTrue(app_arg[0].startswith("--app=http://127.0.0.1:8765"))
        self.assertIn("--new-window", command)
        web_open_mock.assert_not_called()

    def test_open_popout_browser_falls_back_to_webbrowser(self) -> None:
        with patch.object(launch_orbstudio, "_iter_browser_candidates", return_value=[]), patch.object(
            launch_orbstudio.webbrowser,
            "open",
            return_value=True,
        ) as web_open_mock:
            opened = launch_orbstudio._open_popout_browser("http://127.0.0.1:8765")

        self.assertTrue(opened)
        web_open_mock.assert_called_once_with("http://127.0.0.1:8765")

    def test_main_returns_error_when_port_does_not_release_on_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_ORBSTUDIO.py"
            launcher_path.write_text("", encoding="utf-8")
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")
            update_script = root / "update_game_ini.py"
            update_script.write_text("", encoding="utf-8")

            with patch.object(launch_orbstudio, "__file__", str(launcher_path)), patch.object(
                launch_orbstudio,
                "_healthcheck",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_url_available",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_wait_for_port_release",
                return_value=False,
            ) as wait_mock, patch.object(
                launch_orbstudio,
                "_terminate_server_on_port",
                return_value=True,
            ), patch.object(
                launch_orbstudio.subprocess,
                "Popen",
            ) as popen_mock, patch.object(launch_orbstudio.sys, "argv", ["LAUNCH_ORBSTUDIO.py", "--force-restart"]):
                result = launch_orbstudio.main()

        self.assertEqual(result, 1)
        wait_mock.assert_called_once_with("8765", probe_url="http://127.0.0.1:8765")
        popen_mock.assert_not_called()

    def test_main_defaults_to_pixel_engine_for_existing_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_ORBSTUDIO.py"
            launcher_path.write_text("", encoding="utf-8")
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")
            update_script = root / "update_game_ini.py"
            update_script.write_text("", encoding="utf-8")

            with patch.object(launch_orbstudio, "__file__", str(launcher_path)), patch.object(
                launch_orbstudio,
                "_healthcheck",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_ensure_pixel_engine_bundle",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_url_available",
                return_value=True,
            ), patch.object(launch_orbstudio, "_open_popout_browser", return_value=True) as open_mock:
                result = launch_orbstudio.main()

        self.assertEqual(result, 0)
        open_mock.assert_called_once_with("http://127.0.0.1:8765/pixel-engine")

    def test_main_opens_pixel_engine_route_without_forwarding_launcher_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_ORBSTUDIO.py"
            launcher_path.write_text("", encoding="utf-8")
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")
            update_script = root / "update_game_ini.py"
            update_script.write_text("", encoding="utf-8")

            with patch.object(launch_orbstudio, "__file__", str(launcher_path)), patch.object(
                launch_orbstudio,
                "_healthcheck",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_ensure_pixel_engine_bundle",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_url_available",
                return_value=True,
            ), patch.object(launch_orbstudio, "_open_popout_browser", return_value=True) as open_mock, patch.object(
                launch_orbstudio.sys,
                "argv",
                ["LAUNCH_ORBSTUDIO.py", "--pixel-engine"],
            ):
                result = launch_orbstudio.main()

        self.assertEqual(result, 0)
        open_mock.assert_called_once_with("http://127.0.0.1:8765/pixel-engine")

    def test_main_uses_teleprinter_route_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_ORBSTUDIO.py"
            launcher_path.write_text("", encoding="utf-8")
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")
            update_script = root / "update_game_ini.py"
            update_script.write_text("", encoding="utf-8")

            with patch.object(launch_orbstudio, "__file__", str(launcher_path)), patch.object(
                launch_orbstudio,
                "_healthcheck",
                return_value=True,
            ), patch.object(
                launch_orbstudio,
                "_url_available",
                return_value=True,
            ), patch.object(launch_orbstudio, "_open_popout_browser", return_value=True) as open_mock, patch.object(
                launch_orbstudio.sys,
                "argv",
                ["LAUNCH_ORBSTUDIO.py", "--teleprinter"],
            ):
                result = launch_orbstudio.main()

        self.assertEqual(result, 0)
        open_mock.assert_called_once_with("http://127.0.0.1:8765")

    def test_main_recycles_stale_server_when_pixel_engine_route_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_ORBSTUDIO.py"
            launcher_path.write_text("", encoding="utf-8")
            venv_python = root / ".venv" / "Scripts" / "python.exe"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")
            update_script = root / "update_game_ini.py"
            update_script.write_text("", encoding="utf-8")

            with patch.object(launch_orbstudio, "__file__", str(launcher_path)), patch.object(
                launch_orbstudio,
                "_ensure_pixel_engine_bundle",
                return_value=True,
            ), patch.object(launch_orbstudio, "__file__", str(launcher_path)), patch.object(
                launch_orbstudio,
                "_healthcheck",
                side_effect=[True, False, True],
            ), patch.object(
                launch_orbstudio,
                "_url_available",
                return_value=False,
            ), patch.object(
                launch_orbstudio,
                "_terminate_server_on_port",
                return_value=True,
            ) as terminate_mock, patch.object(
                launch_orbstudio,
                "_wait_for_port_release",
                return_value=True,
            ), patch.object(
                launch_orbstudio.subprocess,
                "Popen",
            ) as popen_mock, patch.object(
                launch_orbstudio,
                "_open_popout_browser",
                return_value=True,
            ) as open_mock:
                process = popen_mock.return_value
                process.poll.return_value = None
                result = launch_orbstudio.main()

        self.assertEqual(result, 0)
        terminate_mock.assert_called_once_with("8765")
        popen_mock.assert_called_once()
        open_mock.assert_called_once_with("http://127.0.0.1:8765/pixel-engine")


if __name__ == "__main__":
    unittest.main()