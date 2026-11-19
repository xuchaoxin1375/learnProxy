#!/usr/bin/env python3
"""mihomo 控制 API 与 provider 配置的共用工具（仅标准库）。

render_profile 与两个 provider CLI 脚本共用：定位内核运行时、解析 provider 配置、
计算缓存路径、访问外部控制 API、解码子进程输出、格式化输出。保持零第三方依赖，
Windows / Linux / macOS 都只需要 Python 3.10+。

退出码约定（所有 CLI 脚本一致）：
- 0 成功
- 1 运行错误（API、IO、模板或配置解析失败）
- 2 用法错误（参数冲突、缺前置条件、目标不合法）
- 3 状态差异或需要人工处理（产物过期、被手改、provider 过期）
"""

from __future__ import annotations

import hashlib
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, overload

DEFAULT_API = "http://127.0.0.1:9097"
DEFAULT_SECRET = "1"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_STATE = 3
PROCESS_NAME_PATTERN = (
    r"(?i)^(verge-)?mihomo(\.exe)?$|^(clash|clash-meta|clash-verge)(\.exe)?$"
)


class ApiError(Exception):
    """控制 API 请求失败，消息可直接展示给终端用户。"""


class ConfigError(Exception):
    """配置或运行时定位错误。"""


@dataclass
class Runtime:
    home_dir: str = ""
    config_path: str = ""


def api_base(value: str | None) -> str:
    """校验并返回 API 根地址：参数 > MIHOMO_API > 默认本机 9097。"""
    base = (value or os.environ.get("MIHOMO_API") or DEFAULT_API).strip()
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError(f"API 地址不是合法 URL: {base}")
    return base.rstrip("/")


def api_headers(secret: str | None) -> dict[str, str]:
    """鉴权头：参数 > MIHOMO_SECRET > 模板默认 secret。

    显式传 `--secret ''` 表示不带鉴权头；只有未传参数且环境变量为空时才回落到默认值。
    """
    if secret is not None:
        return {"Authorization": f"Bearer {secret}"} if secret else {}
    token = os.environ.get("MIHOMO_SECRET", "")
    if not token:
        token = DEFAULT_SECRET
    return {"Authorization": f"Bearer {token}"}


def request_json(
    base: str,
    path: str,
    headers: dict[str, str],
    timeout: float,
    method: str = "GET",
) -> tuple[int, Any]:
    """发一次请求并解析 JSON；失败时抛 ApiError（带可操作的提示）。"""
    request = urllib.request.Request(base + path, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ApiError(
                f"鉴权失败（HTTP {exc.code}）：检查 --secret 或环境变量 MIHOMO_SECRET"
            ) from exc
        raise ApiError(f"请求 {method} {path} 失败（HTTP {exc.code}）") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"请求 {method} {path} 失败：{exc.reason}") from exc
    except TimeoutError as exc:
        raise ApiError(f"请求 {method} {path} 超时（{timeout:g}s）") from exc
    except OSError as exc:
        raise ApiError(f"请求 {method} {path} 失败：{exc}") from exc

    if not raw.strip():
        return status, None
    try:
        return status, json.loads(raw)
    except ValueError as exc:
        raise ApiError(f"响应不是合法 JSON：{method} {path}") from exc


def provider_api_path(kind: str, name: str) -> str:
    """拼 provider 路径；名称允许包含空格等字符，按 URL 规则转义。"""
    quoted = urllib.parse.quote(name, safe="")
    section = "rules" if kind == "rule" else "proxies"
    return f"/providers/{section}/{quoted}"


