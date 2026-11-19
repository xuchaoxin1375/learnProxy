[toc]

## 自动更新不是一个开关

**订阅节点、规则集、Geo 数据是三条独立的更新链路，各自的更新节奏写在各自的 provider 里；mihomo 没有“全局关闭自动更新”的开关。**

| 更新对象 | 配置位置 | 控制字段 | 本仓库当前取值（由清单渲染，产物不入库） |
| --- | --- | --- | --- |
| 订阅节点 | `proxy-providers.<name>`（`type: http`） | `interval`、`proxy`、`path`、`size-limit`、`health-check` | `online-sub1` 用 `interval: 43200`（约每天 2 次）、显式 `proxy: PROXY`、不写 `path` |
| 订阅节点（本地） | `proxy-providers.<name>`（`type: file`） | 无更新周期，靠文件监听 | 本仓库默认不启用；接入自建节点时只合并 `health-check`，没有 `interval`，读 `./myprofiles/*.yaml` |
| 分流规则 | `rule-providers.<name>` | `interval`、`proxy`、`path` | 四个规则集都是 `interval: 86400` + `proxy: PROXY`，缓存到 `./ruleset/*.yaml` |
| Geo 数据 | 全局 `geo-auto-update` / `geo-update-interval` | 默认关闭 | 文件里没有设置，即不自动更新 |

这些值不直接写在生成物 `*.yaml` 里：产物由 `templates/spider_lb.template.yaml` 与清单（公开的 `spider_lb.profiles.json` 或本地私有清单）渲染而来，改订阅节奏要改清单里的 `subscriptions[].interval`（或作为默认值的 `subscriptionInterval`），手改产物会被校验发现。渲染、指纹与验收见 [mihomo@配置模板与生成物@render-profile渲染与校验](./mihomo@配置模板与生成物@render-profile渲染与校验.md)。

