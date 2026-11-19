[toc]

## abstract

假设某个适用于mihomo的订阅的节点里,包含多个国家的节点.
如果要按国家分组(代理组),各组走负载均衡(load-balance,简记为`LB`),如何操作?

> 这种配置典型应用场景是爬虫.

可以用 **`proxy-groups + filter + load-balance`** 做。

核心思路是：**按节点名里的国家关键词正则筛选节点**，每个国家建一个 `type: load-balance` 组。

> mihomo 的 `filter` 支持关键字/正则,在代理组定义中使用`filter`来实现灵活的代理分组，且对 `use` 引入的 proxy-provider 或 `include-all-*` 生效；

`load-balance` 支持 `round-robin / consistent-hashing / sticky-sessions`，爬虫测试通常用 `round-robin`。

### 推荐配置示例

把订阅作为 `proxy-provider` 引入，然后按国家分组：

```yaml
mixed-port: 7890
allow-lan: false
mode: rule
log-level: info

proxy-providers:
  sub:
    type: http
    url: "你的订阅链接"
    path: ./proxy_providers/sub.yaml
    interval: 86400
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 300

proxy-groups:
  - name: 🇺🇸 美国-LB
    type: load-balance
    use:
      - sub
    filter: '(?i)(美国|美國|洛杉矶|洛杉磯|纽约|紐約|西雅图|西雅圖|圣何塞|聖荷西|硅谷|\bUSA?\b|United ?States|America)'
    url: https://www.gstatic.com/generate_204
    interval: 300
    strategy: round-robin

  - name: 🇯🇵 日本-LB
    type: load-balance
    use:
      - sub
    filter: '(?i)(日本|东京|東京|大阪|樱花|櫻花|\bJP\b|Japan|Tokyo|Osaka)'
    url: https://www.gstatic.com/generate_204
    interval: 300
    strategy: round-robin

  - name: 🇸🇬 新加坡-LB
    type: load-balance
    use:
      - sub
    filter: '(?i)(新加坡|狮城|獅城|\bSG\b|Singapore)'
    url: https://www.gstatic.com/generate_204
    interval: 300
    strategy: round-robin

  - name: 🇭🇰 香港-LB
    type: load-balance
    use:
      - sub
    filter: '(?i)(香港|\bHK\b|Hong ?Kong)'
    url: https://www.gstatic.com/generate_204
    interval: 300
    strategy: round-robin

  - name: 🕷 爬虫出口
    type: select
    proxies:
      - 🇺🇸 美国-LB
      - 🇯🇵 日本-LB
      - 🇸🇬 新加坡-LB
      - 🇭🇰 香港-LB

rules:
  - MATCH,🕷 爬虫出口
```

这样所有走 mihomo 的流量都会先进入 `🕷 爬虫出口`，你可以手动选择“美国-LB / 日本-LB / 新加坡-LB / 香港-LB”。每个国家组内部再进行负载均衡。

本仓库已按本文思路落地的完整实例见 `templates/spider_lb.template.yaml` 与 `templates/spider_lb.profiles.json`（渲染产物 `*.generated.yaml` 不入库）：12 个 `crawler-*` 入口、按国家分组、`IN-NAME` 分流和规则顺序都在里面。自建节点默认不启用，模板里保留了本地 provider 与“自建-LB”兜底组的注释示例。

### filter 写法的两个坑（实测）

**坑一：短国家码不加词边界，会撞上别的英文词。** 用上面那类节点名实测裸写国家码（`US`、`DE`、`TH`、`TW`、`IT`）的效果：

| 节点名 | 裸写国家码的结果 | 期望 |
| --- | --- | --- |
| `Russia-Moscow-02` | 美国-LB | 俄罗斯 |
| `Australia-Sydney` / `Belarus-Minsk` | 美国-LB | 不匹配 |
| `Sweden-Stockholm` | 德国-LB | EU |
| `Delhi-IN-01` | 德国-LB | 不匹配 |
| `Netherlands-Amsterdam` / `North-America-01` | 泰国-LB（`TH` 命中 `th`） | EU / 美国 |
| `Network-SG-01` | 台湾-LB（`TW` 命中 `tw`） | 新加坡 |
| `DigitalOcean-SG` | EU-LB（`IT` 命中 `it`） | 不匹配 |