def parse_datetime(value: Any) -> datetime | None:
    """解析内核返回的 updatedAt，兼容 RFC3339、纳秒和本地时间文本。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None

    # Python 只认最多 6 位小数，mihomo 有时给 9 位纳秒
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"

    candidates = [text]
    if " " in text and "T" not in text:
        candidates.append(text.replace(" ", "T", 1))
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


@overload
def to_local(value: None) -> None: ...


@overload
def to_local(value: datetime) -> datetime: ...


def to_local(value: datetime | None) -> datetime | None:
    """naive 时间按本机时区解释，aware 时间统一转本地时区。"""
    if value is None:
        return None
    return value.astimezone()


def time_text(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    local = to_local(value)
    return local.strftime(fmt) if local else ""


def age_text(updated: datetime, now: datetime) -> str:
    updated = to_local(updated)
    now = to_local(now)
    span = now - updated
    total_minutes = span.total_seconds() / 60
    if total_minutes < 0:
        return "时钟偏差"
    if total_minutes < 60:
        return f"{int(total_minutes)}m"
    if total_minutes < 48 * 60:
        return f"{int(total_minutes // 60)}h{int(total_minutes % 60):02d}m"
    return f"{int(total_minutes // 1440)}d{int(total_minutes % 1440 // 60):02d}h"


def format_bytes(value: Any) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0.0
    if size <= 0:
        return "0 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:,.2f} {units[index]}"


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def split_yaml_scalar(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] in ("'", '"'):
        quote = text[0]
        end = text.find(quote, 1)
        if end > 0:
            return text[1:end]
    comment = text.find(" #")
    if comment >= 0:
        text = text[:comment]
    return text.strip()


def read_provider_config(config_path: str | None) -> dict[tuple[str, str], dict[str, str]]:
    """只解析 proxy-providers / rule-providers 的块状写法（type/path/url）。

    保持与原 PowerShell 实现一致：不展开 YAML 锚点与流式写法；解析不到时
    路径显示为未解析，而不是让整个脚本失败。
    """
    entries: dict[tuple[str, str], dict[str, str]] = {}
    if not config_path or not os.path.isfile(config_path):
        return entries

    section = ""
    kind = ""
    provider_indent = -1
    field_indent = -1
    current: dict[str, str] | None = None

    with open(config_path, encoding="utf-8-sig", errors="replace") as handle:
        for raw_line in handle:
            text = raw_line.rstrip()
            if not text.strip():
                continue
            trimmed = text.lstrip()
            if trimmed.startswith("#"):
                continue
            indent = len(text) - len(trimmed)

            if indent == 0:
                provider_indent = -1
                field_indent = -1
                current = None
                match = re.match(r"^(proxy-providers|rule-providers):\s*(#.*)?$", trimmed)
                if match:
                    section = match.group(1)
                    kind = "proxy" if section == "proxy-providers" else "rule"
                else:
                    section = ""
                continue
            if not section:
                continue
            if provider_indent < 0:
                provider_indent = indent

            if indent == provider_indent:
                current = None
                field_indent = -1
                match = re.match(r"""^("[^"]+"|'[^']+'|[^:#]+):\s*(.*)$""", trimmed)
                if match:
                    name = split_yaml_scalar(match.group(1))
                    if name:
                        current = {
                            "name": name,
                            "kind": kind,
                            "type": "",
                            "path": "",
                            "url": "",
                        }
                        entries[(kind, name)] = current
                continue

            if current is None:
                continue
            if field_indent < 0:
                field_indent = indent
            if indent != field_indent:
                continue
            match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", trimmed)
            if not match:
                continue
            key = match.group(1).lower()
            value = split_yaml_scalar(match.group(2))
            if key == "type":
                current["type"] = value.lower()
            elif key in ("path", "url"):
                current[key] = value
    return entries


def provider_config_entry(
    config: dict[tuple[str, str], dict[str, str]],
    kind: str,
    name: str,
) -> dict[str, str] | None:
    return config.get((kind, name))


def _to_absolute(path: str, home_dir: str) -> str:
    if os.path.isabs(path):
        return os.path.abspath(path)
    if not home_dir:
        return ""
    return os.path.abspath(os.path.join(home_dir, path))


def resolve_provider_path(entry: dict[str, str] | None, home_dir: str) -> str:
    """缓存文件路径：显式 path 优先，http 未写 path 时按 url 的 md5。"""
    if not entry:
        return ""
    if entry.get("type") == "inline":
        return ""
    if entry.get("path"):
        return _to_absolute(entry["path"], home_dir)
    if entry.get("type") == "http" and entry.get("url") and home_dir:
        section = "rules" if entry.get("kind") == "rule" else "proxies"
        return os.path.abspath(os.path.join(home_dir, section, md5_hex(entry["url"])))
    return ""


def file_exists(path: str) -> bool:
    return bool(path) and os.path.isfile(path)


