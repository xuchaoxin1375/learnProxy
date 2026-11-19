#!/usr/bin/env python3
"""管理独立的 mihomo 实例：校验、启动、状态与停止。

用于在同一台机器上额外运行一个 mihomo 内核。例如 Clash Verge 继续跑
171xx 的 round-robin，本脚本管理的实例跑 172xx/173xx 的粘性配置。

脚本只操作自己通过 PID 文件记录的进程，不按进程名或端口批量清理。

用法（Linux/macOS）: python3 mihomo_instance.py --help
用法（Windows）   : python mihomo_instance.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
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

START_WAIT_SECONDS = 1.5
STOP_WAIT_SECONDS = 5.0


class InstanceError(Exception):
    """实例管理中的可预期错误。"""


class ArgumentParser(argparse.ArgumentParser):
    """参数错误统一返回 2。"""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"参数错误：{message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def resolve_config(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise InstanceError(f"配置文件不存在: {path}")
    return path


def resolve_home(raw: str | None, config: Path) -> Path:
    home = Path(raw).expanduser().resolve() if raw else config.parent
    home.mkdir(parents=True, exist_ok=True)
    return home


def resolve_pid_file(raw: str | None, home: Path) -> Path:
    return Path(raw).expanduser().resolve() if raw else home / "mihomo.pid"


def resolve_log(raw: str | None, home: Path) -> Path:
    return Path(raw).expanduser().resolve() if raw else home / "mihomo.log"


def resolve_pid_file_arg(raw_pid_file: str | None, raw_home: str | None) -> Path:
    if raw_pid_file:
        return Path(raw_pid_file).expanduser().resolve()
    if raw_home:
        return Path(raw_home).expanduser().resolve() / "mihomo.pid"
    raise InstanceError("stop/status 需要 --pid-file 或 --home")


def find_mihomo(explicit: str | None) -> str:
    candidate = (explicit or os.environ.get("MIHOMO_BIN", "")).strip()
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path.resolve())
        raise InstanceError(f"mihomo 可执行文件不存在: {path}")
    for name in ("mihomo", "verge-mihomo"):
        found = shutil.which(name)
        if found:
            return found
    raise InstanceError(
        "找不到 mihomo 可执行文件；用 --mihomo 指定，或设置 MIHOMO_BIN。"
        "Windows 常见位置：C:\\Program Files\\Clash Verge\\verge-mihomo.exe"
    )


def read_pid_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstanceError(f"PID 文件无法解析: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("pid"), int):
        raise InstanceError(f"PID 文件缺少有效 pid: {path}")
    return data


def write_pid_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def remove_pid_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=False,
        )
        text = decode_output(result.stdout)
        return str(pid) in text
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_command_line(pid: int) -> str | None:
    if os.name == "nt":
        command = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        text = decode_output(result.stdout).strip()
        return text or None

    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.is_file():
        try:
            raw = proc_cmdline.read_bytes()
        except OSError:
            return None
        text = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        return text or None
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    text = decode_output(result.stdout).strip()
    return text or None


def command_matches(cmdline: str, config: Path, home: Path) -> bool:
    text = os.path.normcase(cmdline)
    return os.path.normcase(str(config)) in text and os.path.normcase(str(home)) in text


def instance_command(mihomo: str, home: Path, config: Path) -> list[str]:
    return [mihomo, "-d", str(home), "-f", str(config)]


def print_tail(path: Path, lines: int = 20) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    tail = text.splitlines()[-lines:]
    if tail:
        print("--- 日志末尾 ---", file=sys.stderr)
        print("\n".join(tail), file=sys.stderr)


def run_validate(mihomo: str, home: Path, config: Path) -> int:
    command = [mihomo, "-t", "-d", str(home), "-f", str(config)]
    print(f"[校验] {' '.join(command)}", file=sys.stderr)
    result = subprocess.run(command, capture_output=True, check=False)
    stdout = decode_output(result.stdout)
    stderr = decode_output(result.stderr)
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)
    return result.returncode


def cmd_validate(args: argparse.Namespace) -> int:
    config = resolve_config(args.config)
    home = resolve_home(args.home, config)
    mihomo = find_mihomo(args.mihomo)
    return EXIT_OK if run_validate(mihomo, home, config) == 0 else EXIT_ERROR


def cmd_start(args: argparse.Namespace) -> int:
    config = resolve_config(args.config)
    home = resolve_home(args.home, config)
    pid_file = resolve_pid_file(args.pid_file, home)
    log_file = resolve_log(args.log, home)

    existing = read_pid_file(pid_file)
    if existing:
        pid = existing["pid"]
        if process_alive(pid):
            print(f"已在运行: PID {pid} ({pid_file})")
            return EXIT_OK
        print(f"清理过期 PID 文件: {pid_file}", file=sys.stderr)
        remove_pid_file(pid_file)

    mihomo = find_mihomo(args.mihomo)
    command = instance_command(mihomo, home, config)
    if args.dry_run:
        print(" ".join(command))
        print(f"PID 文件: {pid_file}")
        print(f"日志: {log_file}")
        return EXIT_OK

    if run_validate(mihomo, home, config) != 0:
        print("配置校验失败，未启动", file=sys.stderr)
        return EXIT_ERROR

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("ab") as log_handle:
        log_handle.write(f"\n===== {timestamp()} start =====\n".encode())
        log_handle.flush()
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "cwd": str(home),
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)

    time.sleep(START_WAIT_SECONDS)
    exit_code = process.poll()
    if exit_code is not None:
        print(f"启动失败，进程已退出（code={exit_code}）", file=sys.stderr)
        print_tail(log_file)
        return EXIT_ERROR

    write_pid_file(
        pid_file,
        {
            "version": 1,
            "pid": process.pid,
            "home": str(home),
            "config": str(config),
            "started_at": timestamp(),
            "log": str(log_file),
        },
    )
    print(f"已启动: PID {process.pid}")
    print(f"配置: {config}")
    print(f"工作目录: {home}")
    print(f"日志: {log_file}")
    print(f"PID 文件: {pid_file}")
    return EXIT_OK


def cmd_stop(args: argparse.Namespace) -> int:
    pid_file = resolve_pid_file_arg(args.pid_file, args.home)
    data = read_pid_file(pid_file)
    if not data:
        print(f"未运行: 没有 PID 文件 {pid_file}")
        return EXIT_OK

    pid = data["pid"]
    if not process_alive(pid):
        print(f"未运行: PID {pid} 已退出，清理 PID 文件")
        remove_pid_file(pid_file)
        return EXIT_OK

    config = Path(str(data.get("config", ""))).expanduser()
    home = Path(str(data.get("home", ""))).expanduser()
    cmdline = process_command_line(pid)
    if cmdline is None:
        if not args.force:
            raise InstanceError(
                f"无法读取 PID {pid} 的命令行；确认这是本脚本启动的实例后加 --force"
            )
    elif not command_matches(cmdline, config, home):
        raise InstanceError(
            f"PID {pid} 的命令行与 PID 文件不匹配，拒绝停止；确认后加 --force"
        )

    if args.dry_run:
        print(f"将停止 PID {pid} ({pid_file})")
        return EXIT_OK

    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            text = decode_output(result.stderr or result.stdout).strip()
            raise InstanceError(f"taskkill 失败: {text or result.returncode}")
    else:
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + STOP_WAIT_SECONDS
        while time.time() < deadline and process_alive(pid):
            time.sleep(0.2)
        if process_alive(pid):
            if not args.force:
                raise InstanceError(
                    f"PID {pid} 未在 {STOP_WAIT_SECONDS:g} 秒内退出；确认后加 --force"
                )
            os.kill(pid, signal.SIGKILL)

    remove_pid_file(pid_file)
    print(f"已停止: PID {pid}")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    pid_file = resolve_pid_file_arg(args.pid_file, args.home)
    data = read_pid_file(pid_file)
    running = bool(data and process_alive(data["pid"]))
    info: dict[str, Any] = {
        "running": running,
        "pid_file": str(pid_file),
    }
    if data:
        info.update(
            {
                "pid": data["pid"],
                "config": data.get("config", ""),
                "home": data.get("home", ""),
                "log": data.get("log", ""),
                "started_at": data.get("started_at", ""),
            }
        )
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    elif running:
        print(f"运行中: PID {info['pid']}")
        print(f"配置: {info['config']}")
        print(f"工作目录: {info['home']}")
        print(f"日志: {info['log']}")
    elif data:
        print(f"未运行: PID {info['pid']} 已退出（PID 文件 {pid_file}）")
    else:
        print(f"未运行: 没有 PID 文件 {pid_file}")
    return EXIT_OK if running else EXIT_STATE


def build_parser() -> argparse.ArgumentParser:
    parser = ArgumentParser(
        prog="mihomo_instance.py",
        description=(
            "管理独立的 mihomo 实例：validate / start / status / stop。"
            "只操作脚本自己用 PID 文件记录的进程，不按进程名清理。"
        ),
        epilog=(
            "退出码: 0 成功或运行中；1 错误或校验失败；2 参数错误；"
            "3 status 表示未运行。\n"
            "示例:\n"
            "  python mihomo_instance.py validate --config ./config.yaml --mihomo /path/to/mihomo\n"
            "  python mihomo_instance.py start --config ./config.yaml --home ./runtime --mihomo /path/to/mihomo\n"
            "  python mihomo_instance.py status --home ./runtime\n"
            "  python mihomo_instance.py stop --home ./runtime"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_config_args(p: argparse.ArgumentParser, *, home_required: bool = False) -> None:
        p.add_argument("-c", "--config", required=True, help="mihomo 主配置文件")
        p.add_argument(
            "-d",
            "--home",
            required=home_required,
            help=(
                "mihomo -d 工作目录；start 必填，validate 省略时用配置文件所在目录"
            ),
        )
        p.add_argument(
            "-m",
            "--mihomo",
            help="mihomo 可执行文件；省略时读 MIHOMO_BIN 或在 PATH 中查找",
        )

    p_validate = sub.add_parser("validate", help="只跑 mihomo -t，不启动")
    add_config_args(p_validate)

    p_start = sub.add_parser("start", help="校验后后台启动，并写 PID 文件")
    add_config_args(p_start, home_required=True)
    p_start.add_argument("--pid-file", help="默认 <home>/mihomo.pid")
    p_start.add_argument("--log", help="默认 <home>/mihomo.log")
    p_start.add_argument("--dry-run", action="store_true", help="只打印命令，不校验、不启动")

    p_stop = sub.add_parser("stop", help="停止 PID 文件记录的进程")
    p_stop.add_argument("--pid-file", help="PID 文件；与 --home 二选一")
    p_stop.add_argument("--home", help="工作目录；用它定位 <home>/mihomo.pid")
    p_stop.add_argument("--force", action="store_true", help="跳过命令行核对，或 POSIX 下强杀")
    p_stop.add_argument("--dry-run", action="store_true", help="只打印将停止的 PID")

    p_status = sub.add_parser("status", help="查看 PID 文件与进程状态")
    p_status.add_argument("--pid-file", help="PID 文件；与 --home 二选一")
    p_status.add_argument("--home", help="工作目录；用它定位 <home>/mihomo.pid")
    p_status.add_argument("--json", action="store_true", help="输出 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdout()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            return cmd_validate(args)
        if args.command == "start":
            return cmd_start(args)
        if args.command == "stop":
            return cmd_stop(args)
        if args.command == "status":
            return cmd_status(args)
        raise InstanceError(f"未知命令: {args.command}")
    except InstanceError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