原因是 `filter` 是**子串正则**，`US` 在 `Russia`、`Australia` 里同样成立。给国家码加 `\b` 即可：

```yaml
filter: '(?i)(美国|美國|洛杉矶|\bUSA?\b|United ?States|America)'
filter: '(?i)(德国|德國|法兰克福|\bDE\b|Germany)'
```

mihomo 的 `filter` / `exclude-filter` 用的是 `regexp2` 引擎（.NET 风格，`dlclark/regexp2`），支持 `\b` 和前后瞻，不必担心 Go RE2 的限制。多个过滤式可以用反引号 `` ` `` 分隔，彼此是“或”的关系，并且会影响组内节点的排列顺序。([parser.go](https://github.com/MetaCubeX/mihomo/blob/Alpha/adapter/outboundgroup/parser.go))

**坑二：YAML 双引号里写 `\b`，会被解释成退格符。**

```yaml
# 错的：双引号中的 \b 是 0x08 退格符，正则永远匹配不上
filter: "(?i)\bUS\b"

# 对的：单引号不做转义
filter: '(?i)\bUS\b'

# 对的：双引号里写两个反斜杠
filter: "(?i)\\bUS\\b"
```

实测把 `\b` 放进双引号后，`US-LosAngeles-01` 这个节点一个都筛不出来，而且**没有任何报错**，只表现为组里节点变少或整组为空。改完建议核对一次实际入组结果：

```powershell
$api = 'http://127.0.0.1:9097'
$h = @{ Authorization = 'Bearer <secret>' }
$name = [uri]::EscapeDataString('🇺🇸 美国-LB')   # 组名含空格和 emoji，需要编码
(Invoke-RestMethod "$api/proxies/$name" -Headers $h).all
```

另外，`filter` 只匹配**节点名**。自建节点如果叫 `self-vless-reality`、`self-hysteria2` 这种纯协议名，国别关键词一个都没有，就永远进不了国家组，只能靠改名或单独建一个“自建-LB”组兜住。

### 如果你想让不同爬虫走不同国家

可以开多个监听端口，然后用 `IN-NAME`(推荐)或 `IN-PORT` 分流。mihomo 规则支持按入站端口、入站类型、入站名称匹配。([虚空终端](https://wiki.metacubex.one/en/config/rules/))

```yaml
listeners:
  - name: crawler-us
    type: mixed
    listen: 127.0.0.1
    port: 7891

  - name: crawler-jp
    type: mixed
    listen: 127.0.0.1
    port: 7892

rules:
  - IN-NAME,crawler-us,🇺🇸 美国-LB
  - IN-NAME,crawler-jp,🇯🇵 日本-LB
  - MATCH,🕷 爬虫出口
```

用 `IN-NAME` 的好处是端口只写在 `listeners` 里，改端口不用同步改规则；入口名还会出现在日志与 `/connections` 的详情里，排错时能直接看出是哪个爬虫入口。`IN-PORT` 仍然可用，适合入口没有命名或一个端口被多套规则复用的场景。

两个容易踩的点：

- **规则顺序**：如果 `rules` 前面还有 `RULE-SET,direct_domain,DIRECT`、`RULE-SET,cn_ip,DIRECT` 这类直连规则，从 `crawler-us` 进来的国内目标会先命中直连，实际用本机 IP 出去，而不是美国组。要求“该端口一律走该国 IP”，就得把入口规则放到这些直连规则之前。
- 也可以用 listener 的 `proxy` 字段直接把入口钉死到某个组，此时不再走 `rules`（私有网络目标也会被一起代走，需要例外时另外配 `sub-rules`）：

```yaml
listeners:
  - name: crawler-us
    type: mixed
    listen: 127.0.0.1
    port: 7891
    proxy: 🇺🇸 美国-LB
