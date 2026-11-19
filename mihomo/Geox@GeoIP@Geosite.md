[toc]



在网络代理软件（如 **Clash (Mihomo)、Xray、v2fly、Sing-box** 等）的语境下，**GeoX** 并不是一个具体的软件或协议名称，而是一个对**基于地理位置和分类的规则数据库文件**的**统称/代指**。

这个 “**X**” 是一个通配符，代表了代理软件分流（Routing）机制中最核心的两个数据库：**GeoIP** 和 **Geosite**。

## 1. GeoX 包含什么？

它主要由以下两兄弟组成：

- **GeoIP (`geoip.dat` / `.db`)**：**IP 地理位置数据库**。它把全球的 IP 地址归类到不同的国家代码（如 `CN` 代表中国大陆，`US` 代表美国）。
- **Geosite (`geosite.dat` / `.db`)**：**域名分类数据库**。它把庞大的网址域名按照公司、服务或区域进行归类（如 `geosite:google` 包含 Google 旗下的所有域名，`geosite:cn` 包含绝大多数国内主流网站域名，`geosite:category-ads-all` 包含常见的广告域名）。

由于这两者的前缀都是 `Geo`，且在现代内核（如 Mihomo/Clash Meta）中经常作为一套完整的规则集被打包、更新和维护，社区便约定俗成地用 **GeoX** 来统一指代它们。

## 2. 它在代理软件里起什么作用？

GeoX 是代理软件实现“分流（智能路由）”的基石。

如果没有 GeoX，你必须在配置文件里手动一行行写死千百个具体的域名和 IP 段。有了 GeoX 之后，你只需要写几行宏观的规则，代理软件就能自动判断流量的去向：

- **国内流量直连**：匹配到 `geosite:cn`（国内域名）或 `geoip:cn`（国内 IP）的流量，直接不走代理，保证速度且节省机场流量。
- **广告屏蔽**：匹配到 `geosite:category-ads-all` 的流量，直接导向 `REJECT`（拦截），实现全局去广告。
- **海外流量代理**：未匹配到国内规则的其余流量（`MATCH`），自动走代理节点。

## 3. 常见的 GeoX 变体与文件格式

随着内核的演进，GeoX 文件的格式也在发生变化：

| **格式后缀**               | **常见内核**                  | **特点**                                                     |
| -------------------------- | ----------------------------- | ------------------------------------------------------------ |
| **`.dat` 格式** (Protobuf) | Xray, V2Ray, 早期 Clash       | 经典的二进制格式，由 V2Ray 社区发扬光大。体积相对小，但大规则检索时内存占用稍高。 |
| **`.db` / `.mmdb` 格式**   | Mihomo (Clash Meta), Sing-box | 现代内核更青睐的格式（如 MaxMind 格式或 Sing-box 专属二进制）。检索效率极高，内存占用更低，支持更复杂的规则嵌套。 |

## 4. 为什么大家经常谈论“更新 GeoX”？

在各类代理客户端（如 Clash Verge Rev、NekoBox、v2rayN）的设置里，经常能看到“更新 GeoX 数据库”或“自动更新 GeoX”的选项。

这是因为**互联网的 IP 分配和域名是在不断变动和增加的**。如果你的 GeoX 数据库几个月不更新，就可能导致：

1. 部分新成立的国内网站被错误地识别为国外流量，平白浪费代理流量。
2. 某些原本走代理的服务（例如 Netflix 或 ChatGPT 新启用的域名）因为不在旧数据库里，导致无法正常访问。

目前开源社区有非常多优秀的团队在自发维护高精度的 GeoX 数据库（例如 `Loyalsoldier/v2ray-rules-dat` 或 MetaCubeX 团队的维护版本），客户端通常会自动从 GitHub 订阅并下载这些编译好的最新版本。

## 5. 首次运行的数据文件补齐

> 对于mihomo命令行程序用户,初次运行,可能会因为订阅配置中需要的一些Geo相关数据库依赖,而触发自动下载,但是来源github可能导致下载失败.

```shell
$ mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
INFO[2026-07-09T15:47:38.345357443+08:00] Start initial configuration in progress      
INFO[2026-07-09T15:47:38.350661271+08:00] Geodata Loader mode: memconservative         
INFO[2026-07-09T15:47:38.350682180+08:00] Geosite Matcher implementation: succinct     
INFO[2026-07-09T15:47:38.350785420+08:00] Can't find MMDB, start download   
```

你的日志流程是：

- 读取 default.generated.yaml
- 发现规则里有 GEOIP,CN,DIRECT
- 需要 GeoIP 数据库
- 本地找不到 MMDB
- 尝试从 GitHub 下载 geoip.metadb
- 国内网络可能超时,配置解析失败，mihomo 退出!

