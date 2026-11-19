[toc]

## 这个仓库是什么

本仓库是 mihomo（Clash.Meta）的配置与学习工作区，包含三层内容：

- 配置生成：`templates/` 里的模板与 `profiles.json` 生成多份爬虫配置
- provider 运维：只读检查订阅 / 规则集新鲜度，必要时手动触发更新
- 学习笔记：`mihomo/` 下的机制说明、排错手册与实测记录

脚本只依赖 Python 3.10+ 标准库，Windows / Linux / macOS 通用。下面命令以仓库根目录为当前目录，Windows 把 `python3` 换成 `python`。

## 快速开始

```bash
python3 render_profile.py --list        # 看输出目录、已定义 profile 与产物状态
python3 render_profile.py --check       # 与模板比对；首次未生成也返回 3
python3 render_profile.py --check --allow-missing   # 只关心漂移，未生成不算失败
python3 render_profile.py --dry-run     # 只看会写哪些文件
python3 render_profile.py               # 渲染全部
python3 render_profile.py --test --mihomo-home <HomeDir>   # 渲染后跑 mihomo -t

python3 mihomo_instance.py validate --config <config.yaml> --mihomo <mihomo>
python3 mihomo_instance.py start --config <config.yaml> --home <实例目录> --mihomo <mihomo>
python3 mihomo_instance.py status --home <实例目录>
python3 mihomo_instance.py stop --home <实例目录>

python3 check_provider_status.py --secret '<secret>' --summary
python3 trigger_provider_update.py <provider> --dry-run
```

`templates/spider_lb.profiles.json` 里的订阅地址是占位符。要填真实订阅，先复制本地骨架再改：

```bash
cp templates/spider_lb.profiles.local.example.json templates/spider_lb.profiles.local.json
# 编辑 templates/spider_lb.profiles.local.json 里的 subscriptions
```

`templates/spider_lb.profiles.local.json` 已被 `.gitignore` 忽略；脚本默认优先读取它，没有时回退到 `templates/spider_lb.profiles.json`。也可以把骨架复制到桌面或任意私有目录，用 `--manifest /path/to/private.json` 指定，避免真实订阅留在仓库工作区：

```bash
cp templates/spider_lb.profiles.local.example.json ~/Desktop/spider_lb.profiles.local.json
python3 render_profile.py --manifest ~/Desktop/spider_lb.profiles.local.json
```

不要编辑 `~/Desktop/mihomo-profiles/*.generated.yaml`：那是渲染产物，手改会被指纹校验拒绝覆盖；真实订阅只写私有清单。

改了模板或清单后重新渲染；默认生成到 `~/Desktop/mihomo-profiles`（没有 `Desktop` 目录时回退 `~/mihomo-profiles`），`--list` / `--dry-run` 会打印实际输出目录。生成物不会自动同步到 Clash Verge，仍需在 GUI 里重新应用当前 profile。

## 脚本职责

| 路径 | 职责 | 读写行为 |
| --- | --- | --- |
| `render_profile.py` | 从模板与 `profiles.json`（或 `--manifest` 指定的本地清单）渲染 profile，指纹校验，`--manifest` / `--list` / `--print` / `--check` / `--test` | 默认写 `~/Desktop/mihomo-profiles/*.generated.yaml`；无桌面目录时回退 `~/mihomo-profiles` |
| `mihomo_instance.py` | 校验、启动、查看和停止独立 mihomo 实例；PID 文件与日志落在实例目录 | 写实例目录；只停自己 PID 文件记录的进程，不按进程名清理 |
| `check_provider_status.py` | 检查 proxy-provider / rule-provider 新鲜度、订阅用量、缓存路径 | 只读，仅 `GET` 与本地文件检查 |
| `trigger_provider_update.py` | 手动触发订阅或规则集更新、单 provider 测速 | 写操作，会真实下载并消耗流量 |
| `mihomo_provider.py` | 上面脚本共用的 API、运行时定位、缓存路径、输出格式化 | 工具模块，不单独运行 |
| `tests/` | 渲染状态机、端口校验、provider 解析等单元测试 | 只读，使用标准库 `unittest` |

