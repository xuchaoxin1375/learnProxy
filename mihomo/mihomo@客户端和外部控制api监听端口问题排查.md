[toc]

以clash-party(mihomo part)为例,外部控制api端口排查过程中,涉及到了 **Mihomo Core、Clash Party GUI、External Controller API、代理端口** 四者的关系。



### 现象

配置：

```yaml
external-controller: 127.0.0.1:9090
secret: "1"
```

测试：

```bash
curl -H "Authorization: Bearer 1" \
     http://127.0.0.1:9090/version -v
```

返回：

```text
HTTP/1.1 400 Bad Request
```

理论上 `/version` 是 Mihomo 标准 API，应返回 JSON 或认证错误。([MetaCubex](https://wiki.metacubex.one/en/api/))

## 重启内核

修改完端口(确保没有竞争),需要重启mihomo内核,然后重新检查是否生效.

> 对于图形界面的mihomo客户端,通常有重启应用(内核的按钮)

## 进一步排查

------

### 第一步：确认端口是否真的被监听

Windows：

```powershell
netstat -ano | findstr :9090
```

结果：

```text
TCP    0.0.0.0:9090    LISTENING    16764
```

说明：

- 9090 确实有程序监听
- 不是连接被防火墙阻断
- 不是 Connection Refused

------

### 第二步：确认监听进程是谁

```powershell
tasklist /fi "PID eq 16764"
```

结果：

```text
mihomo.exe
```

说明：

- 监听者确实是 Mihomo
- 不是其它软件占用了 9090

------

### 第三步：确认 Mihomo 启动参数

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId=16764" | Select-Object CommandLine
```

结果：

```text
mihomo.exe
-d C:\...\work
-ext-ctl-pipe \\.\pipe\MihomoParty\...
```

这里发现了一个重要信息：

```text
-ext-ctl-pipe
```

Mihomo 支持：

| 接口类型           | 配置                       |
| ------------------ | -------------------------- |
| HTTP API           | `external-controller`      |
| HTTPS API          | `external-controller-tls`  |
| Unix Socket        | `external-controller-unix` |
| Windows Named Pipe | `external-controller-pipe` |

Windows Named Pipe 是官方支持的控制接口。([MetaCubex](https://wiki.metacubex.one/en/config/general/))

------

### 第四步：确认客户端对应的实际配置文件(config.yaml)

根据相关进程的命令行中,找到mihomo进程的运行目录：

```text
C:\scoop\apps\clash-party\current\data\work
```

检查：

```powershell
findstr /i "external-controller" config.yaml
```

结果：

```yaml
external-controller: 127.0.0.1:9090
```

继续检查：

```powershell
findstr /i "secret:" config.yaml
```

结果：

```yaml
secret: "1"
```

说明：

- HTTP API 已配置
- Secret 配置正确
- 配置文件本身没有问题

------

### 第五步：验证是否访问错了端口

后来将：

```yaml
external-controller: 127.0.0.1:9090
```

修改为 9091（原来写的是 9090，这才是 9091 端口也出现监听的原因）。

重启 Mihomo 后：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 9090,9091 | Select-Object LocalPort, OwningProcess
```

结果：

```text
9090 -> LISTENING
9091 -> LISTENING
```

而且：

```text
PID 相同
mihomo.exe
```

这是整个排查中的关键转折点。

如果：

```text
9090 = external-controller
```

那么修改到 9091 后：

```text
9090 应该消失
```

但实际没有。

因此推断：

```text
9090 ≠ external-controller
```

而是另一个监听器。

------

### 第六步：发现真正的 API 端口

测试：

```bash
curl -H "Authorization: Bearer 1" \
     http://127.0.0.1:9091/version
```

成功返回。

说明：

```text
9091 = External Controller API
```

最终问题解决。

------

### 根本原因

排查过程中最大的误区是：

```text
看到 9090 在监听
↓
认为它就是 API
↓
不断访问 9090
↓
得到 400
```

实际上：

```text
9090 是其它 Mihomo Listener
9091 才是 External Controller
```

Mihomo 可以同时监听多个端口，例如：

```yaml
mixed-port: 9090

external-controller: 127.0.0.1:9091
```

二者完全不同。([Clash Official Website](https://clashsurge.com/en/blog/articles/clash-external-controller-bind-address-secret-2026.html))

------

### Windows 下推荐排查顺序

遇到 Mihomo API 无法访问时：

```powershell
# 1. 查看监听端口
netstat -ano | findstr :9090

# 2. 查看进程
tasklist /fi "PID eq <pid>"

# 3. 查看启动参数
Get-CimInstance Win32_Process -Filter "ProcessId=<pid>" | Select-Object CommandLine

# 4. 查看实际配置
findstr /i "external-controller" config.yaml
findstr /i "secret:" config.yaml

# 5. 验证 API
curl -H "Authorization: Bearer xxx" \
     http://127.0.0.1:<controller-port>/version
```

标准 Mihomo API 示例：

```bash
curl -H "Authorization: Bearer 1" \
     http://127.0.0.1:9091/version
```

其中：

- `/version`：获取版本信息
- `/configs`：获取运行配置
- `/proxies`：获取代理组
- `/connections`：获取连接信息

这些都是官方 REST API 端点。([MetaCubex](https://wiki.metacubex.one/en/api/))

### 本次经验总结

不要根据：

```text
netstat 看到的端口
```

直接判断：

```text
这就是 External Controller
```

应该始终以：

```yaml
external-controller:
```

配置值为准，并用：

```bash
curl ... /version
```

验证。

很多 GUI（如 Clash Party、Clash Verge 等）会同时启用：

- HTTP 代理端口
- SOCKS 代理端口
- Mixed Port
- TUN
- Named Pipe
- External Controller

因此单纯看到端口监听，并不能说明它就是 REST API。([MetaCubex](https://wiki.metacubex.one/en/config/general/))