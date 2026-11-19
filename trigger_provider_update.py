#!/usr/bin/env python3
"""手动触发 mihomo provider 的更新或健康检查。

这是写操作：每次 update 都会真实下载订阅或规则集，消耗流量与请求次数。
默认动作前需要显式给出目标；--all 批量还需要 --yes（或先用 --dry-run 预览）。
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from mihomo_provider import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    ApiError,
    ConfigError,
    api_base,
    api_headers,
    configure_stdout,
    file_exists,
    format_blocks,
    format_table,
    parse_datetime,
    provider_api_path,
    provider_config_entry,
    read_provider_config,
    request_json,
    resolve_provider_path,
    resolve_runtime,
    time_text,
    to_json,
)

DETAIL_FIELDS = (
    "name",
    "kind",
    "mode",
    "status",
    "before",
    "after",
    "count",
    "path",
    "fileExists",
    "detail",
)


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"参数错误：{message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="trigger_provider_update.py",
        description="手动触发 mihomo provider 更新或健康检查",
        epilog=(
            "退出码: 0 全部成功 / 1 存在失败目标 / 2 参数错误或目标无法解析\n"
            "Windows 用 python 代替 python3。"
        ),
    )
    parser.add_argument("targets", nargs="*", metavar="名称", help="provider 名称，可重复或用逗号分隔")
    parser.add_argument("--all", action="store_true", help="处理全部 HTTP provider（File 自动跳过），需配合 --yes")
    parser.add_argument("--yes", action="store_true", help="确认批量执行")
    parser.add_argument("--kind", choices=("auto", "proxy", "rule"), default="auto", help="目标类型，默认自动判断")
    parser.add_argument(
        "--mode",
        choices=("update", "healthcheck"),
        default="update",
        help="update 触发下载；healthcheck 仅代理 provider，异步测速",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--list", action="store_true", help="强制竖排输出；与 --summary 组合时仍带路径")
    parser.add_argument("--summary", action="store_true", help="打印结果表与完成统计")
    parser.add_argument("--timeout", type=int, default=120, help="单次请求超时秒数，默认 120")
    parser.add_argument("--api", default="", help="外部控制 API 地址，默认取 MIHOMO_API")
    parser.add_argument("--secret", default=None, help="API secret，默认取 MIHOMO_SECRET")
    parser.add_argument("--home-dir", default="", help="内核工作目录 -d，也可用 MIHOMO_HOME")
    parser.add_argument("--config-path", default="", help="内核配置文件 -f，也可用 MIHOMO_CONFIG")
    parser.add_argument(
        "--dry-run",
        "--what-if",
        dest="dry_run",
        action="store_true",
        help="只显示将要做什么，不发写请求",
    )
    return parser


def build_catalog(
    base: str,
    headers: dict[str, str],
    provider_config: dict[tuple[str, str], dict[str, str]],
    home_dir: str,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}

    for kind, path in (("proxy", "/providers/proxies"), ("rule", "/providers/rules")):
        _, response = request_json(base, path, headers, timeout=15)
        providers = (response or {}).get("providers") or {}
        for name, provider in providers.items():
            if kind == "proxy" and provider.get("vehicleType") == "Compatible":
                continue
            entry = provider_config_entry(provider_config, kind, name)
            path_text = resolve_provider_path(entry, home_dir)
            item = {
                "name": name,
                "kind": kind,
                "vehicle": provider.get("vehicleType", ""),
                "updatedAt": parse_datetime(provider.get("updatedAt")),
                "count": len(provider.get("proxies") or []) if kind == "proxy" else provider.get("ruleCount", 0),
                "path": path_text,
            }
            by_key[(kind, name)] = item
            by_name.setdefault(name, []).append(item)
    return by_key, by_name


def resolve_targets(
    by_name: dict[str, list[dict[str, Any]]],
    names: list[str],
    kind: str,
    mode: str,
) -> list[dict[str, Any]]:
    expanded: list[str] = []
    for name in names:
        expanded.extend(part.strip() for part in name.split(",") if part.strip())

    selected: list[dict[str, Any]] = []
    for name in expanded:
        items = by_name.get(name, [])
        if not items:
            raise ConfigError(
                f"找不到 provider：{name}（可用 python3 check_provider_status.py 查看现有名称）"
            )
        if kind == "auto":
            if len(items) > 1:
                raise ConfigError(f"provider {name} 同时存在 proxy 与 rule 条目，请用 --kind 指定")
            item = items[0]
        else:
            matches = [item for item in items if item["kind"] == kind]
            if not matches:
                raise ConfigError(f"provider {name} 的类型是 {items[0]['kind']}，与 --kind {kind} 不一致")
            item = matches[0]
        if mode == "healthcheck" and item["kind"] != "proxy":
            raise ConfigError(f"provider {name} 是规则集，不支持健康检查")
        selected.append(item)
    return selected


def invoke_target(
    base: str,
    headers: dict[str, str],
    item: dict[str, Any],
    mode: str,
    timeout: int,
    provider_config: dict[tuple[str, str], dict[str, str]],
    home_dir: str,
    dry_run: bool,
) -> dict[str, Any]:
    before: datetime | None = item["updatedAt"]
    action = "健康检查" if mode == "healthcheck" else "触发更新"
    if dry_run:
        return {
            "name": item["name"],
            "kind": item["kind"],
            "mode": mode,
            "status": "skipped",
            "before": time_text(before),
            "after": time_text(before),
            "count": item["count"],
            "path": item["path"],
            "fileExists": file_exists(item["path"]),
            "detail": f"未执行（--dry-run，动作：{action}）",
        }

    method = "GET" if mode == "healthcheck" else "PUT"
    if mode == "healthcheck":
        path = f"/providers/proxies/{urllib.parse.quote(item['name'], safe='')}/healthcheck"
    else:
        path = provider_api_path(item["kind"], item["name"])

    started = time.perf_counter()
    status, _ = request_json(base, path, headers, timeout=timeout, method=method)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    after: datetime | None = None
    count = item["count"]
    detail = "已受理"
    if mode == "update":
        by_key, _ = build_catalog(base, headers, provider_config, home_dir)
        refreshed = by_key.get((item["kind"], item["name"]))
        if refreshed:
            after = refreshed["updatedAt"]
            count = refreshed["count"]
        if after and before and after > before:
            delta = f"数量 {item['count']} → {count}" if count != item["count"] else "数量不变"
            detail = f"已生效（{delta}）"
        elif after:
            detail = "接口返回成功，但 updatedAt 未前进，检查内核日志"
    else:
        detail = "已受理，测速结果异步产生"

    return {
        "name": item["name"],
        "kind": item["kind"],
        "mode": mode,
        "status": f"HTTP {status} / {elapsed_ms}ms",
        "before": time_text(before),
        "after": time_text(after),
        "count": count,
        "path": item["path"],
        "fileExists": file_exists(item["path"]),
        "detail": detail,
    }


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    args = build_parser().parse_args(argv)

    if args.timeout <= 0:
        print("参数错误：--timeout 必须大于 0", file=sys.stderr)
        return EXIT_USAGE
    if args.all and args.targets:
        print(
            "参数错误：--all 与位置参数不能同时使用；批量用 --all --yes，单目标直接写名称",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.all and args.mode == "healthcheck":
        print(
            "参数错误：--all 与 --mode healthcheck 不能同时使用，请显式指定代理 provider 名称",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if args.all and not args.yes and not args.dry_run:
        print(
            "参数错误：--all 属于批量写操作，需同时给 --yes，或先用 --dry-run 预览",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if not args.all and not args.targets:
        print("参数错误：请给出 provider 名称，或使用 --all --yes", file=sys.stderr)
        return EXIT_USAGE

    try:
        base = api_base(args.api)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    headers = api_headers(args.secret)

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

    try:
        by_key, by_name = build_catalog(base, headers, provider_config, home_dir)
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR

    try:
        if args.all:
            items = [
                item
                for item in by_key.values()
                if item["vehicle"] == "HTTP" and (args.kind == "auto" or item["kind"] == args.kind)
            ]
            items.sort(key=lambda item: (item["kind"], item["name"]))
            skipped = [item for item in by_key.values() if item["vehicle"] != "HTTP"]
            if skipped:
                names = ", ".join(item["name"] for item in skipped)
                print(f"提示：跳过 {len(skipped)} 个非 HTTP provider（不联网更新）：{names}", file=sys.stderr)
            if not items:
                print(f"提示：--all --kind {args.kind} 没有匹配到任何 HTTP provider", file=sys.stderr)
        else:
            items = resolve_targets(by_name, args.targets, args.kind, args.mode)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    if not items:
        print("没有匹配的目标，未执行任何操作", file=sys.stderr)
        return EXIT_USAGE

    results: list[dict[str, Any]] = []
    failed = 0
    for item in items:
        try:
            results.append(
                invoke_target(
                    base,
                    headers,
                    item,
                    args.mode,
                    args.timeout,
                    provider_config,
                    home_dir,
                    args.dry_run,
                )
            )
        except ApiError as exc:
            failed += 1
            results.append(
                {
                    "name": item["name"],
                    "kind": item["kind"],
                    "mode": args.mode,
                    "status": "failed",
                    "before": time_text(item["updatedAt"]),
                    "after": "",
                    "count": item["count"],
                    "path": item["path"],
                    "fileExists": file_exists(item["path"]),
                    "detail": str(exc),
                }
            )

    if args.json:
        print(
            to_json(
                {
                    "api": base,
                    "mode": args.mode,
                    "homeDir": home_dir,
                    "configPath": config_path,
                    "results": results,
                    "failed": failed,
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
            print(format_blocks(results, DETAIL_FIELDS))
        else:
            print(f"mihomo provider {args.mode}（{base}）")
            if args.list:
                print(format_blocks(results, DETAIL_FIELDS))
            else:
                print(
                    format_table(
                        ("name", "kind", "mode", "status", "before", "after", "count", "detail"),
                        (
                            (
                                row["name"],
                                row["kind"],
                                row["mode"],
                                row["status"],
                                row["before"],
                                row["after"],
                                row["count"],
                                row["detail"],
                            )
                            for row in results
                        ),
                    )
                )
            ok_count = sum(1 for row in results if row["status"] not in ("failed", "skipped"))
            print(f"完成：{ok_count} 个已处理，{failed} 个失败")

    return EXIT_ERROR if failed else EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