两个 provider 脚本默认输出竖排明细（含 `path` / `fileExists`），`--summary` 换成汇总表，`--json` 供其他脚本消费。`--all` 属于批量写操作，必须再加 `--yes`，或先用 `--dry-run` 预览。

## 退出码

三个 CLI 脚本使用同一套约定，便于包装成巡检或 CI：

| 退出码 | 含义 | 典型触发 |
| --- | --- | --- |
| `0` | 成功 | 渲染完成、检查通过、更新成功 |
| `1` | 运行或配置解析失败 | API 不可达、模板 / JSON 解析失败、`mihomo -t` 失败、目标更新失败 |
| `2` | 用法错误 | 参数冲突、缺前置条件、未知目标、参数值不合法 |
| `3` | 状态差异或需要人工处理 | `--check` 发现差异、产物被手改、未生成（除非加 `--allow-missing`）、provider 过期、`--require-providers` 没有 provider |

`render_profile.py --test` 需要 `--mihomo-home` 或 `MIHOMO_HOME`；缺少时返回 `2`，不会假装校验通过。

## 目录结构

```text
.
├─ README.md                  本页，脚本与文档总入口
├─ LICENSE                    MIT 许可证
├─ .gitignore                 忽略生成物、本地节点与密钥
├─ render_profile.py          配置渲染
├─ mihomo_instance.py         独立实例校验 / 启动 / 状态 / 停止
├─ check_provider_status.py   只读状态检查
├─ trigger_provider_update.py 手动更新 / 测速
├─ mihomo_provider.py         共用工具模块
├─ ruff.toml                  Python 3.10+ 的 lint 配置
├─ templates/
│  ├─ spider_lb.template.yaml 配置正文与占位符
│  ├─ spider_lb.profiles.json 产物差异值与在线订阅（占位）
│  └─ profiles/               历史模板与官方示例
├─ tests/                     单元测试
├─ 自建代理节点/              自建节点搭建记录
└─ mihomo/                    mihomo 学习与运维笔记
```

脚本默认把生成物写到 `~/Desktop/mihomo-profiles`，没有 `Desktop` 目录时回退 `~/mihomo-profiles`；`--list` / `--dry-run` 会打印实际输出目录。需要固定到别处时，在清单里写 `outputDir`（支持 `~`、绝对路径或相对 `templates/` 的路径）。旧产物不会自动搬移，需要时手动移动或用 `outputDir` 指回旧目录。`templates/spider_lb.profiles.local.json` 是本地私有清单，已被 `.gitignore` 忽略，不随仓库提供。`templates/profiles/` 里是历史模板与官方示例（如 `mihomo.template.yaml`、`proxy_full_template.yaml`），当前渲染链路只读 `templates/spider_lb.template.yaml`，改模板时不要改错文件。

自建节点文件不随仓库提供。需要接回本地节点时，把节点 YAML 放到本地未入库目录（例如仓库根的 `profiles/`，需要时新建；相关文件名已在 `.gitignore` 中），再按 `templates/spider_lb.template.yaml` 里的注释示例启用本地 provider，最后在 GUI 里重新应用配置。模板与示例文件里的 IP、UUID、Reality 密钥与密码都只是占位示例。

## 多实例：轮询与粘性并存

同一台机可以同时跑 Clash Verge 和一个独立 mihomo 实例；关键是管理端口和入口端口都不能撞。当前模板的端口分工：

| 实例 | 管理端口 | 业务入口 | 策略 | 典型用途 |
| --- | --- | --- | --- | --- |
| A：Clash Verge | `7897` / `9097` | `171xx` | `round-robin` | 429、Shopify `/products.json` 等需要轮换 IP 的任务 |
| B：独立 mihomo | `17897` / `19097` | `172xx` | `consistent-hashing` | 反爬/会话站，同一目标固定出口 |
| B：独立 mihomo | `17997` / `19197` | `173xx` | `sticky-sessions` | 10 分钟会话粘性；按需使用 |