```

然后爬虫里这样用：

```python
# 美国出口
proxies = {
    "http": "http://127.0.0.1:7891",
    "https": "http://127.0.0.1:7891",
}
# 日本出口
proxies = {
    "http": "http://127.0.0.1:7892",
    "https": "http://127.0.0.1:7892",
}
```

### 策略怎么选

爬虫测试建议：

```yaml
strategy: round-robin
```

三种策略的实际差异（源码 `adapter/outboundgroup/loadbalance.go`）：

| 策略 | 分配依据 | 对爬虫的影响 |
| --- | --- | --- |
| `consistent-hashing`（不写时的默认值） | 目标域名的主域名（eTLD+1）或目标 IP | 同一站点固定一个节点，登录态稳定，但出口 IP 变化少 |
| `round-robin` | 按连接顺序轮换 | 新连接换节点；爬虫用连接池或 keep-alive 时，同一条连接里的请求仍是同一个出口 |
| `sticky-sessions` | 源 IP + 目标，缓存 10 分钟 | 多台爬虫机器共用一个入口时相对稳定，10 分钟后重新分配 |

几个容易忽略的细节：

- 三种策略都会跳过“该组 `url` 测速不通过”的节点，全部不通过才退回第一个节点。所以组上的 `url` 不只是摆设，它决定用哪份测速结果判断存活。
- `round-robin` 的轮换粒度是连接，不是请求；想看到 IP 频繁变化，爬虫侧要主动断开或禁用连接复用。
- 入口配了 `users` 时，新版内核可以用 `hash-key: in-user` 把同一个用户的流量钉在同一个节点，比按源 IP 更可靠。

官方文档里也有这三种策略的说明。([虚空终端](https://wiki.metacubex.one/en/config/proxy-groups/load-balance/))

### 注意事项

节点能否按国家分组，取决于**订阅里的节点名是否包含国家/地区关键词**。

如果节点名不规范，`filter` 会筛不到，需要先用订阅转换、覆写、Sub-Store 或客户端的配置覆写功能把节点名规范化。

不要直接改机场原始订阅文件；订阅一更新就会覆盖。

最好用客户端的“配置覆写 / profile mixin / parser / merge”功能，把上面这些 `proxy-groups` 和 `rules` 合并进去。

### 组筛成空组会怎样

`filter` 写错、订阅过期、机场批量改节点名，都会让某个国家组变成空组。mihomo 的处理是给这个组塞一个 `COMPATIBLE` 占位代理（`empty-fallback` 的默认值），规则照样命中，但连接会失败——**不会自动回落 DIRECT**。

想显式兜底就用 `empty-fallback`，它只能填**具体节点或内置策略**，不能填另一个代理组：

```yaml
- name: 🇺🇸 美国-LB
  type: load-balance
  use: [sub]
  filter: '(?i)(美国|美國|\bUSA?\b)'
  empty-fallback: REJECT   # 也可以填 DIRECT 或某个节点名
```

爬虫场景要谨慎用 `DIRECT`：空组时静默改用本机出口，采集结果里会混进国内 IP，比直接失败更难发现；`REJECT` 至少能让问题暴露出来。如果接入了自建节点，在 `select` 总入口里放一个“自建-LB”子组兜底，比依赖 `empty-fallback` 更直观。

## 出口ip轮换注意事项

mihomo 的 `load-balance` 是在“节点条目”之间轮换，不等于在“出口 IP”之间轮换；同一 IP 的不同协议节点会被当成不同节点。

有的配置节点ip相同只是协议不同,这样对于爬虫就起不到切换ip的效果.

这种情况**单纯 `load-balance` 不够**。它只会在“节点配置项”之间轮换，不会自动判断这些节点背后的**出口 IP 是否相同**。

例如 `US-01-SS`、`US-01-Trojan`、`US-01-VLESS` 如果实际出口 IP 一样，会被当成 3 个节点轮询，但爬虫看到的还是同一个 IP。

比较好的做法有三种：

### 方案 1：优先用节点名规则排除重复协议

如果机场节点命名有规律，比如同 IP 节点只是协议不同，可以每个国家组只保留一种协议。

例如只保留 Trojan：

```yaml
proxy-groups:
  - name: 🇺🇸 美国-LB
    type: load-balance
    use:
      - sub
    filter: '(?i)(美国|美國|\bUSA?\b|United ?States)'
    exclude-type: "Shadowsocks|Vmess|Vless|Hysteria2"
    url: https://www.gstatic.com/generate_204
    interval: 300
    strategy: round-robin
