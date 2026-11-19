[toc]



## 验证mihomo工作状态

mihomo命令行用户验证 mihomo 是否正确运行，不只看“进程在不在”，而要分层确认：

| 层面   | 要验证什么                      | 常用工具                                 |
| ------ | ------------------------------- | ---------------------------------------- |
| 配置层 | YAML 能否解析、Geo 数据是否齐全 | `mihomo -t`                              |
| 进程层 | mihomo 是否真的启动             | `ps`、`pgrep`、`systemctl`               |
| 端口层 | HTTP/SOCKS/API/DNS 端口是否监听 | `ss`、`lsof`                             |
| 代理层 | 通过代理能否访问网站            | `curl -x`                                |
| DNS 层 | 内置 DNS 是否工作               | `dig`、`nslookup`                        |
| 规则层 | 流量是否按规则走                | API、Dashboard、日志                     |
| 服务层 | systemd 是否稳定托管            | `systemctl`、`journalctl`                |
| 网络层 | TUN、路由、防火墙是否正常       | `ip route`、`ip addr`、`nft`、`iptables` |

官方文档推荐 Linux 下使用 systemd 托管 mihomo，并用 `systemctl status mihomo`、`journalctl -u mihomo` 查看服务状态和日志。([Metacubex](https://wiki.metacubex.one/en/startup/service/))

## 最小验证流程

假设你的配置是：

```bash
mihomo -d ~/.config/mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
```

### 基础测试

```bash
mihomo -t -d ~/.config/mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
```

如果配置通过，再前台运行：

```bash
mihomo -d ~/.config/mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
```

另开一个终端检查端口：

```bash
sudo ss -lntp | grep mihomo   # -p 需要 root 才能看到进程名
```

测试代理端口，假设 `mixed-port: 7890`：

```bash
curl -I -x http://127.0.0.1:7890 https://www.google.com
```

### api测试(可选)

如果配置了 API，例如：

```yaml
external-controller: 127.0.0.1:9090
secret: "your_secret"
```

测试 API：(假设api服务端口是9090)

```bash
your_secret=""
curl -H "Authorization: Bearer $your_secret" http://127.0.0.1:9090/version
```

mihomo 官方 API 文档说明，请求 API 时使用 `Authorization: Bearer ${secret}` 认证；

API 包括日志、流量、配置、代理、规则、连接、DNS 查询等接口。([Metacubex](https://wiki.metacubex.one/en/api/))

## 配置是否正确

先跑配置测试：

```bash
mihomo -t -d ~/.config/mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
```

常见结果：

| 输出                        | 含义                               |
| --------------------------- | ---------------------------------- |
| 没有 `fatal error`          | 配置基本能解析                     |
| `Parse config error`        | YAML、规则、节点、Geo 数据等有问题 |
| `can't download MMDB`       | 本地 GeoIP 数据缺失，自动下载失败  |
| `proxy group ... not found` | 规则引用了不存在的策略组           |
| `rule provider ... error`   | 规则集加载失败                     |
| `proxy provider ... error`  | 节点订阅加载失败                   |

你的前一个错误就是配置层失败，不是端口层或代理层失败。

## 进程是否启动

前台运行时，你会直接看到日志。后台或服务运行时，用：

```bash
pgrep -a mihomo
```

或者：

```bash
ps aux | grep '[m]ihomo'
```

如果是 systemd：

```bash
systemctl status mihomo
```

官方 systemd 示例里，mihomo 服务通常用：

```ini
ExecStart=/usr/local/bin/mihomo -d /etc/mihomo
ExecReload=/bin/kill -HUP $MAINPID
```

并通过 `systemctl enable`、`systemctl start`、`systemctl reload`、`systemctl status` 管理。([Metacubex](https://wiki.metacubex.one/en/startup/service/))

## 端口是否监听

先看配置里有哪些端口：

```bash
grep -E '(mixed-port|port|socks-port|redir-port|tproxy-port|external-controller):' ~/.config/mihomo/myprofiles/default.generated.yaml
```

再看系统监听：

```bash
sudo ss -lntp | grep mihomo   # -p 需要 root 才能看到进程名
```

或者：

```bash
lsof -i -P -n | grep mihomo
```

常见端口：

| 端口          | 作用                                 |
| ------------- | ------------------------------------ |
| `7890`        | 常见 mixed-port，HTTP/SOCKS 混合代理 |
| `7891`        | 常见 HTTP 或 SOCKS 端口，取决于配置  |
| `9090`        | 常见 external-controller API         |
| `1053`        | 常见内置 DNS 监听端口                |
| `redir-port`  | Linux 透明代理 TCP 入口              |
| `tproxy-port` | Linux TProxy 入口                    |

如果 `curl -x` 失败，先确认 `mixed-port` 是否真的监听在 `127.0.0.1:7890`。

### 案例分析(bind: address already in use)

```shell
sudo journalctl -u mihomo -o cat -f
time="2026-07-12T12:44:18.759856550+08:00" level=error msg="Start Mixed(http+socks) server error: listen tcp :7897: bind: address already in use"

```

这是 **7897 端口已被其他进程占用**。

> 如果是在wsl系统中运行的,请检查windows主机上是否运行类似的程序占用了该端口.
>
> 如果是windows系统占用了该端口,在wsl系统中可能检测不到是哪个程序占用的,请务必注意.

先找出占用者：

```bash
sudo ss -lntp | grep ':7897'
```

也可以：

```bash
sudo lsof -nP -iTCP:7897 -sTCP:LISTEN
sudo fuser -v 7897/tcp
```

### 常见处理方式

**1. 已有另一个 mihomo 实例在运行**

```bash
pgrep -a mihomo
systemctl status mihomo
```

若之前手动启动过 mihomo，结束多余实例：

```bash
sudo pkill mihomo
sudo systemctl restart mihomo
```

注意：执行 `pkill` 会终止所有 mihomo 进程。更稳妥的是根据 `ss` 查到的 PID 单独结束：

```bash
sudo kill <PID>
```

**2. 有两个 systemd 服务同时启动 mihomo**

检查相关服务：

```bash
systemctl list-units --type=service | grep -Ei 'mihomo|clash'
```

例如发现 `clash.service` 也占用了端口：

```bash
sudo systemctl disable --now clash
sudo systemctl restart mihomo
```

**3. 配置文件里重复监听 7897**

检查配置：

```bash
grep -RniE 'mixed-port|port:|socks-port|7897' /etc/mihomo /root/.config/mihomo 2>/dev/null
```

典型配置应避免端口重复，例如：

```yaml
mixed-port: 7897
```

不要再同时配置：

```yaml
port: 7897
socks-port: 7897
```

如果 7897 必须留给其他程序，可以把 Mihomo 改为：

```yaml
mixed-port: 7898
```

然后验证并重启：

```bash
mihomo -t -d /etc/mihomo
sudo systemctl restart mihomo
sudo journalctl -u mihomo -o cat -n 50
```

最可能的快速处理顺序是：

```bash
sudo ss -lntp | grep ':7897'
pgrep -a mihomo
sudo systemctl restart mihomo
```

## 代理是否可用

假设配置中有：

```yaml
mixed-port: 7890
```

测试 HTTP 代理：

```bash
curl -I -x http://127.0.0.1:7890 https://www.example.com
```

测试能否看到出口 IP：

```bash
curl -x http://127.0.0.1:7890 https://api.ipify.org
```

测试直连出口 IP：

```bash
curl https://api.ipify.org
```

如果两个 IP 不同，说明代理路径大概率生效。

也可以测试 SOCKS5：

```bash
curl -I --socks5 127.0.0.1:7890 https://www.example.com
```

如果 mixed-port 正常，HTTP 和 SOCKS 都应该能用。

## API 是否可用

配置里需要有类似：

```yaml
external-controller: 127.0.0.1:9090
secret: "your-secret"
```

测试版本：

```bash
curl -H "Authorization: Bearer your-secret" http://127.0.0.1:9090/version
```

查看代理组：

```bash
curl -H "Authorization: Bearer your-secret" http://127.0.0.1:9090/proxies
```

查看规则：

```bash
curl -H "Authorization: Bearer your-secret" http://127.0.0.1:9090/rules
```

查看当前连接：

```bash
curl -H "Authorization: Bearer your-secret" http://127.0.0.1:9090/connections
```

官方 API 文档列出了 `/logs`、`/traffic`、`/version`、`/configs`、`/proxies`、`/rules`、`/connections`、`/dns/query` 等接口。([Metacubex](https://wiki.metacubex.one/en/api/))

## 实时日志怎么看

如果你是前台运行：

```bash
mihomo -d ~/.config/mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
```

日志直接显示在终端。

如果你用 systemd：

```bash
journalctl -u mihomo -f
```

查看最近 100 行：

```bash
journalctl -u mihomo -n 100 --no-pager
```

只看本次启动以来：

```bash
journalctl -u mihomo -b --no-pager
```

持续跟踪并去掉多余字段：

```bash
journalctl -u mihomo -o cat -f
```

官方服务文档也给出了使用 `journalctl -u mihomo -o cat -e` 和 `journalctl -u mihomo -o cat -f` 查看日志的方式。([Metacubex](https://wiki.metacubex.one/en/startup/service/))

## API 实时日志

如果 API 开启，可以用：

```bash
curl -N -H "Authorization: Bearer your-secret" \
  "http://127.0.0.1:9090/logs?level=info"
```

排错时改成：

```bash
curl -N -H "Authorization: Bearer your-secret" \
  "http://127.0.0.1:9090/logs?level=debug"
```

配置里也可以临时调日志等级：

```yaml
log-level: debug
```

日常建议：

```yaml
log-level: info
```

`debug` 信息很多，适合短时间排错，不建议长期打开。

## DNS 是否正常

如果你的配置里有：

```yaml
dns:
  enable: true
  listen: 127.0.0.1:1053
```

可以测试：

```bash
dig @127.0.0.1 -p 1053 www.example.com
```

或者：

```bash
nslookup www.example.com 127.0.0.1
```

如果你使用 fake-ip，查询结果可能是 `198.18.0.0/16` 一类虚拟地址，这是正常现象。

DNS 排错重点：

| 现象                | 可能原因                        |
| ------------------- | ------------------------------- |
| 节点全超时          | 代理服务器域名解析失败          |
| `GEOIP` 规则报错    | GeoIP / MMDB 缺失               |
| 国内网站异常慢      | 国内域名解析或规则分流不对      |
| 局域网域名打不开    | fake-ip 没过滤 `.lan`、`.local` |
| TUN 开启后 DNS 异常 | `dns-hijack` 或系统 DNS 冲突    |

## 规则是否命中

最直接的方法是看日志或 API 连接信息。

打开 debug：

```yaml
log-level: debug
```

然后访问一个网站：

```bash
curl -I -x http://127.0.0.1:7890 https://www.example.com
```

同时看日志：

```bash
journalctl -u mihomo -o cat -f
```

如果 API 可用，也可以：

```bash
curl -H "Authorization: Bearer your-secret" http://127.0.0.1:9090/connections
```

你要重点看：

| 字段          | 意义                    |
| ------------- | ----------------------- |
| 目标域名 / IP | mihomo 识别到的连接目标 |
| 规则          | 命中了哪条 rule         |
| 策略组        | 走了哪个 proxy group    |
| 实际节点      | 最终走哪个 proxy        |
| 上传 / 下载   | 是否真的有流量          |

## TUN 是否正常

如果配置里启用了：

```yaml
tun:
  enable: true
```

检查虚拟网卡：

```bash
ip addr
```

查看路由：

```bash
ip route
```

查看规则路由：

```bash
ip rule
```

测试普通系统流量是否被接管：

```bash
curl https://api.ipify.org
```

如果不开 `curl -x`，出口 IP 也变成代理出口，说明 TUN 大概率生效。

TUN 失败常见原因：

| 问题                | 检查点                                         |
| ------------------- | ---------------------------------------------- |
| 没有权限            | 是否 root 运行，systemd 是否有 `CAP_NET_ADMIN` |
| 开启后断网          | `auto-route`、`dns-hijack`、`strict-route`     |
| 局域网打不开        | 私有网段是否被排除或直连                       |
| Docker / 虚拟机异常 | TUN 路由和虚拟网卡冲突                         |
| DNS 不工作          | `dns.listen`、`dns-hijack`、系统 DNS           |

## systemd 推荐方式

Linux 主机长期运行，建议用 systemd。[创建运行服务 - 虚空终端 Docs](https://wiki.metacubex.one/startup/service/)

服务文件示例：

```ini
[Unit]
Description=mihomo Daemon
After=network.target NetworkManager.service systemd-networkd.service

[Service]
Type=simple
User=root
Restart=on-failure
ExecStart=/usr/local/bin/mihomo -d /etc/mihomo -f /etc/mihomo/config.yaml
ExecReload=/bin/kill -HUP $MAINPID
LimitNPROC=500
LimitNOFILE=1000000
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable mihomo
sudo systemctl start mihomo
```

查看：

```bash
systemctl status mihomo
journalctl -u mihomo -o cat -f
```

官方文档的 systemd 示例同样使用 `/usr/local/bin/mihomo -d /etc/mihomo`，并给出 enable、start、reload、status、journalctl 等管理方式。([Metacubex](https://wiki.metacubex.one/en/startup/service/))

## Linux 一键体检脚本思路

可以写一个简单脚本：

```bash
#!/usr/bin/env bash

set -e

CONFIG_DIR="${1:-$HOME/.config/mihomo}"
CONFIG_FILE="${2:-$CONFIG_DIR/config.yaml}"
PROXY_PORT="${3:-7890}"
API_PORT="${4:-9090}"

echo "[1] version"
mihomo -v || true

echo "[2] config test"
mihomo -t -d "$CONFIG_DIR" -f "$CONFIG_FILE"

echo "[3] process"
pgrep -a mihomo || true

echo "[4] ports"
sudo ss -lntp | grep -E "mihomo|:$PROXY_PORT|:$API_PORT" || true

echo "[5] proxy test"
curl -I --max-time 10 -x "http://127.0.0.1:$PROXY_PORT" https://www.example.com || true

echo "[6] direct ip"
curl --max-time 10 https://api.ipify.org || true
echo

echo "[7] proxy ip"
curl --max-time 10 -x "http://127.0.0.1:$PROXY_PORT" https://api.ipify.org || true
echo
```

用法：

```bash
chmod +x check-mihomo.sh
./check-mihomo.sh ~/.config/mihomo ~/.config/mihomo/myprofiles/default.generated.yaml 7890 9090
```

## macOS 验证

macOS 上整体类似：

```bash
pgrep -a mihomo
lsof -iTCP -sTCP:LISTEN -n -P | grep mihomo
curl -I -x http://127.0.0.1:7890 https://www.example.com
```

如果用 launchd 托管：

```bash
launchctl list | grep mihomo
```

日志取决于你怎么启动。如果是前台运行，就看终端；如果是 launchd，要看 plist 里配置的 stdout/stderr 日志路径，或者用 Console.app / `log stream` 辅助排查。

macOS 开 TUN / utun 时，还要看：

```bash
ifconfig
netstat -rn
```

## Windows 命令行验证

PowerShell 查看进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -like "*mihomo*" } |
  Select-Object ProcessId,Name,ExecutablePath,CommandLine
```

查看端口：

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 7890,9090 }
```

测试代理：

```powershell
curl.exe -I -x http://127.0.0.1:7890 https://www.example.com
```

测试 API：

```powershell
curl.exe -H "Authorization: Bearer your-secret" http://127.0.0.1:9090/version
```

如果是 Clash Verge Rev 这类 GUI，可能通过 Named Pipe 控制 mihomo，而不是暴露普通 `127.0.0.1:9090` API；这时要看进程命令行里有没有 `-ext-ctl-pipe`。

## 判断“正确运行”的标准

可以按这个标准判断：

| 标准               | 判断命令                                                     |
| ------------------ | ------------------------------------------------------------ |
| 配置能解析         | `mihomo -t -d ... -f ...`                                    |
| 进程存在           | `pgrep -a mihomo`                                            |
| 代理端口监听       | `ss -lntp \| grep 7890`                                      |
| curl 代理成功      | `curl -x http://127.0.0.1:7890 https://www.example.com`      |
| API 可访问         | `curl -H "Authorization: Bearer secret" http://127.0.0.1:9090/version` |
| 日志无 fatal/error | `journalctl -u mihomo -f`                                    |
| 规则命中符合预期   | `/connections`、`/rules`、debug 日志                         |
| DNS 正常           | `dig @127.0.0.1 -p 1053 example.com`                         |
| TUN 正常           | 不加 `-x` 的 `curl` 也能按规则走代理                         |

最实用的日常顺序是：

```bash
mihomo -t -d ~/.config/mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
pgrep -a mihomo
sudo ss -lntp | grep mihomo   # -p 需要 root 才能看到进程名
curl -I -x http://127.0.0.1:7890 https://www.example.com
journalctl -u mihomo -o cat -f
```

这五步基本能覆盖 80% 的命令行排错场景。