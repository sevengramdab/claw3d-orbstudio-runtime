from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


_MODULE_PATH = Path(__file__).resolve().parents[1] / "LAUNCH_CLAW3D.py"
_SPEC = importlib.util.spec_from_file_location("launch_claw3d", _MODULE_PATH)
assert _SPEC and _SPEC.loader
launch_claw3d = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launch_claw3d)


class LaunchClaw3DTests(unittest.TestCase):
    def test_resolve_managed_adapter_port_uses_fallback_when_hermes_default_is_busy(self) -> None:
        with patch.object(launch_claw3d, "_port_is_listening", side_effect=lambda port: port == "18789"):
            resolved = launch_claw3d._resolve_managed_adapter_port("hermes", {})

        self.assertEqual(resolved, "19444")

    def test_claw3d_launch_env_supports_each_backend(self) -> None:
        with patch.dict(os.environ, {"CLAW3D_GATEWAY_URL": "http://localhost:9000"}, clear=False):
            with patch.object(launch_claw3d, "_port_is_listening", return_value=False):
                hermes_env = launch_claw3d._claw3d_launch_env(["--backend", "hermes"])
            demo_env = launch_claw3d._claw3d_launch_env(["--backend", "demo"])
            custom_env = launch_claw3d._claw3d_launch_env(["--backend", "custom"])
            openclaw_env = launch_claw3d._claw3d_launch_env(["--backend", "openclaw"])

        assert hermes_env is not None
        assert demo_env is not None
        assert custom_env is not None
        assert openclaw_env is not None

        self.assertEqual(hermes_env["CLAW3D_GATEWAY_ADAPTER_TYPE"], "hermes")
        self.assertEqual(hermes_env["HERMES_ADAPTER_PORT"], "18789")
        self.assertEqual(hermes_env["CLAW3D_GATEWAY_URL"], "ws://localhost:18789")
        self.assertEqual(hermes_env["CLAW3D_GATEWAY_TOKEN"], "")

        self.assertEqual(demo_env["CLAW3D_GATEWAY_ADAPTER_TYPE"], "demo")
        self.assertEqual(demo_env["DEMO_ADAPTER_PORT"], "18890")
        self.assertEqual(demo_env["CLAW3D_GATEWAY_URL"], "ws://localhost:18890")
        self.assertEqual(demo_env["CLAW3D_GATEWAY_TOKEN"], "")

        self.assertEqual(custom_env["CLAW3D_GATEWAY_ADAPTER_TYPE"], "custom")
        self.assertEqual(custom_env["CLAW3D_GATEWAY_URL"], "http://localhost:9000")

        self.assertEqual(openclaw_env["CLAW3D_GATEWAY_ADAPTER_TYPE"], "openclaw")
        self.assertEqual(openclaw_env["CLAW3D_GATEWAY_URL"], "")
        self.assertEqual(openclaw_env["CLAW3D_GATEWAY_TOKEN"], "")

    def test_claw3d_ready_url_targets_studio_api(self) -> None:
        self.assertEqual(
            launch_claw3d._claw3d_ready_url("http://127.0.0.1:3000"),
            "http://127.0.0.1:3000/api/studio",
        )

    def test_lm_studio_models_url_targets_models_api(self) -> None:
        self.assertEqual(
            launch_claw3d._lm_studio_models_url("http://127.0.0.1:1234"),
            "http://127.0.0.1:1234/v1/models",
        )

    def test_claw3d_creation_flags_default_to_current_console(self) -> None:
        self.assertEqual(launch_claw3d._claw3d_creation_flags([]), 0)

    def test_claw3d_creation_flags_support_new_console_flag(self) -> None:
        expected = getattr(launch_claw3d.subprocess, "CREATE_NEW_CONSOLE", 0)
        self.assertEqual(launch_claw3d._claw3d_creation_flags(["--new-console"]), expected)

    def test_claw3d_active_backend_reads_studio_settings(self) -> None:
        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"settings":{"gateway":{"adapterType":"hermes"}}}'

        with patch.object(launch_claw3d.urllib.request, "urlopen", return_value=_Response()):
            self.assertEqual(launch_claw3d._claw3d_active_backend("http://127.0.0.1:3000"), "hermes")

    def test_inspect_signal_integrity_reports_model_and_routing_details(self) -> None:
        import io

        class _LmStudioResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def info(self):
                return {"Access-Control-Allow-Origin": "*"}

            def read(self) -> bytes:
                return b'{"data":[{"id":"model-a"},{"id":"model-b"}]}'

        class _StudioResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"settings":{"gateway":{"url":"ws://localhost:18789","adapterType":"hermes"}}}'

        captured = io.StringIO()
        with patch.object(
            launch_claw3d.urllib.request,
            "urlopen",
            side_effect=[_LmStudioResponse(), _StudioResponse()],
        ), patch("sys.stdout", captured):
            result = launch_claw3d.inspect_signal_integrity("http://127.0.0.1:3000")

        self.assertEqual(result, 0)
        output = captured.getvalue()
        self.assertIn("SIGNAL INTEGRITY INSPECTION", output)
        self.assertIn("CORS Shielding: *", output)
        self.assertIn("Available Blocks in Model Space: 2 loaded.", output)
        self.assertIn("Targeting ws://localhost:18789 via hermes adapter.", output)

    def test_inspect_signal_integrity_reports_faults_and_nonzero_status(self) -> None:
        import io

        captured = io.StringIO()
        with patch.object(
            launch_claw3d.urllib.request,
            "urlopen",
            side_effect=[OSError("lm-studio down"), OSError("studio down")],
        ), patch("sys.stdout", captured):
            result = launch_claw3d.inspect_signal_integrity("http://127.0.0.1:3000")

        self.assertEqual(result, 1)
        output = captured.getvalue()
        self.assertIn("[FAULT] Logic Path Interrupted: lm-studio down", output)
        self.assertIn("[FAULT] Studio Control Panel Unreachable: studio down", output)

    def test_main_runs_signal_integrity_mode_without_launching_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_CLAW3D.py"
            launcher_path.write_text("", encoding="utf-8")
            (root / "Claw3D-main").mkdir(parents=True, exist_ok=True)

            with patch.object(launch_claw3d, "__file__", str(launcher_path)), patch.object(
                launch_claw3d,
                "inspect_signal_integrity",
                return_value=0,
            ) as inspect_mock, patch.object(
                launch_claw3d,
                "_ensure_claw3d_dependencies",
            ) as ensure_mock, patch.object(
                launch_claw3d.subprocess,
                "Popen",
            ) as popen_mock, patch.object(
                launch_claw3d.sys,
                "argv",
                [
                    "LAUNCH_CLAW3D.py",
                    "--inspect-signal-integrity",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "3010",
                    "--lm-studio-url",
                    "http://127.0.0.1:2233",
                ],
            ):
                result = launch_claw3d.main()

        self.assertEqual(result, 0)
        inspect_mock.assert_called_once_with("http://0.0.0.0:3010", "http://127.0.0.1:2233")
        ensure_mock.assert_not_called()
        popen_mock.assert_not_called()

    def test_claw3d_dependencies_ready_requires_next_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claw_root = Path(tmp)
            (claw_root / "node_modules").mkdir(parents=True, exist_ok=True)

            self.assertFalse(launch_claw3d._claw3d_dependencies_ready(claw_root))

            next_root = claw_root / "node_modules" / "next"
            next_root.mkdir(parents=True, exist_ok=True)
            (next_root / "package.json").write_text("{}", encoding="utf-8")

            self.assertTrue(launch_claw3d._claw3d_dependencies_ready(claw_root))

    def test_ensure_claw3d_dependencies_installs_when_node_modules_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claw_root = root / "Claw3D-main"
            claw_root.mkdir(parents=True, exist_ok=True)
            (claw_root / "package.json").write_text("{}", encoding="utf-8")

            def fake_run(command: list[str], cwd: Path) -> SimpleNamespace:
                if command[-1] == "install":
                    (cwd / "node_modules").mkdir(exist_ok=True)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(launch_claw3d.orbstudio_launcher, "_ensure_node_tooling_ready", return_value=None), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_resolve_npm_command",
                return_value="npm.cmd",
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_run_pixel_engine_command",
                side_effect=fake_run,
            ):
                ready = launch_claw3d._ensure_claw3d_dependencies(root)

        self.assertTrue(ready)

    def test_ensure_claw3d_dependencies_installs_when_next_package_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claw_root = root / "Claw3D-main"
            (claw_root / "node_modules").mkdir(parents=True, exist_ok=True)
            (claw_root / "package.json").write_text("{}", encoding="utf-8")

            def fake_run(command: list[str], cwd: Path) -> SimpleNamespace:
                if command[-1] == "install":
                    next_root = cwd / "node_modules" / "next"
                    next_root.mkdir(parents=True, exist_ok=True)
                    (next_root / "package.json").write_text("{}", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(launch_claw3d.orbstudio_launcher, "_ensure_node_tooling_ready", return_value=None), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_resolve_npm_command",
                return_value="npm.cmd",
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_run_pixel_engine_command",
                side_effect=fake_run,
            ):
                ready = launch_claw3d._ensure_claw3d_dependencies(root)

        self.assertTrue(ready)

    def test_main_opens_existing_server_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_CLAW3D.py"
            launcher_path.write_text("", encoding="utf-8")
            (root / "Claw3D-main").mkdir(parents=True, exist_ok=True)

            with patch.object(launch_claw3d, "__file__", str(launcher_path)), patch.object(
                launch_claw3d,
                "_ensure_claw3d_dependencies",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_url_available",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_open_popout_browser",
                return_value=True,
            ) as open_mock:
                result = launch_claw3d.main()

        self.assertEqual(result, 0)
        open_mock.assert_called_once_with("http://127.0.0.1:3000")

    def test_main_launches_dev_server_after_dependency_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_CLAW3D.py"
            launcher_path.write_text("", encoding="utf-8")
            claw_root = root / "Claw3D-main"
            claw_root.mkdir(parents=True, exist_ok=True)

            with patch.object(launch_claw3d, "__file__", str(launcher_path)), patch.object(
                launch_claw3d,
                "_ensure_claw3d_dependencies",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_url_available",
                side_effect=[False, True],
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_resolve_npm_command",
                return_value="npm.cmd",
            ), patch.object(
                launch_claw3d,
                "_port_is_listening",
                return_value=False,
            ), patch.object(launch_claw3d.subprocess, "Popen") as popen_mock, patch.object(
                launch_claw3d.orbstudio_launcher,
                "_open_popout_browser",
                return_value=True,
            ) as open_mock:
                process = popen_mock.return_value
                process.poll.return_value = None
                result = launch_claw3d.main()

        self.assertEqual(result, 0)
        popen_mock.assert_called_once_with(
            ["npm.cmd", "run", "dev"],
            cwd=claw_root,
            creationflags=0,
            env=None,
        )
        open_mock.assert_called_once_with("http://127.0.0.1:3000")

    def test_main_launches_dev_server_in_new_console_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_CLAW3D.py"
            launcher_path.write_text("", encoding="utf-8")
            claw_root = root / "Claw3D-main"
            claw_root.mkdir(parents=True, exist_ok=True)

            with patch.object(launch_claw3d, "__file__", str(launcher_path)), patch.object(
                launch_claw3d,
                "_ensure_claw3d_dependencies",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_url_available",
                side_effect=[False, True],
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_resolve_npm_command",
                return_value="npm.cmd",
            ), patch.object(
                launch_claw3d,
                "_port_is_listening",
                return_value=False,
            ), patch.object(launch_claw3d.subprocess, "Popen") as popen_mock, patch.object(
                launch_claw3d.orbstudio_launcher,
                "_open_popout_browser",
                return_value=True,
            ) as open_mock, patch.object(
                launch_claw3d.sys,
                "argv",
                ["LAUNCH_CLAW3D.py", "--new-console"],
            ):
                process = popen_mock.return_value
                process.poll.return_value = None
                result = launch_claw3d.main()

        self.assertEqual(result, 0)
        popen_mock.assert_called_once_with(
            ["npm.cmd", "run", "dev"],
            cwd=claw_root,
            creationflags=getattr(launch_claw3d.subprocess, "CREATE_NEW_CONSOLE", 0),
            env=None,
        )
        open_mock.assert_called_once_with("http://127.0.0.1:3000")

    def test_main_restarts_when_requested_backend_differs_from_active_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_CLAW3D.py"
            launcher_path.write_text("", encoding="utf-8")
            claw_root = root / "Claw3D-main"
            claw_root.mkdir(parents=True, exist_ok=True)

            with patch.object(launch_claw3d, "__file__", str(launcher_path)), patch.object(
                launch_claw3d,
                "_ensure_claw3d_dependencies",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_url_available",
                side_effect=[True, True],
            ), patch.object(
                launch_claw3d,
                "_claw3d_active_backend",
                return_value="custom",
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_terminate_server_on_port",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_wait_for_port_release",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_resolve_npm_command",
                return_value="npm.cmd",
            ), patch.object(launch_claw3d.subprocess, "Popen") as popen_mock, patch.object(
                launch_claw3d.orbstudio_launcher,
                "_open_popout_browser",
                return_value=True,
            ), patch.object(
                launch_claw3d,
                "_port_is_listening",
                return_value=False,
            ), patch.object(
                launch_claw3d,
                "_probe_hermes_adapter_http",
                return_value=True,
            ), patch.object(launch_claw3d.sys, "argv", ["LAUNCH_CLAW3D.py", "--backend", "hermes"]):
                process = popen_mock.return_value
                process.poll.return_value = None
                result = launch_claw3d.main()

        self.assertEqual(result, 0)
        launched_env = popen_mock.call_args.kwargs.get("env")
        assert launched_env is not None
        self.assertEqual(launched_env["CLAW3D_GATEWAY_ADAPTER_TYPE"], "hermes")
        self.assertEqual(launched_env["HERMES_ADAPTER_PORT"], "18789")
        self.assertEqual(launched_env["CLAW3D_GATEWAY_URL"], f"ws://localhost:{launched_env['HERMES_ADAPTER_PORT']}")
        self.assertEqual(launched_env["CLAW3D_GATEWAY_TOKEN"], "")

    def test_main_resets_adapter_before_force_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_CLAW3D.py"
            launcher_path.write_text("", encoding="utf-8")
            (root / "Claw3D-main").mkdir(parents=True, exist_ok=True)

            class _Response:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            with patch.object(launch_claw3d, "__file__", str(launcher_path)), patch.object(
                launch_claw3d,
                "_ensure_claw3d_dependencies",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_url_available",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_terminate_server_on_port",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_wait_for_port_release",
                return_value=False,
            ), patch.object(
                launch_claw3d.urllib.request,
                "urlopen",
                return_value=_Response(),
            ) as urlopen_mock, patch.object(
                launch_claw3d.subprocess,
                "Popen",
            ) as popen_mock, patch.object(launch_claw3d.sys, "argv", ["LAUNCH_CLAW3D.py", "--force-restart"]):
                result = launch_claw3d.main()

        self.assertEqual(result, 1)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:3000/api/studio/reset-adapter")
        self.assertEqual(request.get_method(), "POST")
        popen_mock.assert_not_called()

    def test_main_returns_error_when_force_restart_cannot_release_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher_path = root / "LAUNCH_CLAW3D.py"
            launcher_path.write_text("", encoding="utf-8")
            (root / "Claw3D-main").mkdir(parents=True, exist_ok=True)

            with patch.object(launch_claw3d, "__file__", str(launcher_path)), patch.object(
                launch_claw3d,
                "_ensure_claw3d_dependencies",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_url_available",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_terminate_server_on_port",
                return_value=True,
            ), patch.object(
                launch_claw3d.orbstudio_launcher,
                "_wait_for_port_release",
                return_value=False,
            ) as wait_mock, patch.object(
                launch_claw3d.subprocess,
                "Popen",
            ) as popen_mock, patch.object(launch_claw3d.sys, "argv", ["LAUNCH_CLAW3D.py", "--force-restart"]):
                result = launch_claw3d.main()

        self.assertEqual(result, 1)
        wait_mock.assert_called_once_with("3000", probe_url="http://127.0.0.1:3000/api/studio")
        popen_mock.assert_not_called()

    # ------------------------------------------------------------------
    # Hermes adapter HTTP health probe
    # ------------------------------------------------------------------

    def test_probe_hermes_adapter_http_passes_on_expected_body(self) -> None:
        class _Resp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self) -> bytes:
                return b"Hermes Gateway Adapter \xe2\x80\x93 OK\n"

        with patch.object(launch_claw3d.urllib.request, "urlopen", return_value=_Resp()):
            self.assertTrue(launch_claw3d._probe_hermes_adapter_http("18789"))

    def test_probe_hermes_adapter_http_fails_on_wrong_body(self) -> None:
        class _Resp:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self) -> bytes:
                return b"Not the adapter"

        with patch.object(launch_claw3d.urllib.request, "urlopen", return_value=_Resp()):
            self.assertFalse(launch_claw3d._probe_hermes_adapter_http("18789"))

    def test_probe_hermes_adapter_http_fails_on_connection_error(self) -> None:
        with patch.object(launch_claw3d.urllib.request, "urlopen", side_effect=OSError("refused")):
            self.assertFalse(launch_claw3d._probe_hermes_adapter_http("18789"))

    # ------------------------------------------------------------------
    # .env.local conflict detection
    # ------------------------------------------------------------------

    def test_warn_env_local_conflict_prints_warning_on_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claw_root = Path(tmp)
            env_local = claw_root / ".env.local"
            env_local.write_text("CLAW3D_GATEWAY_ADAPTER_TYPE=custom\n", encoding="utf-8")

            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                launch_claw3d._warn_env_local_conflict(claw_root, "hermes")

            self.assertIn("WARNING", captured.getvalue())
            self.assertIn("custom", captured.getvalue())
            self.assertIn("hermes", captured.getvalue())

    def test_warn_env_local_conflict_silent_on_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claw_root = Path(tmp)
            env_local = claw_root / ".env.local"
            env_local.write_text("CLAW3D_GATEWAY_ADAPTER_TYPE=hermes\n", encoding="utf-8")

            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                launch_claw3d._warn_env_local_conflict(claw_root, "hermes")

            self.assertEqual(captured.getvalue(), "")

    def test_warn_env_local_conflict_silent_when_no_backend_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claw_root = Path(tmp)
            env_local = claw_root / ".env.local"
            env_local.write_text("CLAW3D_GATEWAY_ADAPTER_TYPE=custom\n", encoding="utf-8")

            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                launch_claw3d._warn_env_local_conflict(claw_root, None)

            self.assertEqual(captured.getvalue(), "")

    # ------------------------------------------------------------------
    # _claw3d_active_backend error logging
    # ------------------------------------------------------------------

    def test_claw3d_active_backend_logs_errors_instead_of_silent_none(self) -> None:
        import io
        captured = io.StringIO()
        with patch.object(launch_claw3d.urllib.request, "urlopen", side_effect=OSError("refused")), \
             patch("sys.stdout", captured):
            result = launch_claw3d._claw3d_active_backend("http://127.0.0.1:3000")

        self.assertIsNone(result)
        self.assertIn("Could not probe active backend", captured.getvalue())


if __name__ == "__main__":
    unittest.main()