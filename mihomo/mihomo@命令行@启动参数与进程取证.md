[toc]

## 命令行程序的运行模型

`mihomo` 启动时通常会读取一个**工作目录**和一个 **YAML 配置文件**。

源码中默认配置目录是类 Unix 和 Windows 下的用户目录 `.config/mihomo`，默认配置文件名是 `config.yaml`；如果设置了 `XDG_CONFIG_HOME`，也会参与目录选择。([GitHub](https://raw.githubusercontent.com/MetaCubeX/mihomo/Alpha/constant/path.go))

常见启动方式如下：

```bash
mihomo
```

这会尝试使用默认配置目录中的默认配置文件。

```bash
mihomo -d /etc/mihomo
```

这会把 `/etc/mihomo` 作为工作目录，默认读取其中的 `config.yaml`。官方 systemd 示例也使用了 `ExecStart=/usr/local/bin/mihomo -d /etc/mihomo`。([虚空终端](https://wiki.metacubex.one/en/startup/service/))

```bash
mihomo -d /etc/mihomo -f /etc/mihomo/config.yaml
```

这会显式指定工作目录和配置文件。

```bash
mihomo -t -d /etc/mihomo
```

这会测试配置是否能解析成功，然后退出。

源码中的启动参数包含 `-d` 配置目录、`-f` 配置文件、`-config` base64 配置字符串、`-v` 显示版本、`-t` 测试配置、`-m` geodata mode、`-ext-ui`、`-ext-ctl`、`-secret`、`-post-up`、`-post-down` 等。([GitHub](https://raw.githubusercontent.com/MetaCubeX/mihomo/Alpha/main.go))

```bash
mihomo -v
```

显示当前 mihomo 版本、系统架构、Go 版本和构建时间。这个信息对排错很重要，因为很多配置项和协议支持会随版本变化。

## 常用命令参数

| 参数              | 作用                         | 新手建议                           |
| ----------------- | ---------------------------- | ---------------------------------- |
| `-d`              | 指定 HomeDir，也就是工作目录 | Linux 服务部署时常用 `/etc/mihomo` |
| `-f`              | 指定配置文件                 | 多配置测试时很有用                 |
| `-t`              | 测试配置并退出               | 每次修改配置后先跑它               |
| `-v`              | 显示版本                     | 排错时先贴版本                     |
| `-m`              | 强制使用 geodata（`.dat`）模式 | 与 `geodata-mode: true` 等价，一般不用动 |
| `-config`         | 传入 base64 编码配置         | 脚本、容器场景可能用到             |
| `-age-secret-key` | 解密 age 加密配置            | 高级订阅/安全配置场景              |
| `-ext-ui`         | 覆盖外部 UI 目录             | 临时指定 Dashboard 文件目录        |
| `-ext-ctl`        | 覆盖 API 监听地址            | 调试面板时常用                     |
| `-secret`         | 覆盖 API secret              | 不要留空暴露给局域网或公网         |
| `-ext-ctl-pipe`   | 指定命名管道 API             | GUI 客户端常用；pipe 不校验 secret |
| `-ext-ctl-unix`   | 指定 Unix socket API         | Linux/macOS 本机控制               |
| `-ext-ctl-tls`    | 为 API 启用 TLS              | 跨机访问且要加密时使用             |
| `-f -`            | 从标准输入读取配置           | 容器、临时验证                     |
| `-post-up`        | 启动后执行脚本               | 路由器、iptables 场景可能用        |
| `-post-down`      | 退出前执行脚本               | 清理路由或防火墙规则时可能用       |

## 安装与目录规划

官方文档建议从 Releases 下载对应系统和架构的预编译二进制文件；systemd 部署示例则建议把二进制重命名为 `mihomo`，移动到 `/usr/local/bin/`，并把配置放到 `/etc/mihomo`。([虚空终端](https://wiki.metacubex.one/en/startup/))

推荐新手采用下面这种目录：

```text
/usr/local/bin/mihomo
/etc/mihomo/config.yaml
/etc/mihomo/proxy_providers/
/etc/mihomo/rule_providers/
/etc/mihomo/ui/
/etc/systemd/system/mihomo.service
```

这样做的好处是：程序、主配置、订阅缓存、规则集、面板文件和系统服务各自分离，后续维护不会混乱。

Linux 上可以按这个流程跑：

```bash
sudo install -m 755 mihomo /usr/local/bin/mihomo
sudo mkdir -p /etc/mihomo
sudo cp config.yaml /etc/mihomo/config.yaml
mihomo -t -d /etc/mihomo
sudo /usr/local/bin/mihomo -d /etc/mihomo
```

配置通过测试后，再考虑做成 systemd 服务。

官方文档给出的 systemd 示例包含复制二进制、复制配置、创建 `/etc/systemd/system/mihomo.service`、`systemctl daemon-reload`、`systemctl enable mihomo`、`systemctl start mihomo`、`systemctl reload mihomo`、`journalctl -u mihomo` 查看日志等步骤。([虚空终端](https://wiki.metacubex.one/en/startup/service/))

## mihomo的图形客户端的核心进程信息

以windows系统为例,分析mihomo客户端(以clash-verge-rev)为例,说明客户端是如何启动的mihomo进程.

> 这里使用powershell来获取mihomo相关进程信息(假设mihomo已经启动并处于正常工作状态.)

```powershell
# 列出完整的mihomo进程信息
ps *mihomo*|select *
```

> 不同的mihomo GUI客户端可能会模块mihomo可执行文件的名称.这里使用通配符,提高匹配成功率

```shell
# 获取我们最感兴趣的信息
ps *mihomo*|select Id,Name,ProcessName,Path,CommandLine,StartTime

# output example
Id          : 20288
Name        : verge-mihomo
ProcessName : verge-mihomo
Path        : C:\scoop\apps\clash-verge-rev\2.5.1\verge-mihomo.exe
CommandLine : "\\?\C:\scoop\apps\clash-verge-rev\2.5.1\verge-mihomo.exe" -d C:\Users\<user>\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev -f C:\Users\<user>\AppData\Roaming\io.github.clash-verge-rev.clash-ve
              rge-rev\clash-verge.yaml -ext-ctl-pipe \\.\pipe\verge-mihomo
StartTime   : 2026/7/8 17:16:26
```

查看版本信息:

```shell
#Admin[pwsh][Administrator@CXXUDESK][C:\scoop\apps\clash-verge-rev\current][10:56:57]
 .\verge-mihomo.exe -v
Mihomo Meta v1.19.25 windows amd64 with go1.26.3 Sat May 16 15:18:49 UTC 2026
Use tags: with_gvisor
```

命令行的选项功能不多,重点在于运行后对外提供api能力.

## 总结

mihomo 的学习核心不是背字段，而是理解这条链路：**应用流量进入 Inbound，DNS 和 Sniffer 帮助识别目标，Rules 决定策略，Proxy Group 选择节点，Proxy 完成出站，API 和 Dashboard 负责观察与控制**。只要按这条链路排查和设计配置，新手也能逐步搭出稳定、清晰、可维护的 mihomo 命令行运行环境。