```

或者只保留名称里带 `倍率1x`、`标准`、`IEPL` 之类的节点：

```yaml
filter: '(?i)(美国|\bUSA?\b).*(Trojan|标准|1x)'
exclude-filter: '(?i)(中转|备用|倍率2|倍率3|游戏|家宽同入口)'
```

mihomo 的 `filter` / `exclude-filter` 可以按关键词或正则筛选节点；`exclude-type` 是 `|` 分隔的类型名列表，**不是正则**。注意组级与 provider 级取值不同：组级比对 Adapter Type 名（`Shadowsocks`、`Vmess`、`Vless`、`Hysteria2`），写 `ss` 在组级不会命中；provider 级才使用配置里的 `type`（`ss`、`vmess`）。([虚空终端](https://wiki.metacubex.one/en/config/proxy-providers/))

### 方案 2：在订阅预处理阶段“按 server 去重”

这是更推荐的方式。因为 mihomo 本身不擅长“按出口 IP 去重”，你可以在 **Sub-Store / 订阅转换 / 自写脚本** 里先处理订阅：

逻辑是：

```text
同一个国家组内：
  server / host / address 相同的节点，只保留一个
  如果 server 不同，再保留
```

例如：

```text
US-01-SS      server: 1.2.3.4  保留
US-01-Trojan  server: 1.2.3.4  删除
US-02-VLESS   server: 5.6.7.8  保留
```

处理后再给 mihomo 的 `load-balance` 使用：

```yaml
proxy-providers:
  sub-dedup:
    type: http
    url: "去重后的订阅链接"
    path: ./proxy_providers/sub-dedup.yaml
    interval: 86400
```

这种方式最干净。Sub-Store 这类订阅管理工具支持通过脚本批量处理、重命名、合并订阅；官方仓库也说明它是高级订阅管理工具。([GitHub](https://github.com/sub-store-org/Sub-Store))

### 方案 3：运行时检测出口 IP，再生成可用节点池

如果你的目标是**爬虫真实切 IP**，最可靠的方式是：

1. 逐个节点测试出口 IP。
2. 同一出口 IP 只保留一个节点。
3. 生成新的 mihomo provider 文件。
4. 国家负载均衡组引用这个去重后的 provider。

检测逻辑大概是：

```text
切到节点 A -> 请求 https://api.ipify.org -> 得到出口 IP
切到节点 B -> 请求 https://api.ipify.org -> 得到出口 IP
如果出口 IP 已出现过，B 不加入池
```

这样能解决两类问题：

```text
同 server，同出口 IP
不同 server，但 NAT 后出口 IP 仍相同
```

注意：**按 server 去重不等于按出口 IP 去重**。有些机场会多个入口 server 最后 NAT 到同一个出口 IP，所以爬虫场景最好以“实际出口 IP”为准。

## 建议

你的场景是“爬虫测试”，我建议这样组合：

```text
订阅原始节点
  ↓
Sub-Store / 脚本预处理
  ↓
按国家分组
  ↓
按实际出口 IP 去重
  ↓
生成 US-dedup、JP-dedup、SG-dedup provider
  ↓
mihomo 里每国 load-balance: round-robin
```

最终 mihomo 里只保留：

```yaml
proxy-groups:
  - name: 🇺🇸 美国-LB
    type: load-balance
    use:
      - us-dedup
    url: https://www.gstatic.com/generate_204
    interval: 300
    strategy: round-robin
```

`round-robin` 会在组内节点间轮换，适合你这种希望爬虫尽量轮换出口的用途。官方文档里 `load-balance` 支持 `round-robin`、`consistent-hashing` 和 `sticky-sessions` 等策略；爬虫切 IP 一般不要用粘性策略。([虚空终端](https://wiki.metacubex.one/en/config/proxy-groups/))

一句话：**先去重，再负载均衡**。mihomo 负责分流和轮询，出口 IP 去重最好放到订阅预处理或外部脚本里做。