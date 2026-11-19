#!/usr/bin/env python3
"""只读检查 mihomo 的 proxy-provider / rule-provider 新鲜度。

默认输出竖排明细（含缓存路径），--summary 打印汇总表，--json 供其他脚本消费。
只发 GET 请求、只读本地配置，不会触发下载或测速。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mihomo_provider import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_STATE,
    EXIT_USAGE,
    ApiError,
    ConfigError,
    age_text,
    api_base,
    api_headers,
    configure_stdout,
    file_exists,
    format_blocks,
    format_bytes,
    format_table,
    local_now,
    parse_datetime,
    provider_config_entry,
    read_provider_config,
    request_json,
    resolve_provider_path,
    resolve_runtime,
    time_text,
    to_json,
    to_local,
)

DETAIL_FIELDS = (
    "kind",
    "name",
    "vehicle",
    "updatedAt",
    "age",
    "count",
    "stale",
    "note",
    "path",
    "fileExists",
)


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"参数错误：{message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def provider_rows(
    proxy_response: Any,
    rule_response: Any,
    stale_hours: float,
    now: datetime,
    provider_config: dict[tuple[str, str], dict[str, str]],
    home_dir: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sources = (("proxy", proxy_response), ("rule", rule_response))
    for kind, response in sources:
        providers = (response or {}).get("providers") or {}
        for name, provider in providers.items():
            if kind == "proxy" and provider.get("vehicleType") == "Compatible":
                continue
            updated = parse_datetime(provider.get("updatedAt"))
            age = "未知"
            stale = False
            if updated:
                age = age_text(updated, now)
                if stale_hours > 0 and provider.get("vehicleType") == "HTTP":
                    hours = (to_local(now) - to_local(updated)).total_seconds() / 3600
                    stale = hours > stale_hours
            note = ""
            if provider.get("vehicleType") == "File":
                note = "本地文件监听，不自动下载"
            if stale:
                note = f"{note}；疑似过期" if note else "疑似过期"

            entry = provider_config_entry(provider_config, kind, name)
            path = resolve_provider_path(entry, home_dir)
            if kind == "proxy":
                count = len(provider.get("proxies") or [])
            else:
                count = provider.get("ruleCount", 0)
            rows.append(
                {
                    "kind": kind,
                    "name": name,
                    "vehicle": provider.get("vehicleType", ""),
                    "updatedAt": time_text(updated),
                    "age": age,
                    "count": count,
                    "stale": stale,
                    "note": note,
                    "path": path,
                    "fileExists": file_exists(path),
                }
            )
    return rows


def subscription_rows(proxy_response: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    providers = (proxy_response or {}).get("providers") or {}
    for name, provider in providers.items():
        info = provider.get("subscriptionInfo")
        if not info:
            continue
        expire = ""
        try:
            stamp = int(info.get("Expire") or 0)
        except (TypeError, ValueError):
            stamp = 0
        if stamp > 0:
            expire = to_local(datetime.fromtimestamp(stamp)).strftime("%Y-%m-%d")
        rows.append(
            {
                "name": name,
                "upload": format_bytes(info.get("Upload")),
                "download": format_bytes(info.get("Download")),
                "total": format_bytes(info.get("Total")),
                "expireAt": expire,
            }
        )
    return rows


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="check_provider_status.py",
        description="只读检查 mihomo provider 的新鲜度",
        epilog=(
            "退出码: 0 成功 / 1 API 不可达或解析失败 / 2 参数错误 / 3 过期或缺少 provider\n"
            "Windows 用 python 代替 python3。"
        ),
    )
    parser.add_argument("--api", default="", help="外部控制 API 地址，默认取 MIHOMO_API 或 http://127.0.0.1:9097")
    parser.add_argument("--secret", default=None, help="API secret，默认取 MIHOMO_SECRET")
    parser.add_argument("--stale-hours", type=float, default=26, help="过期判定小时数，默认 26；0 关闭")
    parser.add_argument("--json", action="store_true", help="输出 JSON，stdout 只含 JSON")
    parser.add_argument("--fail-on-stale", action="store_true", help="存在过期条目时返回退出码 3")
    parser.add_argument(
        "--require-providers",
        action="store_true",
        help="一个可检查的 provider 都没有时返回退出码 3，适合监控",
    )
    parser.add_argument("--list", action="store_true", help="强制竖排输出；与 --summary 组合时仍带路径")
    parser.add_argument("--summary", action="store_true", help="打印汇总表与订阅用量")
    parser.add_argument("--home-dir", default="", help="内核工作目录 -d，也可用 MIHOMO_HOME")
    parser.add_argument("--config-path", default="", help="内核配置文件 -f，也可用 MIHOMO_CONFIG")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    args = build_parser().parse_args(argv)
    if args.stale_hours < 0:
        print("参数错误：--stale-hours 不能为负数", file=sys.stderr)
        return EXIT_USAGE

    try:
        base = api_base(args.api)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    headers = api_headers(args.secret)

    try:
        _, proxy_response = request_json(base, "/providers/proxies", headers, timeout=10)
        _, rule_response = request_json(base, "/providers/rules", headers, timeout=10)
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR

    now = local_now()
    needs_path = (not args.summary) or args.list or args.json
    home_dir = ""
    config_path = ""
    provider_config: dict[tuple[str, str], dict[str, str]] = {}
    if needs_path:
        runtime = resolve_runtime(args.home_dir, args.config_path)
        home_dir, config_path = runtime.home_dir, runtime.config_path
        provider_config = read_provider_config(config_path)
        if config_path and not Path(config_path).is_file():
            print(f"提示：配置文件不存在，缓存路径按未解析处理：{config_path}", file=sys.stderr)
        elif config_path and not provider_config:
            print(f"提示：配置里没有解析到 provider 条目，缓存路径按未解析处理：{config_path}", file=sys.stderr)

    rows = provider_rows(proxy_response, rule_response, args.stale_hours, now, provider_config, home_dir)
    subscriptions = subscription_rows(proxy_response)
    has_stale = any(row["stale"] for row in rows)
    if not rows:
        print(
            "提示：API 没有返回任何可检查的 provider；当前配置可能未启用 proxy-providers，"
            "可用 --require-providers 让这种情况返回 3",
            file=sys.stderr,
        )

    if args.json:
        print(
            to_json(
                {
                    "api": base,
                    "checkedAt": time_text(now),
                    "staleHours": args.stale_hours,
                    "homeDir": home_dir,
                    "configPath": config_path,
                    "providers": rows,
                    "subscriptions": subscriptions,
                }
            )
        )
    else:
        if needs_path:
            if not home_dir:
                print(
                    "提示：未定位到内核工作目录，path 为空；可用 --home-dir / --config-path "
                    "或环境变量 MIHOMO_HOME / MIHOMO_CONFIG 指定",
                    file=sys.stderr,
                )
            elif not config_path:
                print(
                    f"提示：未定位到内核配置文件，path 为空；可用 --config-path 或环境变量 "
                    f"MIHOMO_CONFIG 指定（HomeDir: {home_dir}）",
                    file=sys.stderr,
                )

        if not args.summary:
            print(format_blocks(rows, DETAIL_FIELDS))
        else:
            print(f"mihomo provider 状态（{base}，检查时间 {time_text(now)}）")
            if args.list:
                print(format_blocks(rows, DETAIL_FIELDS))
            else:
                print(
                    format_table(
                        ("kind", "name", "vehicle", "updatedAt", "age", "count", "note"),
                        (
                            (
                                row["kind"],
                                row["name"],
                                row["vehicle"],
                                row["updatedAt"],
                                row["age"],
                                row["count"],
                                row["note"],
                            )
                            for row in rows
                        ),
                    )
                )
            if subscriptions:
                print()
                print("订阅用量（来自订阅响应头，非实时计费口径）")
                if args.list:
                    print(format_blocks(subscriptions, ("name", "upload", "download", "total", "expireAt")))
                else:
                    print(
                        format_table(
                            ("name", "upload", "download", "total", "expireAt"),
                            (
                                (sub["name"], sub["upload"], sub["download"], sub["total"], sub["expireAt"])
                                for sub in subscriptions
                            ),
                        )
                    )
            if has_stale:
                print(
                    f"提示：存在超过 {args.stale_hours:g} 小时未更新的 provider，可用 --json 查看明细",
                    file=sys.stderr,
                )

    if args.require_providers and not rows:
        return EXIT_STATE
    if args.fail_on_stale and has_stale:
        return EXIT_STATE
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