- `spider_lb_ch.generated.yaml` 是 172xx + `consistent-hashing`，管理端口 17897/19097。
- `spider_lb_sticky.generated.yaml` 是 173xx + `sticky-sessions`，管理端口 17997/19197。
- `default.generated.yaml` 对应 A（7897/9097）；已有 Clash Verge 时不要再启动它，避免端口冲突。
- 爬虫侧：A 用 `http://127.0.0.1:17111`（美国轮询），B 用 `http://127.0.0.1:17211`（美国粘性）或 `http://127.0.0.1:17311`（美国会话粘性）；`+0` 的 `17100/17200/17300` 是不分国家的 all 入口。
- 两份 B 配置不要同时启动，除非你把 `external-controller-pipe` 也改成不同名字；它们共用模板里的 pipe。
- 只有 A 开 TUN；B 的 `tun.enable` 保持 `false`。
- 每份 B 配置用独立 `--home`，不要和 Clash Verge 的 `-d` 共用。
- `mihomo_instance.py stop` 只停自己 PID 文件里的进程，不会碰 Clash Verge 的内核。

## 文档入口

| 想了解 | 先看 |
| --- | --- |
| 所有 mihomo 笔记的按任务索引 | [mihomo/README.md](./mihomo/README.md) |
| 模板、`profiles.json`、端口方案、渲染与校验 | [mihomo@配置模板与生成物@render-profile渲染与校验](./mihomo/mihomo@配置模板与生成物@render-profile渲染与校验.md) |
| 订阅多久更新、缓存在哪、怎么手动触发 | [mihomo@订阅和规则集的自动更新@interval与手动触发@状态核验](./mihomo/mihomo@订阅和规则集的自动更新@interval与手动触发@状态核验.md) |
| 改了配置却没生效 | [mihomo@配置读取机制和配置文件的布局](./mihomo/mihomo@配置读取机制和配置文件的布局.md) |
| 面板连不上、端口冲突、服务起不来 | [mihomo@运行状态检查@日志和故障排查@端口冲突问题](./mihomo/mihomo@运行状态检查@日志和故障排查@端口冲突问题.md) |
| 用 API 或脚本控制内核 | [mihomo@api指南](./mihomo/mihomo@api指南.md) |
| 自建节点搭建记录 | [自建代理节点/一键搭建节点proxy.md](./自建代理节点/一键搭建节点proxy.md) |

各脚本的 `--help` 也列了参数默认值、互斥关系与退出码，可以先用它查当前版本支持什么。

## 数据与安全

- 本仓库按公开仓库组织：`templates/spider_lb.profiles.json` 只保留占位订阅地址；真实订阅写到本地清单（`templates/spider_lb.profiles.local.json` 或 `--manifest` 指定的文件），节点 IP、UUID、Reality 密钥和密码也不要提交。
- 生成的配置含订阅地址与节点信息，默认在桌面；不要为了备份把它复制回仓库，也不要用 `git add -f` 强行加入被忽略的产物。
- 如果曾把真实凭据提交到公开仓库，先轮换订阅地址和节点密钥；删除文件或清理历史不等于凭据已经安全。
- 模板默认 `external-controller: 127.0.0.1:9097` 与 `secret: '1'`，只适合本机使用。需要局域网面板时，同时改监听地址和 secret，不要只开 `allow-lan`。
- `--secret ''` 表示不带鉴权头；不传时才回落到 `MIHOMO_SECRET`，最后才是模板默认值。
- `trigger_provider_update.py` 每次 update 都会真实下载订阅或规则集，批量执行前先用 `--dry-run` 看清单。

## 开发与验证

```bash
python3 -m unittest discover -s tests          # 全部单元测试
ruff check .
pyright render_profile.py mihomo_instance.py mihomo_provider.py check_provider_status.py trigger_provider_update.py tests
```

当前没有配置 CI；提交前至少跑一遍上面的测试，并在渲染后跑 `python3 render_profile.py --check`。

## 许可证

MIT，见 [LICENSE](./LICENSE)。

## 不适用场景

- 不负责安装 mihomo、Clash Verge 或机场订阅，只处理已经存在的配置与运行态。
- 不把生成物自动推送到 GUI；应用配置仍需在客户端里完成。
- 不是订阅计费工具，`subscriptionInfo` 只反映订阅响应头里的用量，不是实时账单。