def decode_output(raw: bytes) -> str:
    """解码子进程输出：BOM 优先，其次 UTF-8，最后回落到系统编码。

    中文 Windows 上 PowerShell / mihomo 的管道输出可能是 GBK，直接按 UTF-8
    硬解会乱码或抛 UnicodeDecodeError。这里按字节收齐后再逐种编码尝试。
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gbk"):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def _proc_cmdlines() -> list[str]:
    """Linux: 从 /proc/<pid>/cmdline 读取，不依赖额外工具。"""
    found: list[str] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        cmdline = entry / "cmdline"
        try:
            raw = cmdline.read_bytes()
        except OSError:
            continue
        text = raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        if re.search(r"(?i)mihomo|clash", text):
            found.append(text)
    return found


def _ps_cmdlines() -> list[str]:
    """macOS / 其它 POSIX: 用 ps 取完整命令行。"""
    try:
        result = subprocess.run(
            ["ps", "-axo", "args="],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [
        line.strip()
        for line in decode_output(result.stdout).splitlines()
        if re.search(r"(?i)mihomo|clash", line)
    ]


def _windows_cmdlines() -> list[str]:
    """Windows: 借 PowerShell CIM 取命令行；取不到就算了，参数与环境变量仍可用。"""
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        return []
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.Name -match '{PROCESS_NAME_PATTERN}' }} | "
        "ForEach-Object { $_.CommandLine }"
    )
    try:
        result = subprocess.run(
            [shell, "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in decode_output(result.stdout).splitlines() if line.strip()]


def iter_provider_process_args() -> Iterator[str]:
    if os.name == "nt":
        yield from _windows_cmdlines()
        return
    commands = _proc_cmdlines()
    if commands:
        yield from commands
        return
    yield from _ps_cmdlines()


def _cli_arg_value(command_line: str, kind: str) -> str:
    pattern = (
        rf"(?:^|\s)-{{1,2}}(?:{kind})(?:\s+|=)"
        r"(\"([^\"]+)\"|'([^']+)'|(\S+))"
    )
    match = re.search(pattern, command_line)
    if not match:
        return ""
    for group in (2, 3, 4):
        value = match.group(group)
        if value and value.strip():
            return value
    return ""


def resolve_runtime(home_dir: str | None = None, config_path: str | None = None) -> Runtime:
    """定位 HomeDir（-d）与配置文件（-f）：参数 > 环境变量 > 内核进程命令行。"""
    home = (home_dir or os.environ.get("MIHOMO_HOME", "")).strip()
    config = (config_path or os.environ.get("MIHOMO_CONFIG", "")).strip()

    if not home or not config:
        for command in iter_provider_process_args():
            if not home:
                home = _cli_arg_value(command, "d|directory")
            if not config:
                config = _cli_arg_value(command, "f|config")
            if home and config:
                break

    if home:
        home = os.path.abspath(os.path.expanduser(home))
    if config:
        config = os.path.abspath(os.path.expanduser(config))
    if not config and home:
        candidate = os.path.join(home, "config.yaml")
        if os.path.isfile(candidate):
            config = candidate
    if not home and config:
        home = os.path.dirname(config)

    return Runtime(home_dir=home, config_path=config)


def display_width(text: Any) -> int:
    """终端显示宽度：中日韩全角字符按 2 列算，避免表格错位。"""
    width = 0
    for char in str(text):
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def pad(text: Any, width: int) -> str:
    text = str(text)
    return text + " " * max(0, width - display_width(text))


def format_table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    headers = list(headers)
    body = [list(row) for row in rows]
    widths = [display_width(header) for header in headers]
    for row in body:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], display_width(cell))
    lines = [
        "  ".join(pad(header, widths[index]) for index, header in enumerate(headers)),
        "  ".join("-" * width for width in widths),
    ]
    for row in body:
        lines.append(
            "  ".join(pad(cell, widths[index]) for index, cell in enumerate(row))
        )
    return "\n".join(lines)


def format_blocks(rows: Iterable[dict[str, Any]], fields: Iterable[str]) -> str:
    """仿 Format-List 的竖排输出，保持脚本迁移前后的可读性。"""
    fields = list(fields)
    chunks: list[str] = []
    for row in rows:
        width = max(display_width(field) for field in fields)
        lines = [f"{pad(field, width)} : {row.get(field, '')}" for field in fields]
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks)


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def configure_stdout() -> None:
    """重定向时固定 UTF-8：Windows 默认按本地代码页写管道，落盘会变 GBK。"""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if sys.stdout.isatty() or reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", newline="\n")
    except (ValueError, OSError):
        pass
