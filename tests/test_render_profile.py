from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import render_profile as rp


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
