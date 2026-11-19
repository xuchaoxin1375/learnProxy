[toc]



在无桌面的 Linux 服务器上，“系统代理”通常有两种含义：

1. **环境变量代理**：只影响支持 `http_proxy`、`https_proxy`、`all_proxy` 的程序。
2. **TUN 透明代理**：通过路由接管服务器大部分流量，更接近桌面客户端里的“系统代理”。

Mihomo 的运行模式、TUN、节点和策略组都可以通过 `external-controller` API 控制。官方 API 的 `/configs` 支持查看和修改运行配置，`/proxies/{组名}` 支持切换组内节点。([虚空终端](https://wiki.metacubex.one/en/api/))

# 一、先准备控制 API

建议配置：

```yaml
mixed-port: 7897

external-controller: 127.0.0.1:9090
secret: "换成一个足够长的随机密码"

profile:
  store-selected: true
```

`store-selected: true` 会保存策略组的 API 选择，Mihomo 重启后可继续使用上一次选择。([虚空终端](https://wiki.metacubex.one/en/config/general/))

修改后检查并重启：

```bash
sudo mihomo -t -d /etc/mihomo
sudo systemctl restart mihomo

curl -H 'Authorization: Bearer 你的密码' \
  http://127.0.0.1:9090/version
```

不要直接把 `9090` 无防护地暴露到公网。该 API 不仅能切换节点，还能修改配置、断开连接和重启内核。官方配置支持通过 `secret` 设置 API 访问密钥。([虚空终端](https://wiki.metacubex.one/en/config/general/))

下面先定义两个变量：

```bash
API='http://127.0.0.1:9090'
SECRET='你的密码'

mcurl() {
    curl -fsS \
      -H "Authorization: Bearer $SECRET" \
      "$@"
}
```

------

# 二、方式一：命令行环境变量代理

这种方式最安全，不会修改服务器路由，也不容易导致 SSH 失联。

在当前 Shell 中开启：

```bash
proxy_on() {
    export http_proxy='http://127.0.0.1:7897'
    export https_proxy='http://127.0.0.1:7897'
    export all_proxy='socks5h://127.0.0.1:7897'

    export HTTP_PROXY="$http_proxy"
    export HTTPS_PROXY="$https_proxy"
    export ALL_PROXY="$all_proxy"

    export no_proxy='127.0.0.1,localhost,::1'
    export NO_PROXY="$no_proxy"
}
```

关闭：

```bash
proxy_off() {
    unset http_proxy https_proxy all_proxy
    unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
    unset no_proxy NO_PROXY
}
```

使用：

```bash
proxy_on
curl -I https://www.google.com/generate_204

proxy_off
```

也可以只让单条命令走代理：

```bash
https_proxy=http://127.0.0.1:7897 \
curl -I https://www.google.com/generate_204
```

或者显式指定：

```bash
curl -x http://127.0.0.1:7897 \
  https://www.google.com/generate_204
```

需要注意：

- `sudo` 默认可能清除代理环境变量，可以使用 `sudo -E`，但要注意安全。
- systemd 服务不会自动继承你的登录 Shell 环境变量。
- 有些程序完全不读取这些变量，需要单独配置。

例如给某个 systemd 服务设置代理：

```bash
sudo systemctl edit docker
```

写入：

```ini
[Service]
Environment="HTTP_PROXY=http://127.0.0.1:7897"
Environment="HTTPS_PROXY=http://127.0.0.1:7897"
Environment="ALL_PROXY=socks5h://127.0.0.1:7897"
Environment="NO_PROXY=127.0.0.1,localhost,::1"
```

然后：

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

------

# 三、方式二：使用 TUN 作为真正的“系统代理”

推荐在配置文件中加入：

```yaml
tun:
  enable: false
  stack: mixed
  auto-route: true
  auto-redirect: true
  auto-detect-interface: true
  strict-route: true
  dns-hijack:
    - any:53
    - tcp://any:53
```

其中：

- `auto-route` 自动把全局流量路由到 TUN。
- `auto-redirect` 仅支持 Linux，会自动配置 iptables/nftables，并要求开启 `auto-route`。
- `strict-route` 会让 Linux 上的连接更严格地进入 TUN，减少流量或 DNS 泄漏。
- 官方文档在无特殊问题时建议使用 `mips` 栈（当前默认值）。([虚空终端](https://wiki.metacubex.one/config/inbound/tun/))

检查 TUN 设备：

```bash
ls -l /dev/net/tun
```

检查 Mihomo 是否有足够权限：

```bash
systemctl show mihomo \
  -p User \
  -p AmbientCapabilities \
  -p CapabilityBoundingSet
```

一般由 root 启动的原生 systemd 服务可以创建 TUN；容器环境则通常需要 `/dev/net/tun` 和 `NET_ADMIN` 权限。官方 MetaCubeXD 的容器 TUN 配置也是这样要求的。([GitHub](https://github.com/metacubex/metacubexd))

## 通过 API 开启 TUN

先查看状态：

```bash
mcurl "$API/configs" | jq '.tun'
```

开启：

```bash
mcurl -X PATCH "$API/configs" \
  -H 'Content-Type: application/json' \
  -d '{"tun":{"enable":true}}'
```

关闭：

```bash
mcurl -X PATCH "$API/configs" \
  -H 'Content-Type: application/json' \
  -d '{"tun":{"enable":false}}'
```

确认：

```bash
mcurl "$API/configs" | jq '.tun'
ip address show
ip rule show
ip route show table 2022
```

官方把 `/configs` 定义为“运行配置”，并允许通过 `PATCH` 更新，包括返回值中的 `tun` 字段。要让设置在重启后仍然有效，还应同步修改 `/etc/mihomo/config.yaml` 中的 `tun.enable`。([虚空终端](https://wiki.metacubex.one/en/api/))

## 远程服务器的重要警告

第一次开启 TUN 前，建议：

```bash
sudo systemd-run --on-active=3m \
  /bin/systemctl restart mihomo
```

这样如果 TUN 导致网络失联，三分钟后 Mihomo 会被重启；前提是配置文件中仍然是：

```yaml
tun:
  enable: false
```

也可以排除你的 SSH 客户端公网 IP：

```yaml
tun:
  enable: false
  auto-route: true
  auto-redirect: true
  auto-detect-interface: true
  route-exclude-address:
    - 203.0.113.25/32   # 替换为你当前的公网 IP
```

官方 TUN 配置支持通过 `route-exclude-address` 排除指定目标网段。([虚空终端](https://wiki.metacubex.one/en/config/inbound/tun/))

------

# 四、查看所有策略组和当前节点

安装 `jq`：

```bash
sudo apt install -y jq
# 或：
sudo dnf install -y jq
```

查看所有可手动选择的组：

```bash
mcurl "$API/proxies" |
jq -r '
  .proxies
  | to_entries[]
  | select(.value.type == "Selector")
  | "\(.key)\t当前：\(.value.now)"
'
```

查看某个组的所有选项：

```bash
GROUP='节点选择'

GROUP_URI=$(
  jq -rn --arg value "$GROUP" '$value | @uri'
)

mcurl "$API/proxies/$GROUP_URI" |
jq '{
  name,
  type,
  now,
  all
}'
```

API 返回的策略组包含：

- `now`：当前选中的节点或子分组。
- `all`：该组全部可选节点或子分组。
- `type`：`Selector`、`URLTest`、`Fallback` 等类型。([虚空终端](https://wiki.metacubex.one/en/api/))

------

# 五、切换某个分组中的节点

例如把“节点选择”组切换为“香港 01”：

```bash
GROUP='节点选择'
NODE='香港 01'

GROUP_URI=$(
  jq -rn --arg value "$GROUP" '$value | @uri'
)

BODY=$(
  jq -nc --arg name "$NODE" '{name:$name}'
)

mcurl -X PUT "$API/proxies/$GROUP_URI" \
  -H 'Content-Type: application/json' \
  -d "$BODY"
```

确认：

```bash
mcurl "$API/proxies/$GROUP_URI" |
jq -r '"当前节点：\(.now)"'
```

官方接口规定，选择指定代理使用：

```text
PUT /proxies/{策略组名}
{"name":"节点名"}
```

成功时通常返回 HTTP 204。([虚空终端](https://wiki.metacubex.one/en/api/))

## 写成一个方便使用的函数

```bash
mihomo_select() {
    local group="$1"
    local node="$2"
    local group_uri
    local body

    if [ -z "$group" ] || [ -z "$node" ]; then
        echo "用法: mihomo_select '分组名' '节点名'" >&2
        return 2
    fi

    group_uri=$(
        jq -rn --arg value "$group" '$value | @uri'
    )

    body=$(
        jq -nc --arg name "$node" '{name:$name}'
    )

    mcurl -X PUT "$API/proxies/$group_uri" \
      -H 'Content-Type: application/json' \
      -d "$body"

    echo "已将 [$group] 切换到 [$node]"
}
```

使用：

```bash
mihomo_select '节点选择' '香港 01'
mihomo_select 'OpenAI' '美国 02'
mihomo_select '流媒体' '新加坡 01'
```

“切换节点”本质上就是切换某个策略组当前选择的成员；该成员既可以是实际节点，也可以是另一个策略组。

------

# 六、切换 Rule、Global 和 Direct 模式

Mihomo 支持：

- `rule`：按照路由规则选择策略组。
- `global`：所有流量使用 `GLOBAL` 策略组。
- `direct`：所有流量直连。([虚空终端](https://wiki.metacubex.one/en/config/general/))

## Rule 模式

```bash
mcurl -X PATCH "$API/configs" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"rule"}'
```

## Global 模式

```bash
mcurl -X PATCH "$API/configs" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"global"}'
```

然后设置 `GLOBAL` 组：

```bash
GLOBAL_URI=$(jq -rn --arg value 'GLOBAL' '$value | @uri')

mcurl -X PUT "$API/proxies/$GLOBAL_URI" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg name '香港 01' '{name:$name}')"
```

## Direct 模式

```bash
mcurl -X PATCH "$API/configs" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"direct"}'
```

查看当前模式：

```bash
mcurl "$API/configs" | jq -r '.mode'
```

------

# 七、自动选择组的固定和恢复

对于 `URLTest`、`Fallback` 等自动组，可以通过 `PUT` 临时固定某个成员。

恢复自动选择：

```bash
GROUP='自动选择'
GROUP_URI=$(jq -rn --arg value "$GROUP" '$value | @uri')

mcurl -X DELETE "$API/proxies/$GROUP_URI"
```

官方 API 说明，`DELETE /proxies/{组名}` 可以清除自动策略组的固定选择；`Selector` 类型除外，因为它本身就是手动选择组。([虚空终端](https://wiki.metacubex.one/en/api/))

测速整个组：

```bash
GROUP='自动选择'
GROUP_URI=$(jq -rn --arg value "$GROUP" '$value | @uri')

mcurl "$API/group/$GROUP_URI/delay?url=https%3A%2F%2Fwww.gstatic.com%2Fgenerate_204&timeout=5000" |
jq
```

------

# 八、让切换立即影响现有连接

切换节点主要影响新连接。现有 TCP 长连接可能继续使用旧节点。

关闭所有经 Mihomo 管理的连接：

```bash
mcurl -X DELETE "$API/connections"
```

官方 API 的 `DELETE /connections` 会关闭全部当前连接。([虚空终端](https://wiki.metacubex.one/en/api/))

谨慎执行：如果当前 SSH 会话也经由 Mihomo/TUN，它可能会被断开。

------

# 九、使用网页面板切换

可以使用官方 MetaCubeXD 面板管理：

- 策略组和节点。
- 延迟测试。
- 运行模式。
- 连接和日志。
- 部分运行配置。

官方面板支持连接远程 Mihomo，也可以通过 `external-ui` 由 Mihomo 自己提供静态页面。([GitHub](https://github.com/metacubex/metacubexd))

推荐保持 API 只监听本机：

```yaml
external-controller: 127.0.0.1:9090
external-ui: /etc/mihomo/ui
secret: "强密码"
```

从本地电脑建立 SSH 隧道：

```bash
ssh -N \
  -L 9090:127.0.0.1:9090 \
  用户名@服务器地址
```

然后在本地浏览器打开：

```text
http://127.0.0.1:9090/ui/
```

这样无需向公网开放 Mihomo 控制端口。

## 推荐组合

对于远程 Linux 服务器，较稳妥的方案是：

```text
日常命令行程序：
    使用 proxy_on / proxy_off 环境变量

需要全机透明代理：
    开启 TUN

切换节点和策略组：
    使用 Mihomo API 或 MetaCubeXD

远程控制：
    external-controller 仅监听 127.0.0.1
    通过 SSH 端口转发访问
```