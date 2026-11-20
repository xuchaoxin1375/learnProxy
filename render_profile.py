#!/usr/bin/env python3
"""从模板 + profiles.json 渲染 mihomo 配置。

用法（Linux/macOS）: python3 render_profile.py [选项]
用法（Windows）   : python render_profile.py [选项]

职责：
- 从 templates/<template> 与 profiles.json（或本地私有清单）的 defaults/profiles 渲染产物
- 清单选择：--manifest > templates/spider_lb.profiles.local.json > templates/spider_lb.profiles.json
- 默认输出到 ~/Desktop/mihomo-profiles；没有 Desktop 目录时回退到 ~/mihomo-profiles
- 每个产物头部写修订日期、用途、描述、来源与正文 SHA256 指纹
- 用指纹区分“最新 / 未生成 / 被手改 / 需重渲染”，手改产物默认拒绝覆盖
- 支持 `--check`（可配 `--allow-missing`）、`--print`、`--list`、`--dry-run`、`--test`，详见 `--help`

位置参数只表示输出名，`--from` 只表示内容来源；产物 name 直接写文件名（带 .yaml），
也是位置参数的选择键（全名或去掉后缀的短名）。模板里的 {{PROXY_PROVIDERS}} /
{{USE_PROVIDERS}} 由 subscriptions 循环生成，增删在线订阅只需要改 profiles.json。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mihomo_provider import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_STATE,
    EXIT_USAGE,
    configure_stdout,
    decode_output,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
MANIFEST_PATH = TEMPLATE_DIR / "spider_lb.profiles.json"
LOCAL_MANIFEST_PATH = TEMPLATE_DIR / "spider_lb.profiles.local.json"
DEFAULT_OUTPUT_DIR_NAME = "mihomo-profiles"
DEFAULT_MIXED_PORT = 7897
DEFAULT_EXTERNAL_CONTROLLER_PORT = 9097

STRATEGY_NAMES = ("round-robin", "consistent-hashing", "sticky-sessions")
REGION_PORT_FIELDS = {"all": "portAll", "eu": "portEu"}
DEFAULT_COUNTRY_ORDER = ("US", "JP", "HK", "SG", "DE", "FR", "TH", "RU", "TW", "UK")

PROFILE_FIELDS = {
    "name",
    "description",
    "subscriptions",
    "subscriptionInterval",
    "strategy",
    "portAll",
    "portEu",
    "countryOrder",
    "ports",
    "allowCommonPorts",
    "mixedPort",
    "externalControllerPort",
}
SUBSCRIPTION_FIELDS = {"url", "interval", "filter", "exclude-filter", "proxy", "path"}

# 常见代理/浏览器调试工具的默认端口：入口撞上这些值，与其它软件抢端口的概率很高
COMMON_PORTS = set(range(7890, 7900)) | {
    1080,
    1081,
    1086,
    1087,
    2080,
    3128,
    8080,
    8081,
    8118,
    8123,
    8888,
    8889,
    9090,
    9091,
    9097,
    9222,
    10808,
    10809,
    10810,
    20171,
    20172,
}


class TemplateError(Exception):
    pass


class ProfileError(Exception):
    pass


class SelectionError(ProfileError):
    """命令行选择错误：未知目标、重复输出名等，按用法错误返回 2。"""


class ManifestError(Exception):
    pass


class ArgumentParser(argparse.ArgumentParser):
    """参数错误统一返回 2（argparse 默认也是 2，这里保持与其它脚本一致）。"""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"参数错误：{message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    return text.replace("\r\n", "\n")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def active_text(text: str) -> str:
    """去掉整行注释，占位符与端口只从生效内容里解析。"""
    return "\n".join(
        line for line in text.split("\n") if not line.lstrip().startswith("#")
    )


def template_port_keys(template: str) -> list[str]:
    keys: list[str] = []
    for match in re.finditer(r"\{\{PORT_([A-Z0-9]+)\}\}", active_text(template)):
        key = match.group(1).lower()
        if key not in keys:
            keys.append(key)
    return keys


def template_reserved_ports(template: str) -> list[int]:
    reserved: list[int] = []
    text = active_text(template)
    patterns = (
        r"(?m)^\s*(?:mixed-port|port|socks-port|redir-port|tproxy-port)\s*:\s*(\d+)",
        r"(?m)^\s*external-controller\s*:\s*[^\s#]*:(\d+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            port = int(match.group(1))
            if port not in reserved:
                reserved.append(port)
    return reserved


def field_names(obj: Any) -> list[str]:
    if not isinstance(obj, dict):
        return []
    return [key for key in obj if not str(key).startswith("_")]


def check_fields(obj: Any, where: str) -> None:
    for field in field_names(obj):
        if field not in PROFILE_FIELDS:
            allowed = ", ".join(sorted(PROFILE_FIELDS))
            raise ProfileError(f"{where} 出现未知字段: {field};可用字段: {allowed}")


def check_defaults(defaults: Any) -> None:
    if defaults is None:
        return
    if not isinstance(defaults, dict):
        raise ManifestError("profiles.json 的 defaults 必须是对象")
    names = field_names(defaults)
    if "name" in names:
        raise ProfileError("defaults 不能包含 name:产物文件名必须每份单独指定")
    allowed = PROFILE_FIELDS - {"name"}
    for field in names:
        if field not in allowed:
            raise ProfileError(
                f"defaults 出现未知字段: {field};可用字段: {', '.join(sorted(allowed))}"
            )


def int_value(value: Any, where: str) -> int:
    if isinstance(value, bool):
        raise ProfileError(f"{where} 不是整数: {value}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value.strip())
    raise ProfileError(f"{where} 不是整数: {value}")


def merge_entry(entry: dict[str, Any], defaults: dict[str, Any] | None) -> dict[str, Any]:
    """只做顶层字段覆盖：数组与 ports 表整体替换，避免删不掉的父项。"""
    if not defaults:
        return dict(entry)
    merged = {key: value for key, value in defaults.items() if not str(key).startswith("_")}
    for key, value in entry.items():
        if not str(key).startswith("_"):
            merged[key] = value
    return merged


def management_ports(entry: dict[str, Any], name: str) -> tuple[int, int]:
    """读取 mixed-port 与 external-controller 端口，二者必须独立且可用。"""
    mixed = int_value(entry.get("mixedPort", DEFAULT_MIXED_PORT), f"{name}: mixedPort")
    controller = int_value(
        entry.get("externalControllerPort", DEFAULT_EXTERNAL_CONTROLLER_PORT),
        f"{name}: externalControllerPort",
    )
    for label, port in (("mixedPort", mixed), ("externalControllerPort", controller)):
        if port < 1024 or port > 65535:
            raise ProfileError(f"{name}: {label} 超出可用范围（1024-65535）: {port}")
    if mixed == controller:
        raise ProfileError(f"{name}: mixedPort 与 externalControllerPort 不能相同: {mixed}")
    return mixed, controller


def assert_profile(entry: dict[str, Any]) -> dict[str, Any]:
    required = ("name", "description", "subscriptions", "strategy")
    for field in required:
        if field not in entry:
            raise ProfileError(f"profiles.json 条目缺少字段: {field}")
        if isinstance(entry[field], str) and not entry[field].strip():
            raise ProfileError(f"profiles.json 条目字段为空: {field} (name={entry.get('name')})")

    name = str(entry["name"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.yaml", name):
        raise ProfileError(f"profile 名称必须是带 .yaml 后缀的文件名（只允许字母数字与 _ . -）: {name}")
    if "\n" in str(entry["description"]):
        raise ProfileError(f"profile 描述不能换行: {name}")
    strategy = str(entry["strategy"])
    if strategy not in STRATEGY_NAMES:
        raise ProfileError(
            f"{name}: strategy 只支持 {' / '.join(STRATEGY_NAMES)}，当前值: {strategy}"
        )

    default_interval = 0
    if "subscriptionInterval" in entry:
        default_interval = int_value(entry["subscriptionInterval"], f"{name}: subscriptionInterval")
        if default_interval < 60:
            raise ProfileError(f"{name}: subscriptionInterval 至少 60 秒，当前: {default_interval}")

    mixed_port, external_controller_port = management_ports(entry, name)

    subscriptions: list[dict[str, Any]] = []
    raw_subscriptions = entry["subscriptions"]
    if not isinstance(raw_subscriptions, dict) or not raw_subscriptions:
        raise ProfileError(f"{name}: subscriptions 至少要有一个在线订阅")

    for provider, raw_sub in raw_subscriptions.items():
        provider = str(provider)
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", provider):
            raise ProfileError(
                f"{name}: 订阅名不合法（小写字母开头，只允许小写字母、数字、_ 和 -）: {provider}"
            )
        if not isinstance(raw_sub, dict):
            raise ProfileError(f"{name}: 订阅 {provider} 必须是对象（url / interval 等）")
        unknown = [key for key in field_names(raw_sub) if key not in SUBSCRIPTION_FIELDS]
        if unknown:
            raise ProfileError(
                f"{name}: 订阅 {provider} 出现未知字段: {', '.join(unknown)};"
                f"可用字段: {', '.join(sorted(SUBSCRIPTION_FIELDS))}"
            )
        url = str(raw_sub.get("url", "")).strip()
        if not url:
            raise ProfileError(f"{name}: 订阅 {provider} 缺少 url")
        if not url.startswith("https://"):
            raise ProfileError(f"{name}: 订阅 {provider} 的地址必须是 https: {url}")

        if "interval" in raw_sub:
            interval = int_value(raw_sub["interval"], f"{name}: 订阅 {provider} 的 interval")
        else:
            interval = default_interval
        if interval < 60:
            raise ProfileError(
                f"{name}: 订阅 {provider} 的 interval 至少 60 秒，"
                f"或改用 subscriptionInterval 提供默认值"
            )

        sub: dict[str, Any] = {
            "name": provider,
            "url": url,
            "interval": interval,
            "filter": str(raw_sub.get("filter", "")).strip(),
            "exclude-filter": str(raw_sub.get("exclude-filter", "")).strip(),
            "proxy": str(raw_sub.get("proxy", "PROXY")).strip() or "PROXY",
            "path": str(raw_sub.get("path", "")).strip(),
        }
        subscriptions.append(sub)

    return {
        "name": name,
        "description": str(entry["description"]),
        "strategy": strategy,
        "mixed_port": mixed_port,
        "external_controller_port": external_controller_port,
        "subscriptions": subscriptions,
        "entry": entry,
    }


def resolve_ports(
    entry: dict[str, Any],
    name: str,
    template_keys: list[str],
    reserved_ports: list[int],
) -> dict[str, int]:
    keys = [key.lower() for key in template_keys]
    ports: dict[str, int] = {}

    if "portUk" in entry:
        raise ProfileError(
            f"{name}: portUk 已废弃，uk 现在是普通国家，端口由 countryOrder 连号或 ports 表决定"
        )

    if "ports" in entry:
        conflicts = [field for field in ("portAll", "portEu", "countryOrder") if field in entry]
        if conflicts:
            raise ProfileError(
                f"{name}: ports 与 {'/'.join(conflicts)} 不能同时使用（显式模式不再做连号推导）"
            )
        raw_ports = entry["ports"]
        if not isinstance(raw_ports, dict) or not raw_ports:
            raise ProfileError(f"{name}: ports 不能为空")
        for raw_key, raw_value in raw_ports.items():
            key = str(raw_key).lower()
            if key in ports:
                raise ProfileError(f"{name}: ports 键重复: {key}")
            ports[key] = int_value(raw_value, f"{name}: ports.{raw_key}")
    else:
        for key, field in REGION_PORT_FIELDS.items():
            if key not in keys:
                continue
            if field not in entry:
                raise ProfileError(
                    f"{name}: 模板含 {{{{PORT_{key.upper()}}}}} 但缺少字段 {field}（或改用 ports）"
                )
            ports[key] = int_value(entry[field], f"{name}: {field}")

        country_keys = [key for key in keys if key not in REGION_PORT_FIELDS]
        if country_keys:
            if "portEu" not in entry:
                raise ProfileError(f"{name}: 模板含国家级入口，但缺少连号起点 portEu")
            base = int_value(entry["portEu"], f"{name}: portEu")
            order = entry.get("countryOrder", list(DEFAULT_COUNTRY_ORDER))
            if not isinstance(order, list):
                raise ProfileError(f"{name}: countryOrder 必须是数组")
            normalized = [str(code).lower() for code in order]
            duplicates = sorted({code for code in normalized if normalized.count(code) > 1})
            if duplicates:
                raise ProfileError(f"{name}: countryOrder 有重复项: {', '.join(duplicates)}")
            for code in normalized:
                if code in REGION_PORT_FIELDS:
                    raise ProfileError(f"{name}: countryOrder 不能包含地区键: {code}")
                if not re.fullmatch(r"[a-z0-9]{2,8}", code):
                    raise ProfileError(
                        f"{name}: countryOrder 里的代码不合法（小写字母数字 2-8 位）: {code}"
                    )
            for index, code in enumerate(normalized):
                ports[code] = base + index + 1

    missing = [key for key in keys if key not in ports]
    if missing:
        raise ProfileError(f"{name}: 模板需要这些端口，但配置里没有: {', '.join(missing)}")
    unused = [key for key in ports if key not in keys]
    if unused:
        raise ProfileError(f"{name}: 配置了这些端口，但模板没有对应占位符: {', '.join(unused)}")

    for key, value in ports.items():
        if value < 1024 or value > 65535:
            raise ProfileError(f"{name}: 端口超出可用范围（1024-65535）: {key}={value}")
    seen: dict[int, str] = {}
    for key, value in ports.items():
        if value in seen:
            raise ProfileError(f"{name}: 入口端口重复: {seen[value]} 与 {key} 都是 {value}")
        seen[value] = key
    for port in reserved_ports:
        if port in ports.values():
            raise ProfileError(f"{name}: 入口端口与 mixed-port/external-controller 冲突: {port}")

    allow_common = entry.get("allowCommonPorts", False)
    if not isinstance(allow_common, bool):
        raise ProfileError(f"{name}: allowCommonPorts 只接受 true/false")
    if not allow_common:
        hits = [
            f"{key}={value}"
            for key, value in ports.items()
            if value in COMMON_PORTS
        ]
        if hits:
            raise ProfileError(
                f"{name}: 入口端口与常见软件默认端口重叠: {', '.join(hits)};"
                '换一个端口段，或在该条目加 "allowCommonPorts": true 显式放行'
            )

    high = [f"{key}={value}" for key, value in ports.items() if value >= 32768]
    if high:
        print(
            f"警告: {name}: 端口落在临时端口区间（>=32768），可能被系统临时分配撞上: "
            f"{', '.join(high)}",
            file=sys.stderr,
        )
    return ports


def yaml_double(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def yaml_single(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def yaml_token(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        return value
    return yaml_single(value)


def provider_block_lines(subscriptions: list[dict[str, Any]]) -> list[str]:
    """生成 proxy-providers 条目（相对缩进，由调用方补模板缩进）。"""
    lines: list[str] = []
    for index, sub in enumerate(subscriptions):
        if index:
            lines.append("")
        lines.append(f"{sub['name']}:")
        lines.append("  type: http")
        lines.append(f"  url: {yaml_double(sub['url'])}")
        if sub["path"]:
            lines.append(f"  path: {yaml_double(sub['path'])}")
        lines.append(f"  proxy: {yaml_token(sub['proxy'])}")
        lines.append("  <<: *pc")
        if sub["filter"]:
            lines.append(f"  filter: {yaml_single(sub['filter'])}")
        if sub["exclude-filter"]:
            lines.append(f"  exclude-filter: {yaml_single(sub['exclude-filter'])}")
        hours = f"{sub['interval'] / 3600:g}"
        lines.append(f"  # 覆盖锚点的 86400;订阅约每 {hours} 小时拉一次")
        lines.append(f"  interval: {sub['interval']}")
    return lines


def use_provider_lines(subscriptions: list[dict[str, Any]]) -> list[str]:
    return [f"- {sub['name']}" for sub in subscriptions]


def replace_block(text: str, marker: str, lines: list[str]) -> str:
    """把独占一行的 {{MARKER}} 替换成多行块，按标记行缩进对齐。"""
    pattern = re.compile(rf"^([ \t]*)\{{\{{{marker}\}}\}}[ \t]*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        raise TemplateError(f"模板缺少 {{{{{marker}}}}} 标记行")
    if len(matches) > 1:
        raise TemplateError(f"模板里的 {{{{{marker}}}}} 标记行只能有一个")
    match = matches[0]
    indent = match.group(1)
    block = "\n".join((indent + line) if line else "" for line in lines)
    return text[: match.start()] + block + text[match.end():]


def placeholder_values(profile: dict[str, Any], ports: dict[str, int]) -> dict[str, str]:
    values = {
        "{{STRATEGY}}": profile["strategy"],
        "{{MIXED_PORT}}": str(profile["mixed_port"]),
        "{{EXTERNAL_CONTROLLER_PORT}}": str(profile["external_controller_port"]),
    }
    for key, value in ports.items():
        values[f"{{{{PORT_{key.upper()}}}}}"] = str(value)
    return values


def render_body(template: str, values: dict[str, str]) -> str:
    body = template
    for key, value in values.items():
        body = body.replace(key, value)
    for line in body.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        leftover = re.search(r"\{\{[A-Z0-9_]+\}\}", line)
        if leftover:
            raise TemplateError(f"模板里存在未替换的占位符: {leftover.group(0)}")
    if not body.endswith("\n"):
        body += "\n"
    return body


def new_profile_text(
    revision: str,
    description: str,
    fingerprint: str,
    body: str,
    template_name: str,
) -> str:
    script_label = f"{BASE_DIR.name}/{Path(__file__).name}"
    template_label = f"{BASE_DIR.name}/{TEMPLATE_DIR.name}/{template_name}"
    header = "\n".join(
        (
            f"# 修订日期:{revision}",
            "# 用途:爬虫按入站端口固定国家出口(见 rules 中的 IN-NAME),其余流量走 PROXY",
            f"# {description}",
            f"# 由 {script_label} 从 {template_label} 生成,不要手改",
            f"# 生成指纹:sha256:{fingerprint}",
        )
    )
    return header + "\n" + body


def read_generated(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    lines = read_text(path).split("\n")
    fingerprint_index = -1
    fingerprint = ""
    for index, line in enumerate(lines[:8]):
        match = re.fullmatch(r"# 生成指纹:sha256:([0-9a-f]{64})", line)
        if match:
            fingerprint_index = index
            fingerprint = match.group(1)
            break
    revision = ""
    match = re.match(r"^# 修订日期:(.+)$", lines[0]) if lines else None
    if match:
        revision = match.group(1)
    if fingerprint_index < 0:
        return {"revision": revision, "fingerprint": "", "body": None}
    if fingerprint_index == len(lines) - 1:
        body = ""
    else:
        body = "\n".join(lines[fingerprint_index + 1:])
    return {"revision": revision, "fingerprint": fingerprint, "body": body}


def state_of(existing: dict[str, Any] | None, body: str) -> str:
    if existing is None:
        return "missing"
    if existing["body"] == body:
        return "uptodate"
    if not existing["fingerprint"]:
        return "foreign"
    if existing["fingerprint"] != sha256_hex(existing["body"] or ""):
        return "modified"
    return "stale"


def state_text(state: str) -> str:
    return {
        "uptodate": "最新",
        "missing": "未生成",
        "foreign": "缺生成指纹(非本脚本生成)",
        "modified": "被手改",
        "stale": "需重新渲染",
    }.get(state, state)


def find_mihomo(explicit: str | None = None) -> str:
    """定位 mihomo：--mihomo > MIHOMO_BIN > PATH 中的 mihomo/verge-mihomo。"""
    candidate = (explicit or os.environ.get("MIHOMO_BIN", "")).strip()
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path.resolve())
        raise OSError(f"mihomo 可执行文件不存在: {path}")
    for name in ("mihomo", "verge-mihomo"):
        found = shutil.which(name)
        if found:
            return found
    raise OSError(
        "找不到 mihomo 命令；用 --mihomo 指定、设置 MIHOMO_BIN，"
        "或把 mihomo/verge-mihomo 放进 PATH"
    )


def run_mihomo_test(paths: list[Path], home_dir: str, mihomo: str | None = None) -> int:
    command = find_mihomo(mihomo)
    if not os.path.isdir(home_dir):
        raise OSError(f"MihomoHome 不存在: {home_dir}")

    failed = 0
    for path in paths:
        try:
            result = subprocess.run(
                [command, "-t", "-d", home_dir, "-f", str(path)],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            failed += 1
            print(f"[测试超时] {path.name}")
            continue
        if result.returncode == 0:
            print(f"[测试通过] {path.name}")
        else:
            failed += 1
            print(f"[测试失败] {path.name}")
            for line in (decode_output(result.stdout) + decode_output(result.stderr)).splitlines():
                print(f"           {line}")
    return failed


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="render_profile.py",
        description=(
            "从模板渲染 mihomo 爬虫配置；默认输出到 ~/Desktop/mihomo-profiles，"
            "没有 Desktop 目录时回退到 ~/mihomo-profiles"
        ),
        epilog=(
            "名称解析: 精确文件名 > 去掉 .generated.yaml/.yaml 的短名 > 视为新输出名。\n"
            "新输出名默认补 .generated.yaml，内容取 --from，未给则用 defaults。\n"
            "清单选择: --manifest > templates/spider_lb.profiles.local.json（存在时）> "
            "templates/spider_lb.profiles.json。\n"
            "输出目录可用 profiles.json 的 outputDir 覆盖（支持 ~、绝对路径或相对 templates/ 的路径）。\n"
            "退出码: 0 成功 / 1 运行或配置解析失败 / 2 用法错误 / "
            "3 产物未生成、有差异或需要 --force\n"
            "Windows 用 python 代替 python3。"
        ),
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="输出名",
        help=(
            "要生成的输出名，可写多个或用逗号分隔；省略表示渲染 profiles 里的全部。"
            "已定义的全名/短名按对应条目生成，其它名称视为新输出名"
        ),
    )
    parser.add_argument(
        "--manifest",
        default="",
        metavar="文件",
        help=(
            "profiles 数据文件；省略时优先 templates/spider_lb.profiles.local.json（存在时），"
            "否则用 templates/spider_lb.profiles.json。相对路径按当前目录解析"
        ),
    )
    parser.add_argument(
        "--from",
        dest="source",
        default="",
        metavar="来源",
        help="内容来源：已定义 profile 的全名或短名；省略时新输出名用 defaults",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验输出目录中的产物是否同步；未生成、有差异或产物被手改返回 3",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="配合 --check：未生成的产物不算失败；内容漂移或被手改仍返回 3",
    )
    parser.add_argument(
        "--print",
        dest="print_preview",
        action="store_true",
        help="渲染结果输出到 stdout，不写盘；多份时加注释分隔行（只作预览，不是单份可加载配置）",
    )
    parser.add_argument(
        "--list",
        dest="list_profiles",
        action="store_true",
        help="列出输出目录中已定义 profile 与自定义产物及其状态，不写盘",
    )
    parser.add_argument(
        "--names",
        action="store_true",
        help="配合 --list，只输出名字，一行一个，便于遍历",
    )
    parser.add_argument("--force", action="store_true", help="覆盖被手改过或非本脚本生成的产物")
    parser.add_argument(
        "--test",
        action="store_true",
        help="渲染后调用 mihomo -t 校验；必须提供 --mihomo-home 或 MIHOMO_HOME",
    )
    parser.add_argument(
        "--mihomo-home",
        default="",
        metavar="目录",
        help="mihomo -t 的 -d 目录；也可用环境变量 MIHOMO_HOME",
    )
    parser.add_argument(
        "--mihomo",
        default="",
        metavar="路径",
        help="mihomo 可执行文件；省略时读 MIHOMO_BIN，或在 PATH 中查找 mihomo/verge-mihomo",
    )
    parser.add_argument(
        "--dry-run",
        "--what-if",
        dest="dry_run",
        action="store_true",
        help="只列出将要写入的文件，不落盘",
    )
    parser.add_argument("--verbose", action="store_true", help="打印模板占位符等调试信息")
    return parser


def resolve_manifest_path(
    value: str = "",
    template_dir: Path = TEMPLATE_DIR,
    cwd: Path | None = None,
) -> Path:
    """选择 profiles 数据文件。

    显式 --manifest 优先（相对路径按当前目录解析）；否则优先同目录的
    spider_lb.profiles.local.json，最后回退 spider_lb.profiles.json。
    显式路径不在这里检查存在性，由 load_manifest 统一报错。
    """
    raw = value.strip()
    if raw:
        expanded = os.path.expanduser(os.path.expandvars(raw))
        path = Path(expanded)
        if not path.is_absolute():
            path = (cwd or Path.cwd()) / path
        return Path(os.path.abspath(path))

    local = template_dir / LOCAL_MANIFEST_PATH.name
    if local.is_file():
        return local
    return template_dir / MANIFEST_PATH.name


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or MANIFEST_PATH
    if not manifest_path.is_file():
        raise ManifestError(f"找不到 profiles 数据文件: {manifest_path}")
    try:
        raw = read_text(manifest_path)
    except (OSError, UnicodeError) as exc:
        raise ManifestError(f"读取 profiles 数据文件失败 ({manifest_path}): {exc}") from exc
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise ManifestError(f"{manifest_path} 不是合法 JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError(f"{manifest_path} 顶层必须是对象")
    return manifest


def profile_keys(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_full: dict[str, dict[str, Any]] = {}
    by_short: dict[str, dict[str, Any]] = {}
    for entry in entries:
        name = str(entry.get("name", ""))
        if name in by_full:
            raise ProfileError(f"profiles.json 里有重复的产物名: {name}")
        by_full[name] = entry
        short = short_name(name)
        if not short:
            continue
        if short in by_short:
            other = str(by_short[short].get("name", ""))
            raise ProfileError(f"短名冲突: {other} 与 {name} 都解析为 {short}")
        by_short[short] = entry
    return by_full, by_short


def short_name(name: str) -> str:
    return re.sub(r"(?:\.generated)?\.yaml$", "", name)


def resolve_defined(
    target: str,
    by_full: dict[str, dict[str, Any]],
    by_short: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if target in by_full:
        return by_full[target]
    return by_short.get(target)


def normalize_output_name(value: str) -> str:
    name = value if value.endswith(".yaml") else value + ".generated.yaml"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.yaml", name):
        raise ProfileError(f"输出文件名不合法(只允许字母数字与 _ . -): {value}")
    return name


def load_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries = manifest.get("profiles")
    if not isinstance(entries, list) or not entries:
        raise ManifestError("profiles.json 里没有任何 profile")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ManifestError("profiles.json 的 profiles 条目必须是对象")
    return entries


def select_outputs(
    manifest: dict[str, Any], targets: list[str], source: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """位置参数决定输出名，--from 决定内容来源，两者互不混用。"""
    defaults = manifest.get("defaults")
    check_defaults(defaults)
    entries = load_entries(manifest)
    by_full, by_short = profile_keys(entries)

    source_entry = None
    if source:
        source_entry = resolve_defined(source, by_full, by_short)
        if source_entry is None:
            keys = ", ".join(sorted(by_short))
            raise SelectionError(f"--from 找不到已定义的 profile: {source};可用: {keys}")

    expanded: list[str] = []
    for value in targets:
        expanded.extend(part.strip() for part in value.split(",") if part.strip())

    if not expanded:
        if source_entry is not None:
            raise SelectionError("--from 需要配合一个输出名使用")
        return (
            [{"name": str(entry["name"]), "entry": entry, "defined": True} for entry in entries],
            defaults,
        )

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in expanded:
        entry = resolve_defined(target, by_full, by_short)
        if entry is not None:
            output = str(entry["name"])
            defined = True
        else:
            output = normalize_output_name(target)
            defined = False
        if output in seen:
            raise SelectionError(f"输出文件名重复: {output}")
        seen.add(output)

        if source_entry is not None:
            content = {**source_entry, "name": output}
        elif entry is not None:
            content = entry
        else:
            if not defaults:
                raise SelectionError(f"{output} 未定义，且没有 defaults 可生成默认配置")
            content = {
                key: value for key, value in defaults.items() if not str(key).startswith("_")
            }
            content["name"] = output
        selected.append({"name": output, "entry": content, "defined": defined})
    return selected, defaults


def resolve_output_dir(
    raw: str,
    template_dir: Path = TEMPLATE_DIR,
    home: Path | None = None,
) -> Path:
    """解析 outputDir。

    空值：优先 ~/Desktop/mihomo-profiles，缺少 Desktop 目录时回退 ~/mihomo-profiles。
    非空：展开 ~ 与环境变量；相对路径按 template_dir 解析，绝对路径保持原样。
    """
    home_dir = Path(home or Path.home()).expanduser()
    raw = raw.strip()
    if not raw:
        desktop = home_dir / "Desktop"
        base = desktop if desktop.is_dir() else home_dir
        return Path(os.path.abspath(base / DEFAULT_OUTPUT_DIR_NAME))

    expanded = os.path.expandvars(raw)
    if expanded == "~" or expanded.startswith(("~/", "~\\")):
        expanded = os.path.join(str(home_dir), expanded[2:])
    path = Path(expanded)
    if not path.is_absolute():
        path = template_dir / path
    return Path(os.path.abspath(path))


def output_directory(manifest: dict[str, Any]) -> Path:
    raw_value = manifest.get("outputDir", "")
    raw = "" if raw_value is None else str(raw_value)
    return resolve_output_dir(raw, TEMPLATE_DIR)


def path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def load_template(manifest: dict[str, Any]) -> tuple[str, str, list[str], list[int]]:
    template_name = str(manifest.get("template", "")).strip()
    if not template_name:
        raise ManifestError("profiles.json 缺少 template 字段")
    if "/" in template_name or "\\" in template_name or Path(template_name).name != template_name:
        raise ManifestError(f"template 只允许写数据目录内的文件名: {template_name}")
    template_path = TEMPLATE_DIR / template_name
    if not template_path.is_file():
        raise ManifestError(f"找不到模板文件: {template_path}")
    template = read_text(template_path)
    if not template.strip():
        raise TemplateError(f"模板内容为空: {template_path}")
    if "&pc" not in active_text(template):
        raise TemplateError("模板缺少 provider-com: &pc 锚点，生成在线订阅块需要它")
    return template, template_name, template_port_keys(template), template_reserved_ports(template)


def build_body(
    template: str,
    profile: dict[str, Any],
    port_keys: list[str],
    reserved: list[int],
) -> str:
    ports = resolve_ports(profile["entry"], profile["name"], port_keys, reserved)
    for label, port in (
        ("mixedPort", profile["mixed_port"]),
        ("externalControllerPort", profile["external_controller_port"]),
    ):
        if port in ports.values():
            raise ProfileError(f"{profile['name']}: {label}={port} 与入口端口冲突")
    body = template
    body = replace_block(body, "PROXY_PROVIDERS", provider_block_lines(profile["subscriptions"]))
    body = replace_block(body, "USE_PROVIDERS", use_provider_lines(profile["subscriptions"]))
    return render_body(body, placeholder_values(profile, ports))


def prepare_profiles(
    entries: list[dict[str, Any]], defaults: dict[str, Any] | None
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for entry in entries:
        check_fields(entry, f"profile {entry.get('name')}")
        profiles.append(assert_profile(merge_entry(entry, defaults)))
    return profiles


def scan_generated(output_dir: Path) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    if not output_dir.is_dir():
        return files
    for path in sorted(output_dir.glob("*.yaml")):
        info = read_generated(path)
        if info is None:
            continue
        # `.generated.yaml` 后缀或文件头指纹，两个证据有一个就算本脚本产物
        if path.name.endswith(".generated.yaml") or info["fingerprint"]:
            files[path.name] = info
    return files


def show_inventory(manifest: dict[str, Any], names_only: bool = False) -> None:
    defaults = manifest.get("defaults")
    check_defaults(defaults)
    entries = load_entries(manifest)
    by_full, _ = profile_keys(entries)
    output_dir = output_directory(manifest)
    files = scan_generated(output_dir)
    custom = [name for name in files if name not in by_full]

    if names_only:
        for entry in entries:
            print(short_name(str(entry.get("name", ""))))
        for name in custom:
            print(name)
        return

    print(f"输出目录: {output_dir}")
    template, _, port_keys, reserved = load_template(manifest)
    print("已定义:")
    for entry in entries:
        check_fields(entry, f"profile {entry.get('name')}")
        profile = assert_profile(merge_entry(entry, defaults))
        body = build_body(template, profile, port_keys, reserved)
        state = state_of(read_generated(output_dir / profile["name"]), body)
        print(
            f"  {short_name(profile['name'])} -> {profile['name']}"
            f" ({state_text(state)})"
        )

    if not custom:
        return

    print()
    print("自定义(未在 profiles.json):")
    default_body = None
    if defaults:
        try:
            default_profile = assert_profile(
                merge_entry({**defaults, "name": "custom.generated.yaml"}, defaults)
            )
            default_body = build_body(template, default_profile, port_keys, reserved)
        except (ProfileError, TemplateError):
            default_body = None
    for name in custom:
        if default_body is None:
            note = "无法校验(defaults 不完整)"
        else:
            state = state_of(files[name], default_body)
            if state == "uptodate":
                note = "按 defaults，最新"
            elif state == "stale":
                note = "已生成(内容非 defaults 或模板已变)"
            else:
                note = state_text(state)
        print(f"  {name} ({note})")



def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    args = build_parser().parse_args(argv)

    if args.names:
        args.list_profiles = True

    if args.list_profiles and (
        args.check
        or args.allow_missing
        or args.print_preview
        or args.test
        or args.dry_run
        or args.force
        or args.source
        or args.targets
    ):
        print(
            "参数错误：--list 只做清单，不能与输出名 / --from / --check / --allow-missing / --print / --test / --dry-run / --force 同时使用",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.allow_missing and not args.check:
        print("参数错误：--allow-missing 只能与 --check 一起使用", file=sys.stderr)
        return EXIT_USAGE
    if args.check and args.print_preview:
        print("参数错误：--print 与 --check 不能同时使用", file=sys.stderr)
        return EXIT_USAGE
    if args.check and args.test:
        print("参数错误：--check 只比对不写入，不能与 --test 同时使用", file=sys.stderr)
        return EXIT_USAGE
    if args.check and args.force:
        print("参数错误：--check 只比对不写入，不能与 --force 同时使用", file=sys.stderr)
        return EXIT_USAGE
    if args.print_preview and args.test:
        print("参数错误：--print 不写盘，--test 需要落盘后的产物", file=sys.stderr)
        return EXIT_USAGE
    if args.dry_run and args.test:
        print("参数错误：--dry-run 不写盘，--test 会校验旧产物；两者不能同时使用", file=sys.stderr)
        return EXIT_USAGE

    test_home = ""
    if args.test:
        test_home = (args.mihomo_home or os.environ.get("MIHOMO_HOME", "")).strip()
        if not test_home:
            print(
                "错误: --test 需要 --mihomo-home 或环境变量 MIHOMO_HOME；"
                "未提供时不会假装校验通过",
                file=sys.stderr,
            )
            return EXIT_USAGE

    try:
        manifest_path = resolve_manifest_path(args.manifest)
        manifest = load_manifest(manifest_path)
    except ManifestError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if manifest_path != MANIFEST_PATH:
        print(f"[清单] {manifest_path}", file=sys.stderr)

    if args.list_profiles:
        try:
            show_inventory(manifest, args.names)
        except (ManifestError, ProfileError, TemplateError) as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_OK

    try:
        selected, defaults = select_outputs(manifest, args.targets, args.source)
    except SelectionError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (ManifestError, ProfileError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        profiles = prepare_profiles([item["entry"] for item in selected], defaults)
    except ProfileError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        output_dir = output_directory(manifest)
        template, template_name, port_keys, reserved = load_template(manifest)
        if not args.print_preview:
            print(f"[输出目录] {output_dir}")
            if path_is_inside(output_dir, BASE_DIR):
                for item in selected:
                    name = str(item.get("name", ""))
                    if not name.endswith(".generated.yaml"):
                        print(
                            f"提示: {name} 不带 .generated 标记，且输出目录在仓库内，注意别误提交",
                            file=sys.stderr,
                        )
        if (
            not args.print_preview
            and not args.dry_run
            and not args.check
            and not output_dir.is_dir()
        ):
            output_dir.mkdir(parents=True, exist_ok=True)
            print(f"[创建目录] {output_dir}")
        if args.verbose:
            print(
                f"模板端口占位符: {', '.join(port_keys)};模板自身占用: {', '.join(map(str, reserved))}",
                file=sys.stderr,
            )
    except (ManifestError, TemplateError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return EXIT_ERROR

    revision = time.strftime("%Y%m%d.%H:%M")
    written = unchanged = planned = printed = 0
    missing: list[str] = []
    drifted: list[str] = []
    blocked: list[str] = []
    rendered: list[Path] = []

    for profile in profiles:
        try:
            body = build_body(template, profile, port_keys, reserved)
        except ProfileError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return EXIT_ERROR
        except TemplateError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return EXIT_ERROR

        fingerprint = sha256_hex(body)
        out_path = output_dir / profile["name"]
        text = new_profile_text(
            revision,
            profile["description"],
            fingerprint,
            body,
            template_name,
        )
        existing = read_generated(out_path)
        rendered.append(out_path)

        if args.print_preview:
            if len(profiles) > 1:
                print(f"# ===== {profile['name']} =====")
            print(text.rstrip("\n"))
            printed += 1
            continue

        state = state_of(existing, body)
        if args.check:
            if state == "uptodate":
                print(f"[最新] {profile['name']}")
            elif state == "missing":
                print(f"[未生成] {profile['name']}")
                missing.append(profile["name"])
            elif state in ("foreign", "modified"):
                print(
                    f"[需覆盖] {profile['name']} "
                    f"(原因: {state},产物被手改过或非本脚本生成,需 --force 覆盖)"
                )
                drifted.append(profile["name"])
            else:
                print(f"[需重渲染] {profile['name']} (原因: 模板或清单已变)")
                drifted.append(profile["name"])
            continue

        if state == "uptodate":
            assert existing is not None
            print(f"[最新] {profile['name']} (修订 {existing['revision']})")
            unchanged += 1
            continue

        if state in ("foreign", "modified") and not args.force:
            print(f"[跳过] {profile['name']} (产物被手改过或不是本脚本生成,加 --force 才会覆盖)")
            blocked.append(profile["name"])
            continue

        if args.dry_run:
            print(f"[预览] {profile['name']} ({state})")
            planned += 1
            continue

        write_text(out_path, text)
        print(f"[写入] {profile['name']} ({state})")
        written += 1

    if args.print_preview:
        if printed > 1:
            print(
                "提示: 多份输出用注释分隔，只作预览；要落盘或给 mihomo 加载请单独指定一份",
                file=sys.stderr,
            )
        print(f"提示: 已输出 {printed} 份到 stdout,未写盘", file=sys.stderr)
        return EXIT_OK

    if args.check:
        parts: list[str] = []
        if missing:
            parts.append(f"{len(missing)} 份未生成")
        if drifted:
            parts.append(f"{len(drifted)} 份需要重新渲染")
        if not parts:
            print("检查结果: 全部与模板一致")
            return EXIT_OK
        print("检查结果: " + "，".join(parts))
        if drifted:
            print(
                "提示: 手改或非本脚本生成的产物先对比内容，确认后再 --force；"
                "模板或清单变更的直接重新渲染"
            )
            return EXIT_STATE
        if not args.allow_missing:
            print("提示: 首次生成请直接运行渲染；只关心漂移可加 --allow-missing")
            return EXIT_STATE
        print("提示: --allow-missing 已忽略未生成项")
        return EXIT_OK

    print(f"汇总: 写入 {written} 份, 未变 {unchanged} 份, 跳过 {len(blocked)} 份, 预览 {planned} 份")
    if args.dry_run:
        print("提示: --dry-run 只列要写的文件;要看渲染内容加 --print（同样不落盘）")

    if blocked:
        print("跳过项被手改过;确认 diff 后加 --force 覆盖,或把改动合并回模板")
        return EXIT_STATE

    if args.test:
        try:
            failed = run_mihomo_test(rendered, test_home, args.mihomo)
        except OSError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return EXIT_ERROR
        if failed:
            print(f"mihomo -t: {failed} 份失败")
            return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
