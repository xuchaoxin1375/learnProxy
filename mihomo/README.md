[toc]

> 上级入口：[仓库根 README](../README.md)（脚本、模板与文档总索引）

## 这个目录是什么

mihomo（Clash.Meta 内核）的学习与运维笔记，覆盖从“订阅怎么变成可用代理池”到“规则、DNS、API 与排错”。所有文档按主题分了组，找不到入口时先看下面的按任务索引。

## 按任务找入口

| 想做的事 | 先看 |
| --- | --- |
| 第一次接触，先建立整体概念 | [mihomo概念学习指南](./mihomo概念学习指南.md)、[mihomo流量路由与配置入门](./mihomo流量路由与配置入门.md) |
| 从零配一份能用的订阅代理池 | [mihomo@基于订阅的代理池基础@最小可用配置](./mihomo@基于订阅的代理池基础@最小可用配置.md) |
| 按国家/地区自动分组，或做负载均衡 | [mihomo@基于模糊过滤规则自动分组代理组@按照代理所属国家分组](./mihomo@基于模糊过滤规则自动分组代理组@按照代理所属国家分组.md)、[mihomo@常见代理组(proxy-group)对比@创建负载均衡代理组(load-balance)@代理组的选中和使用](./mihomo@常见代理组%28proxy-group%29对比@创建负载均衡代理组%28load-balance%29@代理组的选中和使用.md) |
| 订阅多久更新一次、怎么核验、怎么手动触发 | [mihomo@订阅和规则集的自动更新@interval与手动触发@状态核验](./mihomo@订阅和规则集的自动更新@interval与手动触发@状态核验.md) |
| 改配置模板、生成多份 profile | [mihomo@配置模板与生成物@render-profile渲染与校验](./mihomo@配置模板与生成物@render-profile渲染与校验.md) |
| 改完配置却没生效 | [mihomo@配置读取机制和配置文件的布局](./mihomo@配置读取机制和配置文件的布局.md) 的案例一节 |
| 面板连不上、端口冲突、服务起不来 | [mihomo@运行状态检查@日志和故障排查@端口冲突问题](./mihomo@运行状态检查@日志和故障排查@端口冲突问题.md) |
| 用 API 或脚本控制内核 | [mihomo@api指南](./mihomo@api指南.md) |
| 跑仓库里的脚本：渲染、状态检查、手动更新 | [仓库根 README](../README.md) |
| 第一次从零部署多实例，按顺序走一遍 | [mihomo@新用户部署@从零到可用](./mihomo@新用户部署@从零到可用.md) |
| 后台多实例：启动、状态、停止 | [mihomo@后台服务多实例@启动状态停止](./mihomo@后台服务多实例@启动状态停止.md) |

## 入门与配置基础

| 文档 | 内容 |
| --- | --- |
| [mihomo概念学习指南](./mihomo概念学习指南.md) | 术语、配置块职责与整体结构 |
| [mihomo流量路由与配置入门](./mihomo流量路由与配置入门.md) | 一份请求从入站到出站经过哪些层 |
| [mihomo代理配置指南](./mihomo代理配置指南.md) | 节点字段与常见配置项速查 |
| [mihomo@典型配置说明](./mihomo@典型配置说明.md) | 典型配置块示例与取舍说明 |
| [mihomo@基于订阅的代理池基础@最小可用配置](./mihomo@基于订阅的代理池基础@最小可用配置.md) | 订阅 → provider → 分组 → 规则的最小闭环 |
| [常见代理内核对比@Xray@sing-box@mihomo](./常见代理内核对比@Xray@sing-box@mihomo.md) | 三个内核的定位与差异 |
| [将一个节点转换应用于Xray和mihom(clash)客户端](./将一个节点转换应用于Xray和mihom%28clash%29客户端.md) | 分享链接字段如何映射成节点配置 |
| [sub-store节点和订阅管理和转换指南](./sub-store节点和订阅管理和转换指南.md) | 订阅集中管理与格式转换 |

## 配置读取与生成

| 文档 | 内容 |
| --- | --- |
| [mihomo@配置读取机制和配置文件的布局](./mihomo@配置读取机制和配置文件的布局.md) | HomeDir、启动参数、相对路径基准、改动为何不生效 |
| [mihomo@配置覆写](./mihomo@配置覆写.md) | 覆写与合并的层级 |
| [mihomo@配置模板与生成物@render-profile渲染与校验](./mihomo@配置模板与生成物@render-profile渲染与校验.md) | 模板 + `profiles.json` 渲染产物、指纹校验、收录规则 |

## 入站与工作模式

| 文档 | 内容 |
| --- | --- |
| [mihomo@入站和listeners](./mihomo@入站和listeners.md) | 端口、`listeners`、按入站分流 |
| [mihomo@工作模式(mode)说明@GLOBAL分组说明](./mihomo@工作模式%28mode%29说明@GLOBAL分组说明.md) | `rule` / `global` / `direct` 的差异 |

## 出站、分组与节点池

| 文档 | 内容 |
| --- | --- |
| [mihomo@代理组和代理集合(proxy-provider)对比](./mihomo@代理组和代理集合%28proxy-provider%29对比.md) | 节点来源与使用策略的分工 |
| [mihomo@常见代理组(proxy-group)对比@创建负载均衡代理组(load-balance)@代理组的选中和使用](./mihomo@常见代理组%28proxy-group%29对比@创建负载均衡代理组%28load-balance%29@代理组的选中和使用.md) | `select` / `url-test` / `fallback` / `load-balance` |
| [mihomo@基于模糊过滤规则自动分组代理组@按照代理所属国家分组](./mihomo@基于模糊过滤规则自动分组代理组@按照代理所属国家分组.md) | 用正则按国家聚合节点 |
| [mihomo节点代理池方案](./mihomo节点代理池方案.md) | 代理池的组织方式与取舍 |
| [分组和节点切换/mihomo@代理节点的选择工作机制](./分组和节点切换/mihomo@代理节点的选择工作机制.md) | 组内选择与切换的机制 |
| [分组和节点切换/mihomo@选中节点的方式说明](./分组和节点切换/mihomo@选中节点的方式说明.md) | 面板与 API 中选中节点的区别 |
| [分组和节点切换/mihomo@linux系统上的系统代理设置和代理组节点切换](./分组和节点切换/mihomo@linux系统上的系统代理设置和代理组节点切换.md) | Linux 下的系统代理与切换 |