`interval` 的官方定义只有一句“更新 provider 的时间，单位为秒”，真正的启动判定、到点触发和失败重试由内核的 fetcher 实现。([虚空终端](https://wiki.metacubex.one/config/proxy-providers/))

## 内核实际怎么排更新

依据 mihomo `component/resource/fetcher.go`（`Alpha` 分支）与本地 v1.19.32 实测：

| 阶段 | 行为 | 影响 |
| --- | --- | --- |
| 启动 | 先读本地缓存文件；`updatedAt` 被重置为该文件的 mtime | 重启后 `updatedAt` 会“退回”到缓存文件的修改时间，不是重启时间 |
| 启动判定 | 缓存文件年龄 `> interval` 才强制刷新，否则直接用缓存 | 频繁重启不会放大订阅流量 |
| 缓存缺失 | 直接发起一次下载，再进入循环 | 首次部署必然拉一次 |
| 到点触发 | 定时器初值 `interval - (now - updatedAt)` | 各 provider 按自身节奏错峰，不是整点批处理 |
| 更新失败 | 指数退避重试，起点 `10s`（或 `interval`，取较小者），上限 `interval` | 断网恢复后不用等一整天 |
| 内容未变 | 内容 hash 相同则只刷新 `updatedAt`，不重写缓存文件 | 文件 mtime 停滞不代表没更新 |
| 省略 `interval` | 视为 `0`：启动时强制拉一次，之后不再循环 | 这是唯一的“关掉自动更新”写法 |
| `type: file` | 不下载，改为监听本地文件变化 | 编辑本地节点文件会实时重载，与 `interval` 无关 |

`interval` 与健康检查是两回事：`health-check.interval: 300` 只是测速节奏，且 `lazy` 默认 `true`，没被使用的节点不会按 5 分钟全量测速。([虚空终端](https://wiki.metacubex.one/config/proxy-providers/))

## 想达到什么效果，改哪里

本仓库的订阅节奏由清单的 `subscriptions[].interval` 渲染进产物（没写时用 `subscriptionInterval` 默认值），改完要重新渲染并重新应用，具体见 [mihomo@配置模板与生成物@render-profile渲染与校验](./mihomo@配置模板与生成物@render-profile渲染与校验.md)。下表适用于任意 mihomo 配置。

| 目标 | 做法 | 代价与注意 |
| --- | --- | --- |
| 彻底关掉订阅自动更新 | 删除 `interval`（启动仍会拉一次） | 想要启动也不联网，只能改用 `type: file` 或 `inline` |
| 降低更新频率 | 把 `interval` 调大，如 `604800`（一周） | 机场节点变动后会滞后 |
| 提高更新频率 | 调小 `interval`，如 `3600` | 订阅请求变多，部分机场会限流或计次 |
| 固定缓存文件名 | 显式写 `path: ./proxy_providers/<name>.yaml` | 换 URL 后旧缓存会顶替新订阅，换 URL 时同步删缓存 |
| 限制单次下载大小 | `size-limit: 10485760`（字节，默认 `0` 不限制） | 超大订阅或异常响应会撑内存与磁盘 |
| 指定下载链路 | `proxy: DIRECT` 或 `proxy: <代理组名>` | 不写时行为见下一节，取决于版本实现 |
| 规则集更新不走代理 | 去掉 `rule-providers.*.proxy` | 直连拉 `cdn.jsdelivr.net` 在国内常失败，会一直用旧规则 |

## 订阅下载走哪条路

官方文档里 `proxy` 的作用是“经过指定代理进行下载/更新”，示例配置通常写 `proxy: DIRECT`。([虚空终端](https://wiki.metacubex.one/config/proxy-providers/))

本机实测给出的反例值得记住（当时 `online-sub1` 还没有写 `proxy`，现在生成物里已显式写 `PROXY`）：抓 `/connections` 与内核日志得到：

```text
host   = example.com
chains = 🇺🇸美国·洛杉矶|原生-4 <- 美国-LB <- PROXY
rule   = Match
process = mihomo
```

也就是说这次订阅下载由 mihomo 自身发起，经规则 `MATCH` 落到 `PROXY` 组，而不是直连。结论：

- 不写 `proxy` 不等于“一定直连”，本机实测是走策略路由
- 想让行为确定，就显式写 `proxy: DIRECT` 或某个代理组
- 订阅域名在国内不可达时，“没写 proxy”可能表现为更新失败并回退到旧缓存，日志里才有 `[Provider] ... pull error`

## 缓存文件在哪、长什么样

不写 `path` 时，文件名是 URL 的 MD5（小写、无扩展名），位置在**工作目录的 `proxies/` 下**：

```text
<HomeDir>/proxies/<url 的 md5>
```

`online-sub1`（原 `xs`）对应 `<HomeDir>\proxies\<url 的 md5>`，没有扩展名，内容是**订阅原始响应**。

几个容易误判的点：

- 该订阅返回的是完整 clash 配置（含 `mixed-port`、`proxy-groups` 等），内核只取其中的 `proxies` 段，所以缓存文件看起来像一份配置而不是节点列表
- 显式写了 `path` 就以 `path` 为准，本仓库规则集用的是 `./ruleset/direct-domain.yaml` 这类路径
- `proxy_providers/` 目录里可能残留旧版本或旧配置生成的文件（本机就有 8 月遗留的 `xs.yaml`，旧 provider 名），不要拿它当当前缓存判断依据
- `updatedAt` 在内核内存里，重启后等于缓存文件 mtime；判断“多久没更新”要同时看 API 和文件 mtime

落盘细节（依据 mihomo `component/resource/vehicle.go`）：

| 项 | 行为 |
| --- | --- |
| 相对路径基准 | 工作目录 `HomeDir`（内核 `-d` 的值），不是 yaml 所在目录 |
| 目录与权限 | 父目录不存在时自动创建（`0755`），文件权限 `0666` |
| 越界限制 | 只允许 `HomeDir` 及其子目录；要写到别处需用 `SAFE_PATHS` 环境变量追加（Windows 用 `;` 分隔） |
| 写入方式 | `os.WriteFile` 覆盖写，**不是原子操作**：先截断再写，更新进行中拷走文件可能拿到半截缓存 |
| 内容未变 | 不重写内容，只 `Chtimes` 把 mtime 推到当前时间（`etag-support: true` 时 304 也走这条） |
| 下载失败 | 不写任何内容，保留旧缓存，日志 `[Provider] <name> pull error` |
| 订阅用量与 ETag | 存在 `HomeDir/cache.db`，`subscriptionInfo` 与 If-None-Match 用的 hash 都在这里 |

要定位“当前到底用的哪个文件”，用 URL 的 MD5 算，或者按修改时间找最新的：

```powershell
$homeDir = '<HomeDir>'  # 换成你的 -d
$url = 'https://example.com/api/v1/client/subscribe?token=YOUR_SUBSCRIPTION_TOKEN'
$md5 = [BitConverter]::ToString([Security.Cryptography.MD5]::Create().ComputeHash(
    [Text.Encoding]::UTF8.GetBytes($url))).Replace('-', '').ToLower()
Join-Path $homeDir "proxies\$md5"

Get-ChildItem -LiteralPath "$homeDir\proxies" | Sort-Object LastWriteTime -Descending |
    Select-Object Name, Length, LastWriteTime
```

接口不暴露缓存路径（`/providers/proxies` 只有名称、类型、时间与节点），所以要么按 MD5 算，要么在 provider 上显式写 `path` 让路径可预期。

仓库里的两个 provider 脚本会按同样的规则把路径算出来一起显示：先读内核配置（`-f`）里每个 provider 的 `path` / `url`，没写 `path` 的 `http` 条目用 URL 的 MD5 拼出默认位置。定位工作目录与配置文件的顺序是 `--home-dir` / `--config-path` 参数 > `MIHOMO_HOME` / `MIHOMO_CONFIG` 环境变量 > 运行中内核进程的命令行（`-d` / `-f`，Windows 下借 PowerShell CIM 读取，取不到就跳过）。脚本只解析 `proxy-providers` / `rule-providers` 的块状写法，流式写法与 YAML 锚点不解析；读不到配置或工作目录时路径显示“未解析”，其余输出不受影响。

## 核验现状（只读）

关键是三个 API 与两个文件系统旁证，全部只读，不会产生订阅流量。

仓库内提供只读脚本 `check_provider_status.py`，默认输出竖排明细（含缓存路径），`--summary` 换成汇总表：

```bash
python3 check_provider_status.py --secret '<secret>'                     # 竖排明细，带 path
python3 check_provider_status.py --secret '<secret>' --summary           # 状态表 + 订阅用量（不含 path）
python3 check_provider_status.py --secret '<secret>' --summary --list    # 汇总改竖排，带 path
python3 check_provider_status.py --secret '<secret>' --json              # 交给其他脚本
python3 check_provider_status.py --stale-hours 30 --fail-on-stale        # 巡检，过期则退出码 3
python3 check_provider_status.py --require-providers                     # 没有 provider 也返回 3
```

字段：`kind`、`name`、`vehicle`、`updatedAt`、`age`、`count`、`stale`、`note`、`path`、`fileExists`。默认输出和 `--list` 都带 `path`，`--summary` 的汇总表不显示；`--json` 里另有顶层 `homeDir` / `configPath` 说明路径是按哪份配置算的。自动探测不准时用 `--home-dir <目录>`、`--config-path <文件>` 指定。

当前 API 没有任何可检查的 provider 时，脚本会提示“可能未启用 proxy-providers”并照常输出空表；监控场景加 `--require-providers`，这种情况返回 `3`，避免把“配置里根本没有 provider”误判为健康。

脚本只发 `GET`，不下载订阅、不测速、不改配置；`--help` 列出全部参数。下面是不依赖脚本的手工命令，便于在其他机器照做。

```powershell
$api = 'http://127.0.0.1:9097'
$h = @{ Authorization = 'Bearer <secret>' }

# 节点 provider：类型、更新时间、节点数
$j = Invoke-RestMethod "$api/providers/proxies" -Headers $h
$j.providers.PSObject.Properties | ForEach-Object {
    [pscustomobject]@{
        name      = $_.Value.name
        vehicle   = $_.Value.vehicleType
        updatedAt = $_.Value.updatedAt
        nodes     = @($_.Value.proxies).Count
    }
}

# 订阅流量与到期（机场在响应头里返回时才有）
$j.providers.'online-sub1'.subscriptionInfo

# 规则集：更新时间与规则条数
(Invoke-RestMethod "$api/providers/rules" -Headers $h).providers.PSObject.Properties |
    ForEach-Object {
        [pscustomobject]@{
            name      = $_.Value.name
            updatedAt = $_.Value.updatedAt
            ruleCount = $_.Value.ruleCount
        }
    }
```

```bash
curl -s -H "Authorization: Bearer <secret>" http://127.0.0.1:9097/providers/proxies \
  | jq '.providers | to_entries[] | select(.value.vehicleType != "Compatible") | {name: .key, vehicle: .value.vehicleType, updatedAt: .value.updatedAt, nodes: (.value.proxies | length)}'
```

字段与旁证怎么读：

| 证据 | 说明 |
| --- | --- |
| `vehicleType` | `HTTP` 才会自动下载；`File` 只看本地文件；`Compatible` 是代理组被当作 provider 一起返回的条目，不是订阅 |
| `updatedAt` | 最近一次成功更新时间（含“内容未变”）；失败不刷新；重启后退回缓存文件 mtime |
| `proxies` 数量 | 节点集合是否真的换过，比 `updatedAt` 更能看出内容变化 |
| `subscriptionInfo` | 上传、下载、总量、到期时间戳，来自订阅响应头 |
| 缓存文件 mtime | 内容未变时只 `Chtimes`，内容变了才重写；两者都会推进时间 |
| `/logs?level=info`（WebSocket） | 成功时 `[Provider] <name>'s content update`；无变化要 `level=debug` 才有 `content doesn't change` |
| `/connections` | 更新瞬间能看到 `process=mihomo`、目标为订阅域名的连接及其 `chains` |

## 手动触发

仓库内提供写操作脚本 `trigger_provider_update.py`，触发后会回查 `updatedAt` 与数量，确认是否真的生效：

```bash
python3 trigger_provider_update.py online-sub1 --secret '<secret>'  # 单个目标
python3 trigger_provider_update.py online-sub1,direct_domain --secret '<secret>' --dry-run  # 只预览
python3 trigger_provider_update.py --all --yes --secret '<secret>'  # 全部 HTTP 类型
python3 trigger_provider_update.py --all --kind proxy --yes --secret '<secret>'  # 只更新订阅节点
python3 trigger_provider_update.py --all --kind rule --yes --secret '<secret>'  # 只更新规则集
python3 trigger_provider_update.py online-sub1 --mode healthcheck --secret '<secret>'  # 只测速
python3 trigger_provider_update.py online-sub1 --secret '<secret>' --list  # 竖排明细，带 path
python3 trigger_provider_update.py online-sub1 --secret '<secret>' --summary  # 汇总：结果表 + 完成统计（不含 path）
python3 trigger_provider_update.py online-sub1 --secret '<secret>' --summary --list  # 汇总改竖排，带 path
```

退出码：`0` 全部成功、`1` 有失败目标、`2` 参数错误或目标无法解析。`--all` 必须配 `--yes`，且不能同时再给位置参数；默认处理订阅节点与规则集，加 `--kind proxy` 或 `--kind rule` 可收窄；`File` 类型自动跳过；规则集不支持 `healthcheck`。结果字段含 `name`、`kind`、`mode`、`status`、`before`、`after`、`count`、`path`、`fileExists`、`detail`；`--summary` 的结果表不显示路径，加 `--list` 可切成带路径的竖排；`--json` 始终带路径。同样支持 `--home-dir` / `--config-path` 指定。下面是等价的手工请求，便于在其他环境照做。

| 目的 | 请求 | 说明 |
| --- | --- | --- |
| 拉一次订阅 | `PUT /providers/proxies/<name>` | 立即下载并重建节点集合，返回 `204` |
| 拉一次规则集 | `PUT /providers/rules/<name>` | 重写对应缓存文件 |
| 只测速不更新 | `GET /providers/proxies/<name>/healthcheck` | 触发节点延迟测试，与订阅无关 |
| 单节点测速 | `GET /providers/proxies/<name>/proxies/<节点名>/healthcheck` | 节点名需 URL 编码 |
| 重载整份配置 | `PUT /configs?force=true`（`-d` 路径为 `path` 参数） | 改了 yaml 且不依赖 GUI 时使用 |

```bash
curl -i -X PUT -H "Authorization: Bearer <secret>" http://127.0.0.1:9097/providers/proxies/online-sub1
curl -i -X PUT -H "Authorization: Bearer <secret>" http://127.0.0.1:9097/providers/rules/direct_domain
```

```powershell
$h = @{ Authorization = 'Bearer <secret>' }
Invoke-WebRequest -Method Put 'http://127.0.0.1:9097/providers/proxies/online-sub1' -Headers $h
```

- `204` 只表示请求被受理，是否换了内容要看 `updatedAt`、节点数和日志
- 每次触发都是一次真实订阅请求，会消耗机场流量与请求次数
- 更新会 `version + 1` 并重建相关的 `load-balance` / `select` 组，正在使用这些组的连接可能受影响
- 规则集手动更新不会自动修复写错的 `behavior`，格式不匹配会解析失败并保留旧缓存

## 本机实测记录（2026-11-12，Windows + Clash Verge + mihomo v1.19.32）

运行时工作目录为 mihomo 的 `<HomeDir>`，`myprofiles` 是指向生成物目录的 Junction（本机当时指向仓库 `profiles/`）。生成物目录里的 `*.yaml` 与 Verge 用的副本不会自动同步：当天实测两者 SHA256 不同，运行态仍是旧版配置（`interval: 86400`、`IN-PORT` 规则）。

| 观测项 | 实测值 |
| --- | --- |
| `online-sub1`（当时叫 `xs`）更新前 | `updatedAt=2026/11/12 8:25:47`，63 个节点（其中 5 个是“剩余流量/套餐到期”这类信息节点） |
| 手动触发 `online-sub1` | `204`，耗时约 `1.5s`，`updatedAt` 变为 `8:54:25`，节点数不变 |
| `online-sub1` 缓存文件 | `proxies/<url 的 md5>`，mtime 随更新推进 |
| 订阅用量 | 上传、下载字节数随更新推进（含日常流量） |
| 订阅到期 | 响应头 `Expire` 字段，按秒级时间戳换算 |
| 本地 file provider（自建节点文件） | `updatedAt` 与本地文件 mtime 完全一致，说明启动后没有周期性重拉 |
| 手动触发本地 provider | `204`，`updatedAt` 立即变为请求时间 |
| 修改本地节点文件 mtime | 3 秒内 `updatedAt` 跟进到新 mtime，验证 `fswatch` 自动重载 |
| 规则集 | `direct_domain` 110189 条、`cn_ip` 9647 条、`private_domain` 132 条、`lan_ip` 28 条，均于当天 `8:32` 更新 |
| 更新链路 | `/connections` 捕获 `process=mihomo`，`chains` 为节点 ← `美国-LB` ← `PROXY`，`rule=Match` |
| 生成物与运行态 | 生成物改了不会自动生效，需在 GUI 重新应用；判断“当前跑哪一版”看 `clash-verge.yaml` 的 mtime 与其特征值 |

## 常见误解

| 说法 | 实际 |
| --- | --- |
| 不写 `proxy` 就是直连 | 本机实测经规则 `MATCH` 走了 `PROXY`；要确定就显式写 |
| 文件 mtime 没变就是没更新 | 内容 hash 未变时只刷新 `updatedAt`，文件可能不重写 |
| 改完 yaml 立刻生效 | GUI 客户端（如 Clash Verge）读的是它生成的运行时配置，需重新应用 profile |
| 改生成物 `*.yaml` 就能生效 | 那是模板生成物，要先改模板与清单再渲染；手改会被校验发现并要求 `--force` |
| 缓存文件可以随时拷走备份 | 写入不是原子的（先截断再写），更新进行中拷可能拿到半截文件 |
| 缓存文件一定在 `proxy_providers/` | 默认位置是 `proxies/<url 的 md5>`，`proxy_providers/` 可能只是历史残留 |
| provider 的 `filter` 能去掉信息节点 | 本仓库是在代理组上用 `exclude-filter` 过滤，provider 池里仍含信息节点 |
| `health-check.interval: 300` 就是每 5 分钟测全部节点 | `lazy` 默认 `true`，未被使用的节点不测 |
| `type: file` 也按 `interval` 定期重读 | 实际是文件监听，改动即重载；`interval` 对它不生效 |

## 验收清单

- 每个 `http` provider 都有明确的 `interval`，并知道这个数值对应多久
- 改订阅节奏走清单的 `subscriptions[].interval`（或默认值 `subscriptionInterval`），重新渲染后再在 GUI 重新应用
- 需要确定性链路的 provider 显式写了 `proxy`
- 换过订阅 URL 的 provider 检查过缓存文件是否顶替（必要时显式 `path` 并清旧缓存）
- 规则集有 `proxy`，且代理组在启动时可用，否则规则更新会静默失败
- 用 `/providers/proxies`、`/providers/rules` 的 `updatedAt` 判断新鲜度，不以文件 mtime 单独下结论
- 手动触发后核对 `updatedAt`、节点数、日志三者，再看业务侧是否要重新选节点