### 初次运行会做什么

mihomo 初次运行大致会做这些事：

| 步骤             | 做什么                              | 你的日志对应                  |
| ---------------- | ----------------------------------- | ----------------------------- |
| 读取配置         | 解析 `-f` 指定的 YAML               | `Start initial configuration` |
| 初始化 Geo 数据  | 加载 GeoIP、GeoSite、MMDB 等        | `Geodata Loader mode`         |
| 检查本地数据文件 | 看 HomeDir 下有没有 MMDB            | `Can't find MMDB`             |
| 自动下载缺失数据 | 默认从 GitHub 下载                  | `start download`              |
| 解析规则         | 解析 `rules` 中的 `GEOIP,CN,DIRECT` | `rules[2] [GEOIP,CN,DIRECT]`  |
| 启动服务         | 若配置成功，才启动端口、DNS、TUN 等 | 你这里没走到这一步            |

你的问题发生在 **配置解析阶段**，所以 mihomo 甚至还没真正进入可用运行状态。

因为你的配置里有：

```yaml
rules:
  - GEOIP,CN,DIRECT
```

`GEOIP` 规则需要 GeoIP 数据库。mihomo 没找到本地 MMDB，于是访问：

```text
https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb
```

但国内命令行环境访问 GitHub Release 经常超时，于是报：

```text
context deadline exceeded
```

官方示例配置中也能看到 `geox-url` 可以自定义 `geoip`、`geosite`、`mmdb`、`asn` 下载地址。([GitHub](https://raw.githubusercontent.com/MetaCubeX/mihomo/refs/heads/Meta/docs/config.yaml))

## 6. 国内网络下的下载加速

最稳妥的是：**不要让 mihomo 初次启动时临时去 GitHub 下载 Geo 数据，而是提前手动准备，或者在配置里改成可访问的镜像地址。**

### 做法一：手动下载 MMDB 到配置目录

例如当前启动命令是：

```bash
mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
```

但你没有显式 `-d`，所以 HomeDir 通常仍是：

```bash
~/.config/mihomo
```

可以先建目录(如果缺失的话会创建),确保目录存在(其他自定义目录类似)：

```bash
mkdir -p ~/.config/mihomo
```

然后把 `geoip.metadb` 下载到这里。

如果能访问 GitHub：

```bash
url="https://gh-proxy.com/https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb"
curl -L -o ~/.config/mihomo/geoip.metadb "$url" # 保存路径根据实际情况修改.这里是默认情况
```

如果 GitHub 不稳定，就用你能访问的镜像源下载同名文件。

> 例如使用`https://gh-proxy.com`.

> MetaCubeX 的 `meta-rules-dat` 仓库提供 `geoip.metadb`、`country-lite.mmdb`、`geoip-lite.dat` 等资源。([GitHub](https://github.com/MetaCubeX/meta-rules-dat))

然后重新运行：

```bash
mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
```

### 做法二：在 YAML 里配置 `geox-url`

在 `default.generated.yaml` 顶层加入类似配置：

```yaml
geox-url:
  geoip: "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.dat"
  geosite: "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geosite.dat"
  mmdb: "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb"
  asn: "https://fastly.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/GeoLite2-ASN.mmdb"

geo-auto-update: true
geo-update-interval: 24
```

官方示例配置里就展示了通过 `geox-url` 自定义 Geo 数据下载地址，并包含 `mmdb` 指向 `geoip.metadb` 的写法。([GitHub](https://raw.githubusercontent.com/MetaCubeX/mihomo/refs/heads/Meta/docs/config.yaml))

### 做法三：临时绕开 GEOIP 规则

如果只是想先启动验证代理，可以暂时把：

```yaml
- GEOIP,CN,DIRECT
```

改成注释：

```yaml
# - GEOIP,CN,DIRECT
```

然后保留兜底：

```yaml
- MATCH,PROXY
```

但这只是临时方案。缺点是国内 IP 直连规则没了，流量分流会不准。

### 推荐你的最终配置习惯

命令行用户建议固定使用 `-d`，避免路径混乱：

```bash
mihomo -d ~/.config/mihomo -f ~/.config/mihomo/myprofiles/default.generated.yaml
```

这样所有相对路径、provider 缓存、Geo 数据都明确归到：

```text
~/.config/mihomo
```

然后在配置顶层加：

```yaml
geo-auto-update: true
geo-update-interval: 24
geox-url:
  mmdb: "你能稳定访问的 geoip.metadb 地址"
```

你的这个报错，核心解决点就是：**提前准备 `geoip.metadb`，或者把 `geox-url.mmdb` 改成国内可访问地址。**
