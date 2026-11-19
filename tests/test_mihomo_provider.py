from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mihomo_provider as mp


class DecodeTests(unittest.TestCase):
    def test_utf8(self) -> None:
        self.assertEqual(mp.decode_output("中文".encode()), "中文")

    def test_gbk_fallback(self) -> None:
        self.assertEqual(mp.decode_output("中文".encode("gbk")), "中文")

    def test_utf16_bom(self) -> None:
        raw = b"\xff\xfe" + "中文".encode("utf-16-le")
        self.assertEqual(mp.decode_output(raw), "中文")


class TimeTests(unittest.TestCase):
    def test_parse_nanoseconds_and_z(self) -> None:
        dt = mp.parse_datetime("2026-11-12T08:54:25.123456789+08:00")
        assert dt is not None
        self.assertEqual(dt.microsecond, 123456)
        self.assertIsNotNone(dt.tzinfo)
        self.assertIsNotNone(mp.parse_datetime("2026-11-12T08:54:25Z"))

    def test_parse_space_and_empty(self) -> None:
        self.assertIsNotNone(mp.parse_datetime("2026-11-12 08:54:25"))
        self.assertIsNone(mp.parse_datetime(""))
        self.assertIsNone(mp.parse_datetime("not-a-time"))

    def test_age_text(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(mp.age_text(now - timedelta(minutes=30), now), "30m")
        self.assertEqual(mp.age_text(now - timedelta(minutes=90), now), "1h30m")
        self.assertEqual(mp.age_text(now - timedelta(days=2), now), "2d00h")
        self.assertEqual(mp.age_text(now + timedelta(minutes=1), now), "时钟偏差")


class HeaderTests(unittest.TestCase):
    def test_default_and_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mp.api_headers(None), {"Authorization": "Bearer 1"})
        with patch.dict(os.environ, {"MIHOMO_SECRET": "env"}):
            self.assertEqual(mp.api_headers(None), {"Authorization": "Bearer env"})

    def test_explicit_secret_overrides_env(self) -> None:
        with patch.dict(os.environ, {"MIHOMO_SECRET": "env"}):
            self.assertEqual(mp.api_headers("x"), {"Authorization": "Bearer x"})
            self.assertEqual(mp.api_headers(""), {})


class ScalarTests(unittest.TestCase):
    def test_split_yaml_scalar(self) -> None:
        self.assertEqual(mp.split_yaml_scalar('"hello # x"'), "hello # x")
        self.assertEqual(mp.split_yaml_scalar("'a b'"), "a b")
        self.assertEqual(mp.split_yaml_scalar("value # comment"), "value")

    def test_format_bytes(self) -> None:
        self.assertEqual(mp.format_bytes(0), "0 B")
        self.assertEqual(mp.format_bytes(1024), "1.00 KiB")
        self.assertEqual(mp.format_bytes(1536), "1.50 KiB")

    def test_display_width(self) -> None:
        self.assertEqual(mp.display_width("中文a"), 5)
        table = mp.format_table(("name", "值"), [("a", "中")])
        self.assertIn("name", table)
        self.assertIn("----", table)


class ProviderConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.home = self.temp.name
        self.config = Path(self.home) / "config.yaml"
        self.config.write_text(
            """proxy-providers:
  online:
    type: http
    url: "https://example.com/sub"
  "online sub":
    type: http
    url: https://example.com/sub2
  local:
    type: file
    path: ./myprofiles/s4.yaml
rule-providers:
  direct_domain:
    type: http
    behavior: domain
    url: https://example.com/direct.txt
    path: ./ruleset/direct.yaml
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_read_block_providers(self) -> None:
        config = mp.read_provider_config(str(self.config))
        self.assertEqual(config[("proxy", "online")]["type"], "http")
        self.assertEqual(config[("proxy", "online sub")]["url"], "https://example.com/sub2")
        self.assertEqual(config[("proxy", "local")]["path"], "./myprofiles/s4.yaml")
        self.assertEqual(config[("rule", "direct_domain")]["path"], "./ruleset/direct.yaml")

    def test_resolve_provider_path(self) -> None:
        config = mp.read_provider_config(str(self.config))
        local = mp.resolve_provider_path(config[("proxy", "local")], self.home)
        self.assertEqual(local, os.path.join(self.home, "myprofiles", "s4.yaml"))

        online = config[("proxy", "online")]
        expected = os.path.join(self.home, "proxies", mp.md5_hex(online["url"]))
        self.assertEqual(mp.resolve_provider_path(online, self.home), expected)

        rule = config[("rule", "direct_domain")]
        self.assertEqual(
            mp.resolve_provider_path(rule, self.home),
            os.path.join(self.home, "ruleset", "direct.yaml"),
        )

    def test_inline_and_missing(self) -> None:
        self.assertEqual(mp.resolve_provider_path({"type": "inline"}, self.home), "")
        self.assertEqual(mp.resolve_provider_path(None, self.home), "")

    def test_provider_api_path(self) -> None:
        self.assertEqual(mp.provider_api_path("proxy", "a b"), "/providers/proxies/a%20b")
        self.assertEqual(mp.provider_api_path("rule", "a b"), "/providers/rules/a%20b")


if __name__ == "__main__":
    unittest.main()
