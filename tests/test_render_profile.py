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

import render_profile as rp


def run_main(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = rp.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def make_temp_manifest(tmp: str) -> Path:
    source = Path(__file__).resolve().parents[1] / "templates" / "spider_lb.profiles.json"
    manifest = json.loads(source.read_text(encoding="utf-8"))
    manifest["outputDir"] = tmp
    path = Path(tmp) / "private.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


class StateTests(unittest.TestCase):
    def test_missing(self) -> None:
        self.assertEqual(rp.state_of(None, "body"), "missing")

    def test_uptodate(self) -> None:
        body = "a\n"
        existing = {"revision": "x", "fingerprint": rp.sha256_hex(body), "body": body}
        self.assertEqual(rp.state_of(existing, body), "uptodate")

    def test_stale_when_old_body_matches_fingerprint(self) -> None:
        old = "old\n"
        existing = {"revision": "x", "fingerprint": rp.sha256_hex(old), "body": old}
        self.assertEqual(rp.state_of(existing, "new\n"), "stale")

    def test_modified_when_body_changed_by_hand(self) -> None:
        body = "old\n"
        existing = {"revision": "x", "fingerprint": rp.sha256_hex(body), "body": body + "hack\n"}
        self.assertEqual(rp.state_of(existing, "new\n"), "modified")

    def test_foreign_without_fingerprint(self) -> None:
        existing = {"revision": "", "fingerprint": "", "body": "x\n"}
        self.assertEqual(rp.state_of(existing, "y\n"), "foreign")


class NamingTests(unittest.TestCase):
    def test_short_name(self) -> None:
        self.assertEqual(rp.short_name("default.generated.yaml"), "default")
        self.assertEqual(rp.short_name("probe.yaml"), "probe")
        self.assertEqual(rp.short_name("a.b.yaml"), "a.b")

    def test_normalize_output_name(self) -> None:
        self.assertEqual(rp.normalize_output_name("crawler"), "crawler.generated.yaml")
        self.assertEqual(rp.normalize_output_name("probe.yaml"), "probe.yaml")
        with self.assertRaises(rp.ProfileError):
            rp.normalize_output_name("bad/name")

    def test_profile_keys_rejects_short_name_collision(self) -> None:
        entries = [
            {"name": "x.generated.yaml"},
            {"name": "x.yaml"},
        ]
        with self.assertRaises(rp.ProfileError):
            rp.profile_keys(entries)

    def test_profile_keys_rejects_duplicate_full_name(self) -> None:
        entries = [{"name": "x.generated.yaml"}, {"name": "x.generated.yaml"}]
        with self.assertRaises(rp.ProfileError):
            rp.profile_keys(entries)


class OutputDirTests(unittest.TestCase):
    def test_default_uses_desktop_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "Desktop").mkdir()
            expected = home / "Desktop" / "mihomo-profiles"
            self.assertEqual(
                rp.resolve_output_dir("", home / "repo" / "templates", home).resolve(),
                expected.resolve(),
            )

    def test_default_falls_back_to_home_without_desktop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            expected = home / "mihomo-profiles"
            self.assertEqual(
                rp.resolve_output_dir("", home / "repo" / "templates", home).resolve(),
                expected.resolve(),
            )

    def test_expands_tilde(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            expected = home / "custom" / "profiles"
            self.assertEqual(
                rp.resolve_output_dir("~/custom/profiles", home / "templates", home).resolve(),
                expected.resolve(),
            )

    def test_relative_path_stays_under_template_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            template_dir = home / "repo" / "templates"
            expected = home / "repo" / "profiles"
            self.assertEqual(
                rp.resolve_output_dir("../profiles", template_dir, home).resolve(),
                expected.resolve(),
            )

    def test_absolute_path_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = home / "absolute"
            self.assertEqual(
                rp.resolve_output_dir(os.fspath(target), home / "templates", home).resolve(),
                target.resolve(),
            )

    def test_path_is_inside(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertTrue(rp.path_is_inside(root / "repo" / "profiles", root / "repo"))
            self.assertFalse(rp.path_is_inside(root / "repo", root / "repo" / "profiles"))


class MihomoFinderTests(unittest.TestCase):
    def test_explicit_path_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "my-mihomo"
            fake.write_text("", encoding="utf-8")
            self.assertEqual(rp.find_mihomo(str(fake)), str(fake.resolve()))

    def test_env_path_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "my-mihomo"
            fake.write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {"MIHOMO_BIN": str(fake)}):
                self.assertEqual(rp.find_mihomo(None), str(fake.resolve()))

    def test_missing_explicit_path_raises(self) -> None:
        with self.assertRaises(OSError):
            rp.find_mihomo("/no/such/mihomo")

    def test_path_falls_back_to_verge_mihomo(self) -> None:
        def which(name: str) -> str | None:
            return "/fake/verge-mihomo" if name == "verge-mihomo" else None

        with mock.patch("render_profile.shutil.which", side_effect=which):
            self.assertEqual(rp.find_mihomo(None), "/fake/verge-mihomo")


class ManifestTests(unittest.TestCase):
    def test_explicit_manifest_wins_over_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_dir = root / "templates"
            template_dir.mkdir()
            (template_dir / "spider_lb.profiles.json").write_text("{}", encoding="utf-8")
            (template_dir / "spider_lb.profiles.local.json").write_text("{}", encoding="utf-8")
            explicit = root / "private.json"
            explicit.write_text("{}", encoding="utf-8")
            self.assertEqual(
                rp.resolve_manifest_path(os.fspath(explicit), template_dir).resolve(),
                explicit.resolve(),
            )

    def test_local_manifest_is_preferred_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            template_dir = Path(tmp) / "templates"
            template_dir.mkdir()
            (template_dir / "spider_lb.profiles.json").write_text("{}", encoding="utf-8")
            local = template_dir / "spider_lb.profiles.local.json"
            local.write_text("{}", encoding="utf-8")
            self.assertEqual(
                rp.resolve_manifest_path("", template_dir).resolve(),
                local.resolve(),
            )

    def test_base_manifest_is_used_when_local_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            template_dir = Path(tmp) / "templates"
            template_dir.mkdir()
            base = template_dir / "spider_lb.profiles.json"
            base.write_text("{}", encoding="utf-8")
            self.assertEqual(
                rp.resolve_manifest_path("", template_dir).resolve(),
                base.resolve(),
            )

    def test_relative_manifest_uses_given_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = root / "work"
            cwd.mkdir()
            self.assertEqual(
                rp.resolve_manifest_path("private.json", root / "templates", cwd).resolve(),
                (cwd / "private.json").resolve(),
            )

    def test_load_manifest_reads_given_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.json"
            path.write_text('{"profiles": []}', encoding="utf-8")
            self.assertEqual(rp.load_manifest(path), {"profiles": []})

    def test_load_manifest_rejects_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(rp.ManifestError):
            rp.load_manifest(Path(tmp) / "missing.json")

    def test_main_uses_explicit_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_temp_manifest(tmp)
            code, stdout, stderr = run_main(["--manifest", os.fspath(path), "--dry-run"])
            self.assertEqual(code, 0)
            self.assertIn(f"[清单] {path}", stderr)
            self.assertIn(f"[输出目录] {Path(tmp)}", stdout)


class CheckTests(unittest.TestCase):
    def test_check_missing_fails_without_allow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_temp_manifest(tmp)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            code, stdout, _ = run_main(["--manifest", os.fspath(path), "--check"])
            self.assertEqual(code, rp.EXIT_STATE)
            self.assertIn("[未生成] default.generated.yaml", stdout)
            self.assertIn("[未生成] spider_lb_sticky.generated.yaml", stdout)
            self.assertIn(f"{len(manifest['profiles'])} 份未生成", stdout)

    def test_check_missing_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_temp_manifest(tmp)
            code, stdout, _ = run_main(
                ["--manifest", os.fspath(path), "--check", "--allow-missing"]
            )
            self.assertEqual(code, rp.EXIT_OK)
            self.assertIn("--allow-missing 已忽略", stdout)

    def test_check_does_not_create_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_temp_manifest(tmp)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            output_dir = Path(tmp) / "new" / "out"
            manifest["outputDir"] = os.fspath(output_dir)
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            code, _, _ = run_main(["--manifest", os.fspath(path), "--check"])
            self.assertEqual(code, rp.EXIT_STATE)
            self.assertFalse(output_dir.exists())

    def test_check_drift_still_fails_with_allow_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_temp_manifest(tmp)
            code, _, _ = run_main(["--manifest", os.fspath(path)])
            self.assertEqual(code, rp.EXIT_OK)

            target = Path(tmp) / "default.generated.yaml"
            target.write_text(
                target.read_text(encoding="utf-8") + "# 手改\n", encoding="utf-8"
            )
            code, stdout, _ = run_main(
                ["--manifest", os.fspath(path), "--check", "--allow-missing"]
            )
            self.assertEqual(code, rp.EXIT_STATE)
            self.assertIn("[需覆盖] default.generated.yaml", stdout)
            self.assertIn("1 份需要重新渲染", stdout)

    def test_allow_missing_requires_check(self) -> None:
        code, _, stderr = run_main(["--allow-missing"])
        self.assertEqual(code, rp.EXIT_USAGE)
        self.assertIn("只能与 --check", stderr)


class TemplateTests(unittest.TestCase):
    def test_port_keys_ignore_comments(self) -> None:
        template = (
            "mixed-port: 7897\n"
            "port: {{PORT_ALL}}\n"
            "# 这一行不算: {{PORT_IGNORED}}\n"
            "socks-port: {{PORT_SOCKS}}\n"
        )
        self.assertEqual(rp.template_port_keys(template), ["all", "socks"])

    def test_reserved_ports(self) -> None:
        template = (
            "mixed-port: 7897\n"
            "external-controller: 127.0.0.1:9097\n"
            "port: 7898\n"
        )
        self.assertEqual(rp.template_reserved_ports(template), [7897, 7898, 9097])

    def test_new_profile_text_uses_template_name(self) -> None:
        text = rp.new_profile_text(
            "20260101.12:00",
            "demo",
            "f" * 64,
            "body\n",
            "other.template.yaml",
        )
        self.assertIn("other.template.yaml", text)
        self.assertNotIn("spider_lb.template.yaml", text)
        self.assertIn("生成指纹:sha256:" + "f" * 64, text)


class PortTests(unittest.TestCase):
    def test_linked_mode(self) -> None:
        entry = {
            "portAll": 17100,
            "portEu": 17110,
            "countryOrder": ["us", "jp"],
        }
        ports = rp.resolve_ports(entry, "p", ["all", "eu", "us", "jp"], [])
        self.assertEqual(
            ports,
            {"all": 17100, "eu": 17110, "us": 17111, "jp": 17112},
        )

    def test_default_country_order(self) -> None:
        entry = {"portAll": 17100, "portEu": 17110}
        keys = ["all", "eu"] + [code.lower() for code in rp.DEFAULT_COUNTRY_ORDER]
        ports = rp.resolve_ports(entry, "p", keys, [])
        self.assertEqual(ports["us"], 17111)
        self.assertEqual(ports["uk"], 17120)

    def test_explicit_mode(self) -> None:
        entry = {"ports": {"all": 17100, "eu": 17110}}
        self.assertEqual(
            rp.resolve_ports(entry, "p", ["all", "eu"], []),
            {"all": 17100, "eu": 17110},
        )

    def test_explicit_and_linked_conflict(self) -> None:
        entry = {"ports": {"all": 17100}, "portAll": 17100}
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports(entry, "p", ["all"], [])

    def test_missing_port(self) -> None:
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports({"portAll": 17100}, "p", ["all", "eu"], [])

    def test_unused_port(self) -> None:
        entry = {"ports": {"all": 17100, "eu": 17110}}
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports(entry, "p", ["all"], [])

    def test_duplicate_port(self) -> None:
        entry = {"ports": {"all": 17100, "eu": 17100}}
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports(entry, "p", ["all", "eu"], [])

    def test_out_of_range(self) -> None:
        entry = {"ports": {"all": 80}}
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports(entry, "p", ["all"], [])

    def test_reserved_port(self) -> None:
        entry = {"ports": {"all": 9097}}
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports(entry, "p", ["all"], [9097])

    def test_common_port_rejected_then_allowed(self) -> None:
        entry: dict[str, object] = {"ports": {"all": 7890}}
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports(entry, "p", ["all"], [])
        entry["allowCommonPorts"] = True
        self.assertEqual(rp.resolve_ports(entry, "p", ["all"], []), {"all": 7890})

    def test_deprecated_port_uk(self) -> None:
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports({"portUk": 17120}, "p", [], [])

    def test_duplicate_country_order(self) -> None:
        entry = {"portAll": 17100, "portEu": 17110, "countryOrder": ["us", "us"]}
        with self.assertRaises(rp.ProfileError):
            rp.resolve_ports(entry, "p", ["all", "eu", "us"], [])


class ManagementTests(unittest.TestCase):
    def entry(self, **overrides: object) -> dict[str, object]:
        entry: dict[str, object] = {
            "name": "p.generated.yaml",
            "description": "demo",
            "subscriptions": {"s": {"url": "https://example.com/sub"}},
            "subscriptionInterval": 60,
            "strategy": "round-robin",
        }
        entry.update(overrides)
        return entry

    def test_default_management_ports(self) -> None:
        profile = rp.assert_profile(self.entry())
        self.assertEqual(profile["mixed_port"], rp.DEFAULT_MIXED_PORT)
        self.assertEqual(profile["external_controller_port"], rp.DEFAULT_EXTERNAL_CONTROLLER_PORT)

    def test_custom_management_ports(self) -> None:
        profile = rp.assert_profile(
            self.entry(mixedPort=17897, externalControllerPort=19097)
        )
        self.assertEqual(profile["mixed_port"], 17897)
        self.assertEqual(profile["external_controller_port"], 19097)

    def test_management_ports_must_differ(self) -> None:
        with self.assertRaises(rp.ProfileError):
            rp.assert_profile(self.entry(mixedPort=17897, externalControllerPort=17897))

    def test_management_port_out_of_range(self) -> None:
        with self.assertRaises(rp.ProfileError):
            rp.assert_profile(self.entry(mixedPort=80))

    def test_listener_conflicts_with_management_port(self) -> None:
        template = (
            "mixed-port: {{MIXED_PORT}}\n"
            "external-controller: 127.0.0.1:{{EXTERNAL_CONTROLLER_PORT}}\n"
            "port: {{PORT_ALL}}\n"
            "{{PROXY_PROVIDERS}}\n"
            "{{USE_PROVIDERS}}\n"
        )
        profile = rp.assert_profile(self.entry(mixedPort=17100, portAll=17100))
        with self.assertRaises(rp.ProfileError):
            rp.build_body(template, profile, ["all"], [])


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = {
            "defaults": {"description": "默认"},
            "profiles": [
                {"name": "a.generated.yaml"},
                {"name": "b.generated.yaml"},
            ],
        }

    def test_unknown_from_is_selection_error(self) -> None:
        with self.assertRaises(rp.SelectionError):
            rp.select_outputs(self.manifest, ["x"], "nope")

    def test_from_without_output_is_selection_error(self) -> None:
        with self.assertRaises(rp.SelectionError):
            rp.select_outputs(self.manifest, [], "a")

    def test_duplicate_output_is_selection_error(self) -> None:
        with self.assertRaises(rp.SelectionError):
            rp.select_outputs(self.manifest, ["a", "a"], "")

    def test_new_output_inherits_defaults(self) -> None:
        selected, _ = rp.select_outputs(self.manifest, ["crawler"], "")
        self.assertEqual(selected[0]["name"], "crawler.generated.yaml")
        self.assertEqual(selected[0]["entry"]["description"], "默认")


if __name__ == "__main__":
    unittest.main()
