from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mihomo_instance as mi


def run_main(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = mi.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class PathTests(unittest.TestCase):
    def test_default_home_is_config_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text("mixed-port: 1\n", encoding="utf-8")
            self.assertEqual(mi.resolve_home(None, config), config.parent)

    def test_default_pid_and_log_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(mi.resolve_pid_file(None, home), home / "mihomo.pid")
            self.assertEqual(mi.resolve_log(None, home), home / "mihomo.log")

    def test_pid_file_arg_requires_pid_or_home(self) -> None:
        with self.assertRaises(mi.InstanceError):
            mi.resolve_pid_file_arg(None, None)


class PidFileTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mihomo.pid"
            data = {"pid": 123, "config": "config.yaml", "home": tmp}
            mi.write_pid_file(path, data)
            self.assertEqual(mi.read_pid_file(path), data)

    def test_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(mi.read_pid_file(Path(tmp) / "mihomo.pid"))

    def test_invalid_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mihomo.pid"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(mi.InstanceError):
                mi.read_pid_file(path)

    def test_missing_pid_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mihomo.pid"
            path.write_text(json.dumps({"config": "x"}), encoding="utf-8")
            with self.assertRaises(mi.InstanceError):
                mi.read_pid_file(path)


class ControllerTests(unittest.TestCase):
    def test_read_controller_strips_quotes_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(
                "mixed-port: 19001\n"
                "external-controller: 127.0.0.1:19097 # api\n"
                "secret: '1'\n",
                encoding="utf-8",
            )
            self.assertEqual(mi.read_controller(config), ("127.0.0.1:19097", "1"))

    def test_read_controller_ignores_pipe_and_nested_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(
                "external-controller-pipe: \\\\.\\pipe\\verge-mihomo\n"
                "proxy-providers:\n"
                "  nested:\n"
                "    secret: nested\n",
                encoding="utf-8",
            )
            self.assertEqual(mi.read_controller(config), (None, None))

    def test_verify_config_marks_empty_providers_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(
                "external-controller: 127.0.0.1:19097\nsecret: '1'\n",
                encoding="utf-8",
            )

            def fake_request(base: str, path: str, headers: dict, timeout: float):
                if path == "/version":
                    return 200, {"version": "v1.19.33"}
                return 200, {
                    "providers": {
                        "online": {"proxies": []},
                        "other": {"proxies": [{"name": "a"}]},
                    }
                }

            with mock.patch.object(mi, "request_json", side_effect=fake_request):
                ok, messages = mi.verify_config(config)
            self.assertFalse(ok)
            self.assertIn("空 provider: online", messages)
            self.assertIn("存在空 provider", " ".join(messages))

    def test_verify_config_accepts_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(
                "external-controller: 127.0.0.1:19097\nsecret: '1'\n",
                encoding="utf-8",
            )

            def fake_request(base: str, path: str, headers: dict, timeout: float):
                if path == "/version":
                    return 200, {"version": "v1.19.33"}
                return 200, {"providers": {"online": {"proxies": [{"name": "a"}]}}}

            with mock.patch.object(mi, "request_json", side_effect=fake_request):
                ok, messages = mi.verify_config(config)
            self.assertTrue(ok)
            self.assertIn("节点 1 个", " ".join(messages))

    def test_verify_config_reports_api_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text(
                "external-controller: 127.0.0.1:19097\nsecret: '1'\n",
                encoding="utf-8",
            )
            with mock.patch.object(mi, "request_json", side_effect=mi.ApiError("boom")):
                ok, messages = mi.verify_config(config)
            self.assertFalse(ok)
            self.assertIn("API 验证失败: boom", messages)


class CommandTests(unittest.TestCase):
    def test_instance_command(self) -> None:
        home = Path(tempfile.gettempdir()) / "home"
        config = Path(tempfile.gettempdir()) / "config.yaml"
        command = mi.instance_command("mihomo", home, config)
        self.assertEqual(
            command,
            ["mihomo", "-d", str(home), "-f", str(config)],
        )

    def test_command_matches(self) -> None:
        home = Path(tempfile.gettempdir()) / "home"
        config = Path(tempfile.gettempdir()) / "config.yaml"
        cmdline = f"mihomo -d {home} -f {config}"
        self.assertTrue(mi.command_matches(cmdline, config, home))
        self.assertFalse(
            mi.command_matches(cmdline, Path(tempfile.gettempdir()) / "other.yaml", home)
        )

    def test_verify_flags_parse(self) -> None:
        parser = mi.build_parser()
        start = parser.parse_args(["start", "--config", "x", "--home", "y", "--verify"])
        status = parser.parse_args(["status", "--home", "y", "--verify"])
        self.assertTrue(start.verify)
        self.assertTrue(status.verify)


class CliTests(unittest.TestCase):
    def test_status_without_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, _ = run_main(["status", "--home", tmp])
            self.assertEqual(code, mi.EXIT_STATE)
            self.assertIn("没有 PID 文件", stdout)

    def test_stop_without_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, _ = run_main(["stop", "--home", tmp])
            self.assertEqual(code, mi.EXIT_OK)
            self.assertIn("没有 PID 文件", stdout)

    def test_start_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text("mixed-port: 1\n", encoding="utf-8")
            code, stdout, _ = run_main(
                [
                    "start",
                    "--config",
                    str(config),
                    "--home",
                    tmp,
                    "--mihomo",
                    sys.executable,
                    "--dry-run",
                ]
            )
            self.assertEqual(code, mi.EXIT_OK)
            self.assertIn("-d", stdout)
            self.assertIn(str(config), stdout)

    def test_list_empty_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, _ = run_main(["list", "--root", tmp])
            self.assertEqual(code, mi.EXIT_STATE)
            self.assertIn("没有实例", stdout)

    def test_list_missing_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, _ = run_main(["list", "--root", str(Path(tmp) / "missing")])
            self.assertEqual(code, mi.EXIT_STATE)
            self.assertIn("没有实例", stdout)

    def test_list_running_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            instance = Path(tmp) / "robin"
            instance.mkdir()
            mi.write_pid_file(
                instance / "mihomo.pid",
                {"pid": os.getpid(), "home": str(instance), "config": "config.yaml"},
            )
            code, stdout, _ = run_main(["list", "--root", tmp])
            self.assertEqual(code, mi.EXIT_OK)
            self.assertIn("robin", stdout)
            self.assertIn("运行中", stdout)


if __name__ == "__main__":
    unittest.main()