## 规则、DNS 与 Geo

| 文档 | 内容 |
| --- | --- |
| [mihomo@路由规则(rule)](./mihomo@路由规则%28rule%29.md) | 规则类型、顺序与匹配 |
| [mihomo@规则集(rule-providers)](./mihomo@规则集%28rule-providers%29.md) | `behavior` / `format` / 更新与缓存 |
| [mihomo@分流方案@国内直连白名单@mrs](./mihomo@分流方案@国内直连白名单@mrs.md) | 用 `.mrs` 规则库落地“国内直连、其余代理” |
| [mihomo@分流方案@国内直连白名单@Loyalsoldier](./mihomo@分流方案@国内直连白名单@Loyalsoldier.md) | 同一思路的 Loyalsoldier txt 版本 |
| [mihomo@DNS层处理机制](./mihomo@DNS层处理机制.md) | DNS 解析流程与 fake-ip 等模式 |
| [DoH和DoT](./DoH和DoT.md) | 加密 DNS 的配置与差异 |
| [Geox@GeoIP@Geosite](./Geox@GeoIP@Geosite.md) | Geo 数据来源、匹配器与更新 |

## API 与运维

| 文档 | 内容 |
| --- | --- |
| [mihomo@api指南](./mihomo@api指南.md) | 外部控制 API 全量清单与示例 |
| [mihomo@外部控制和跨域请求开放配置](./mihomo@外部控制和跨域请求开放配置.md) | 解读 Verge 生成物的管理入口与安全边界（CORS 细节在 API 篇） |
| [mihomo@客户端和外部控制api监听端口问题排查](./mihomo@客户端和外部控制api监听端口问题排查.md) | 面板连不上、端口占用 |
| [mihomo@命令行@启动参数与进程取证](./mihomo@命令行@启动参数与进程取证.md) | 启动参数、运行模型与进程文案取证 |
| [mihomo@运行状态检查@日志和故障排查@端口冲突问题](./mihomo@运行状态检查@日志和故障排查@端口冲突问题.md) | 分层状态检查与常见故障 |
| [mihomo@订阅和规则集的自动更新@interval与手动触发@状态核验](./mihomo@订阅和规则集的自动更新@interval与手动触发@状态核验.md) | 更新排期、缓存位置、核验与手动触发 |

## 配套脚本

| 脚本 | 职责 | 读写行为 |
| --- | --- | --- |
| [`render_profile.py`](../render_profile.py) | 从 `templates/` 渲染 profile、指纹校验、位置参数/`--from` 另存、`--manifest` 本地清单、`--list` 清单、可选跑 `mihomo -t` | 默认写 `~/Desktop/mihomo-profiles/*.generated.yaml`；无桌面目录时回退 `~/mihomo-profiles` |
| [`check_provider_status.py`](../check_provider_status.py) | 竖排明细（新鲜度、过期标记、缓存路径），`--summary` 出汇总表 | 只读，仅 `GET` 与本地文件检查 |
| [`trigger_provider_update.py`](../trigger_provider_update.py) | 手动触发订阅或规则集更新、单 provider 测速 | 写操作，会真实下载 |
| [`mihomo_provider.py`](../mihomo_provider.py) | 上面两个 provider 脚本共用的 API、路径与运行时定位 | 只读工具模块 |

模板与值文件在 `templates/`（`spider_lb.template.yaml`、`spider_lb.profiles.json`），产物默认在 `~/Desktop/mihomo-profiles`（无桌面目录时回退 `~/mihomo-profiles`），可用清单里的 `outputDir` 覆盖。真实订阅不要写进公开的 `spider_lb.profiles.json`：复制成 `templates/spider_lb.profiles.local.json` 再改，脚本会优先读取；也可以用 `--manifest` 指定其他位置。自建节点文件不随仓库提供；需要本地使用时把节点 YAML 放进未入库目录（例如仓库根的 `profiles/`；相关文件名已在 `.gitignore` 中），模板里只保留注释示例。

三个脚本只依赖 Python 3.10+ 标准库，Windows / Linux / macOS 通用；文档命令以 Linux/macOS 的 `python3` 为例，Windows 把 `python3` 换成 `python`。

两个 provider 脚本默认输出竖排明细（含 `path` / `fileExists`），`--summary` 才打印人看的汇总表（不含路径），`--list` 可强制竖排并用于把汇总表切成带路径的列表。路径按运行中内核的 `-d` / `-f` 自动定位工作目录与配置文件，也可用 `--home-dir` / `--config-path` 或环境变量 `MIHOMO_HOME` / `MIHOMO_CONFIG` 覆盖；`--json` 始终带路径。

## 约定

- 带 `.generated.yaml` 后缀的配置是脚本产物，不要手改；改模板与清单后重新渲染。默认输出在仓库外，若把 `outputDir` 指回仓库，`.gitignore` 仍会忽略这类文件
- 文档里的路径是示例，`-d`/`-f` 以本机实际工作目录为准
- 命令示例中的 `<secret>`、`/path/to/...` 是占位，不要直接照抄
