[toc]

## 为什么要模板加生成物

**一份模板加一份值文件，渲染出多份 profile；生成物头部带正文指纹，`--check` 能同时发现“被手改”和“模板改了没重新渲染”，避免多份配置长期漂移。**

本仓库的爬虫配置现在是这条链路：

```text
templates/spider_lb.template.yaml          配置正文 + 占位符 + 生成标记
templates/spider_lb.profiles.json          每份产物的差异值 + 在线订阅表（占位）
templates/spider_lb.profiles.local.json    可选本地私有清单，存在时优先（不提交）
            │
            ▼  render_profile.py
~/Desktop/mihomo-profiles/default.generated.yaml        生成物，头部有修订日期与生成指纹
~/Desktop/mihomo-profiles/spider_lb_robin.generated.yaml 生成物
~/Desktop/mihomo-profiles/spider_lb_ch.generated.yaml   生成物
~/Desktop/mihomo-profiles/spider_lb_sticky.generated.yaml 生成物
（没有 Desktop 目录时回退 ~/mihomo-profiles）
            │
            ▼  在 GUI 里重新应用 profile
Clash Verge 的 profiles/<uid>.yaml → clash-verge.yaml → 内核实际加载
```

脚本已从 PowerShell 迁到 Python，三个工具都只依赖标准库，Windows / Linux / macOS 通用：

```text
render_profile.py          渲染、指纹校验、--list / --print / --test
check_provider_status.py   只读检查 provider 新鲜度
trigger_provider_update.py 手动触发 provider 更新或测速
mihomo_provider.py         上述脚本共用的 API、路径与运行时定位
```

下面命令以 Linux/macOS 的 `python3` 为例；Windows 把 `python3` 换成 `python`。

## 文件职责

| 路径 | 角色 | 能否手改 |
| --- | --- | --- |
| `templates/spider_lb.template.yaml` | 配置正文，含 `{{...}}` 占位符与生成标记 | 改这里 |
| `templates/spider_lb.profiles.json` | 公开的 `defaults` + 每份产物的订阅、端口、策略（订阅为占位） | 改结构或占位值 |
| `templates/spider_lb.profiles.local.example.json` | 本地私有清单骨架：三套后台服务 profile、default 和管理端口、订阅占位符 | 复制成 `.local.json` 后再填真实订阅 |
| `templates/spider_lb.profiles.local.json` | 可选的本地私有清单，放真实订阅；已被 `.gitignore` 忽略 | 本地改这里，不提交 |
| `<输出目录>/default.generated.yaml`、`spider_lb_robin.generated.yaml`、`spider_lb_ch.generated.yaml`、`spider_lb_sticky.generated.yaml` | 生成物，头部有修订日期与 `# 生成指纹:sha256:...`；`<输出目录>` 默认是 `~/Desktop/mihomo-profiles`，无桌面目录时是 `~/mihomo-profiles` | 不要手改，会被覆盖或触发 `--force` 要求 |
| `render_profile.py` | 渲染、指纹校验、可选跑 `mihomo -t` | 工具本身 |
| `mihomo_instance.py` | 校验、启动、查看和停止独立 mihomo 实例；PID 文件与日志落在实例目录 | 只停自己 PID 文件记录的进程 |

生成物头部由脚本写入：修订日期、用途说明、profile 描述、生成来源（脚本路径与 `profiles.json` 里的 `template`）、正文指纹。指纹是**正文的 SHA256**，用来判断产物是否被手改过；生成来源也从 `template` 推导，换模板后不会继续写旧文件名。

## 产物命名与输出位置

默认输出目录是 `~/Desktop/mihomo-profiles`；`~/Desktop` 不存在时回退到 `~/mihomo-profiles`。需要固定到别处时，在 `profiles.json` 写 `outputDir`：

- `"outputDir": "~/mihomo-profiles"`：家目录下的子目录
- `"outputDir": "D:/mihomo-profiles"`：绝对路径
- `"outputDir": "../profiles"`：相对 `templates/`，也就是仓库根下的 `profiles/`

已有产物不会自动搬移：旧版本放在仓库 `profiles/` 的文件需要手动移到新目录，或用 `outputDir` 指回旧目录。

产物文件名建议带 `.generated` 标记（`<输出目录>/<name>.generated.yaml`）。默认输出在仓库外，不依赖忽略规则；如果 `outputDir` 指回仓库，`.gitignore` 里的 `*.generated.*` 仍会忽略它们：

```gitignore
# 脚本生成的配置产物(头部带生成指纹),由 render_profile.py 从 templates/ 重新渲染,不入库
*.generated.*
```

生成物不入库的原因：

- 生成物可从模板随时重建，入库只会制造合并冲突和“改了产物却没改模板”的漂移
- 新增 profile（`profiles.json` 里加一项）自动被忽略，不用再改 `.gitignore`
- 是否生成物有两个独立证据：文件名后缀 `.generated.yaml`，以及文件头 `# 生成指纹:sha256:...`

判断某个文件是否真的由脚本生成，用 `python3 render_profile.py --check`：与模板一致退出 `0`，手改、过期或缺失退出 `3`。首次生成前只关心漂移，可加 `--allow-missing`，让“未生成”不算失败；手改或过期仍然退出 `3`。`--list` 与 `--dry-run` 会先打印实际输出目录。

## 本地私有清单

公开仓库里的 `spider_lb.profiles.json` 只放占位订阅。需要真实订阅时，复制一份本地清单再改：

```bash
cp templates/spider_lb.profiles.json templates/spider_lb.profiles.local.json
# 编辑 templates/spider_lb.profiles.local.json 里的 subscriptions
python3 render_profile.py --manifest templates/spider_lb.profiles.local.json
```

清单选择顺序：

- `--manifest <文件>`：显式指定，优先于自动发现；相对路径按当前目录解析，支持 `~` 与环境变量。
- `templates/spider_lb.profiles.local.json`：存在时自动使用，不需要额外参数。
- `templates/spider_lb.profiles.json`：没有本地清单时的公开模板。

使用非公开清单时，脚本会在 stderr 打印 `[清单] <路径>`，避免改了本地文件却以为还在用公开文件。`templates/*.local.json` 已被 `.gitignore` 忽略；不要用 `git add -f` 强行加入。

`template` 字段仍然只允许写 `templates/` 下的文件名，`outputDir` 的相对路径也仍按 `templates/` 解析，与清单文件放在哪里无关。要完全放到仓库外，用绝对 `outputDir`。

## 模板里的占位符

| 占位符 | 来源字段 | 用在哪 |
| --- | --- | --- |
| `{{PROXY_PROVIDERS}}` | `subscriptions` | `proxy-providers` 里的在线订阅块，按订阅表循环生成 |
| `{{USE_PROVIDERS}}` | `subscriptions` | `use-providers` 里的在线订阅条目；接入本地 provider 时再手动追加 |
| `{{STRATEGY}}` | `strategy` | `com_proxy_group.strategy`（`round-robin` / `consistent-hashing` / `sticky-sessions`） |
| `{{MIXED_PORT}}` | `mixedPort` | 顶层 `mixed-port`；多实例时每份必须不同 |
| `{{EXTERNAL_CONTROLLER_PORT}}` | `externalControllerPort` | 顶层 `external-controller` 端口；多实例时每份必须不同 |
| `{{PORT_ALL}}` `{{PORT_EU}}` | `portAll` / `portEu` | 两个地区级入口 |
| `{{PORT_US}}` `{{PORT_JP}}` `{{PORT_HK}}` `{{PORT_SG}}` `{{PORT_DE}}` `{{PORT_FR}}` `{{PORT_TH}}` `{{PORT_RU}}` `{{PORT_TW}}` `{{PORT_UK}}` | 由 `portEu` 起按 `countryOrder` 连号推导 | 国家级入口（默认十个，uk 同列） |

两个生成标记必须**各出现一次且独占一行**，标记行自身的缩进决定生成块的缩进。模板还要求保留 `provider-com: &pc` 锚点，生成的 provider 块用 `<<: *pc` 复用健康检查配置。缺少标记或锚点会直接报错，避免订阅被静默丢掉。

端口推导规则：`portEu` 起按 `countryOrder`（缺省是 us/jp/hk/sg/de/fr/th/ru/tw/uk）**连续 +1 分配**，uk 也是普通国家，没有单独的端口字段。模板里出现哪些 `{{PORT_*}}`，配置里就必须提供对应的端口键，反过来也一样，少一个或多一个都会报错。同一 profile 内端口不得重复，也不能占用模板自身的端口或常见软件默认端口（见下一节）。

## profiles.json 结构

```json
{
  "template": "spider_lb.template.yaml",
  "defaults": {
    "description": "默认配置:入口 171xx,按连接轮询换出口",
    "subscriptions": {
      "online-sub1": { "url": "https://..." }
    },
    "subscriptionInterval": 43200,
    "portAll": 17100,
    "portEu": 17110,
    "mixedPort": 7897,
    "externalControllerPort": 9097,
    "strategy": "round-robin"
  },
  "profiles": [
    { "name": "default.generated.yaml" },
    {
      "name": "spider_lb_robin.generated.yaml",
      "description": "后台服务 A:入口 171xx,按连接轮询换出口",
      "portAll": 17100,
      "portEu": 17110,
      "mixedPort": 17797,
      "externalControllerPort": 18997,
      "strategy": "round-robin"
    },
    {
      "name": "spider_lb_ch.generated.yaml",
      "description": "对齐版本:入口 172xx,同一目标固定出口",
      "subscriptions": {
        "online-sub1": { "url": "https://..." }
      },
      "portAll": 17200,
      "portEu": 17210,
      "mixedPort": 17897,
      "externalControllerPort": 19097,
      "strategy": "consistent-hashing"
    },
    {
      "name": "spider_lb_sticky.generated.yaml",
      "description": "会话粘性版本:入口 173xx,同一来源+目标 10 分钟粘性",
      "portAll": 17300,
      "portEu": 17310,
      "mixedPort": 17997,
      "externalControllerPort": 19197,
      "strategy": "sticky-sessions"
    }
  ]
}
```

省略 `outputDir` 时使用默认输出目录；要固定位置就加上该字段，写法见上一节。这份文件只放占位值；真实订阅写到本地私有清单，见上一节。

`defaults` 就是默认配置本身；`default.generated.yaml` 只写 `name`，其余全部继承。其它条目写哪个字段就覆盖哪个，没写的仍来自 `defaults`。覆盖是**顶层整字段替换**：`subscriptions`、`ports`、`countryOrder` 一旦重写就整块替换，不与 `defaults` 里的同名对象深合并。省略输出名时渲染 `profiles` 里的全部条目，不会只渲染第一条。

位置参数只表示**输出名**，`--from` 只表示**内容来源**，两件事分开。名称解析顺序：已定义全名 → 去掉 `.generated.yaml` / `.yaml` 的短名 → 视为新输出名。新输出名默认补 `.generated.yaml`，内容取 `--from`，没给就用 `defaults`；显式写 `.yaml`（如 `probe.yaml`）则按原样落盘。默认输出在仓库外，不会误提交；如果 `outputDir` 指回仓库，不带 `.generated` 的文件会收到提示。

短名必须唯一：同时定义 `x.yaml` 与 `x.generated.yaml` 时，`x` 无法决定指向哪一份，脚本会直接报错，而不是静默选第一个。`--list` 也会跑与渲染相同的字段校验，字段名写错不会等到真正渲染才暴露。

```bash
python3 render_profile.py                          # 渲染已定义的全部
python3 render_profile.py default                  # 短名：default.generated.yaml
python3 render_profile.py crawler                  # 新输出：crawler.generated.yaml，内容同 default
python3 render_profile.py crawler --from spider_lb_ch   # 内容用 ch，存成 crawler
python3 render_profile.py probe.yaml               # 显式 .yaml，按原样存
```

| 字段 | 说明 | 适用模式 |
| --- | --- | --- |
| `template` / `outputDir` | 模板文件名与产物目录。`outputDir` 省略时用 `~/Desktop/mihomo-profiles`（无桌面目录回退 `~/mihomo-profiles`）；支持 `~`、绝对路径，或相对 `templates/` 的路径 | 全局 |
| `defaults` | 基础配置：可放除 `name` 外的任意字段（含 `subscriptions`）；条目只写 `name` 即继承整份，写了哪个字段就整块覆盖哪个（数组与 `ports` 表整体替换，不深合并） | 全局（可选） |
| `name` | 产物文件名**含 `.yaml` 后缀**，脚本原样落盘，也是位置参数的选择键（全名或短名）；建议带 `.generated` 标记（如 `default.generated.yaml`）；只有 `outputDir` 指回仓库时才依赖 `.gitignore` 的忽略规则 | 全局 |
| `description` | 写进产物头部的用途说明 | 全局 |
| `subscriptions` | provider 名 → `{ url, interval?, filter?, exclude-filter?, proxy?, path? }`；至少一项，增删订阅只改这里 | 全局 |
| `subscriptionInterval` | 订阅更新周期（秒）默认值，供没写 `interval` 的订阅使用，适合放 `defaults` | 全局 |
| `strategy` | 负载均衡策略，决定同组内按连接轮换还是固定出口 | 全局 |
| `mixedPort` / `externalControllerPort` | 顶层 `mixed-port` 与 `external-controller` 端口；多实例时每份必须不同 | 全局（默认 7897/9097） |
| `portAll` / `portEu` | 两个地区入口，`portEu` 同时是国家端口的起点 | 连号（默认）；模板里有对应占位符时必填 |
| `countryOrder` | 国家顺序，缺省 us/jp/hk/sg/de/fr/th/ru/tw/uk | 连号（默认）；可选，新增国家追加到末尾 |
| `ports` | 显式端口表，键为占位符后缀小写（`all`/`eu`/`us`…） | 显式（可选）；与 `portAll`/`portEu`/`countryOrder` 互斥 |
| `allowCommonPorts` | 允许入口使用常见软件默认端口 | 两种模式；默认 `false` |

字段名写错会直接报错并列出可用字段，避免拼错的键被当成“继承默认值”。看每份 profile 实际覆盖/继承了哪些字段、启用了哪些订阅：

```bash
python3 render_profile.py --list
```

## 多路在线订阅

`subscriptions` 是映射而不是单个 `url`，数量随加随删，模板不用改。比如再加一路订阅：

```json
"subscriptions": {
  "online-sub1": { "url": "https://..." },
  "online-sub2": {
    "url": "https://...",
    "interval": 21600,
    "filter": "(?i)(US|JP)",
    "exclude-filter": "(?i)(官网|剩余流量)"
  }
}
```

渲染后会生成对应的 provider 块，并自动进入 `use-providers`：

```yaml
proxy-providers:
  online-sub1:
    type: http
    url: "https://..."
    proxy: PROXY
    <<: *pc
    # 覆盖锚点的 86400;订阅约每 12 小时拉一次
    interval: 43200
  online-sub2:
    type: http
    url: "https://..."
    proxy: PROXY
    <<: *pc
    filter: '(?i)(US|JP)'
    exclude-filter: '(?i)(官网|剩余流量)'
    # 覆盖锚点的 86400;订阅约每 6 小时拉一次
    interval: 21600
```

约定与坑：

- provider 名用小写字母、数字、`_`、`-`，它同时是 `/providers/proxies/<name>` 的运行时身份，换机场时只改 `url`，不动分组和规则
- `proxy` 默认 `PROXY`；`path` 省略时缓存按 URL 的 md5 存放，换订阅链接等于换缓存
- `filter` / `exclude-filter` 由脚本加单引号，正则里的 `\b` 不会被 YAML 双引号吃成退格符；字符串里的单引号会自动转义
- 两个 URL 指向同一机场同一订阅时节点会重复进 LB 组，流量权重被放大
- 新增订阅后确认 `provider-com` 锚点仍在模板里，否则 `<<: *pc` 无处可依，脚本会报错

## 端口编号方案

每份 profile 独占一个 100 端口 band，band 内按固定偏移分配，新增国家不动已有端口：

| 偏移 | 用途 | 主配置 | 对齐版 | 会话粘性版 |
| --- | --- | --- | --- | --- |
| `+0` | `all`，不区分国家 | 17100 | 17200 | 17300 |
| `+1`..`+9` | 预留给新的地区组 | — | — | — |
| `+10` | `eu`，欧洲组，同时是国家连号起点 | 17110 | 17210 | 17310 |
| `+11`..`+89` | 国家入口（含 uk），按 `countryOrder` 连号 | 17111-17120 | 17211-17220 | 17311-17320 |
| `+90`..`+99` | 预留给额外入口 | — | — | — |

选 1xxxx 的原因：避开 7890-7899（Clash/mihomo 客户端）、9090/9091/9097（API）、1080/1081/10808-10810 等常见端口，也低于系统临时端口区间（Windows 49152+、Linux 32768+）。每段留 79 个国家位，当前用 10 个（含 uk）。

三套后台服务 profile 的监听 band 不重叠（171xx / 172xx / 173xx），管理端口也已分开；`default` 是 GUI/legacy：

| profile | mixedPort | externalControllerPort | 典型用途 |
| --- | --- | --- | --- |
| `default` | 7897 | 9097 | GUI/legacy，不要和 robin 同时启动 |
| `spider_lb_robin` | 17797 | 18997 | 后台服务 A，171xx |
| `spider_lb_ch` | 17897 | 19097 | 后台服务 B，172xx |
| `spider_lb_sticky` | 17997 | 19197 | 后台服务 B，173xx |

模板不再写 `external-controller-pipe`，后台实例统一用 TCP `external-controller`；Clash Verge 启动内核时会用自己的 `-ext-ctl-pipe`。因此 A、B、C 可以同时运行；只有需要 TUN 的实例开 `tun.enable`。

## 多实例启动

先渲染目标 profile，再用 `mihomo_instance.py` 校验和启动；每个实例用独立 `--home`，不要和 Clash Verge 共用。完整操作清单见[后台服务多实例：启动、状态、停止](./mihomo@后台服务多实例@启动状态停止.md)。

```bash
# A：171xx 轮询
python3 mihomo_instance.py start \
  --config ~/Desktop/mihomo-profiles/spider_lb_robin.generated.yaml \
  --home ~/mihomo-sticky/robin --mihomo /path/to/mihomo

# B：172xx 目标粘性
python3 mihomo_instance.py start \
  --config ~/Desktop/mihomo-profiles/spider_lb_ch.generated.yaml \
  --home ~/mihomo-sticky/ch --mihomo /path/to/mihomo

# 查看所有实例
python3 mihomo_instance.py list --root ~/mihomo-sticky

# 单独停止
python3 mihomo_instance.py stop --home ~/mihomo-sticky/ch
```

A、B 可以同时运行；173xx 的 `spider_lb_sticky` 也按同样方式启动。`stop` 只停 PID 文件里记录的进程，不会按进程名误伤 Clash Verge。

## 端口两种模式

默认连号，需要精确控制时切显式；两者互斥，同一份 profile 不能混用。

### 连号（默认）

两个地区入口逐个指定，国家入口（含 uk）从 `portEu` 起 +1、+2……：

```json
{
  "portAll": 17100,
  "portEu": 17110,
  "countryOrder": ["us", "jp", "hk", "sg", "de", "fr", "th", "ru", "tw", "uk"]
}
```

`countryOrder` 可以省略，省略时用内置顺序。新增国家**只能追加到末尾**：插在中间会让后面所有国家端口前移，外部写死的端口映射会静默指错国家。

### 显式端口表（可选）

```json
"ports": {
  "all": 17100, "eu": 17110,
  "us": 17111, "jp": 17112, "hk": 17113, "sg": 17114, "de": 17115,
  "fr": 17116, "th": 17117, "ru": 17118, "tw": 17119, "uk": 17120
}
```

写了 `ports` 就不能再写 `portAll`/`portEu`/`countryOrder`。新增国家只加一个键，已有国家端口不动，适合“端口已经被外部系统当契约”的场景。

### 端口校验规则

- 模板里的 `{{PORT_*}}` 集合与本次配置提供的端口键必须完全一致，少一个或多一个都报错，模板加了入口没配端口、配了端口模板没入口都会被拦住
- 同一份 profile 内端口不得重复
- 不能占用模板自身的 `mixed-port`/`port`/`socks-port`/`redir-port`/`tproxy-port` 与 `external-controller` 端口，这些值从模板正文解析，不写死在脚本里
- 不能落在常见软件默认端口：7890-7899（Clash/mihomo 客户端）、9090/9091/9097（Clash API）、1080/1081/1086/1087、10808-10810、3128、8080/8081、8118/8123、8888/8889、2080、9222（Chrome DevTools）、20171/20172；确需使用加 `"allowCommonPorts": true`
- 合法范围 1024-65535；>=32768 落在系统临时端口区间时只告警，不拦截

按这套方案，每段能加到 79 个国家（17111-17189）而不用换段；再往上就开新 band（如 17300），不要把端口挤回 7890 段。

## 常用命令

| 目的 | 命令 | 说明 |
| --- | --- | --- |
| 渲染全部 | `python3 render_profile.py` | 内容未变则跳过，不产生无意义改动 |
| 使用本地清单 | `python3 render_profile.py --manifest templates/spider_lb.profiles.local.json` | 显式指定数据文件；本地文件存在时也可省略 |
| 只渲染一份 | `python3 render_profile.py default` | 短名即可，自动对应 `default.generated.yaml` |
| 按默认配置另存 | `python3 render_profile.py crawler` | 生成 `crawler.generated.yaml`，内容同 default |
| 指定内容来源另存 | `python3 render_profile.py crawler --from spider_lb_ch` | 用 ch 的内容，存成 `crawler.generated.yaml` |
| 精确文件名 | `python3 render_profile.py probe.yaml` | 显式 `.yaml` 按原样落盘 |
| 查看清单 | `python3 render_profile.py --list` | 输出目录 + 已定义 profile + 自定义产物及其状态 |
| 遍历名字 | `python3 render_profile.py --list --names` | 一行一个，可直接喂给循环 |
| 看要写哪些文件 | `python3 render_profile.py --dry-run` | 只列出文件与汇总，不落盘；要看内容用 `--print` |
| 终端预览正文 | `python3 render_profile.py crawler --from spider_lb_ch --print` | 渲染结果打到 stdout，含文件头；不落盘 |
| 保存单份预览 | `python3 render_profile.py default --print > preview.yaml` | 单份才是一份可直接加载的配置；多份会被注释分隔，只作预览 |
| 校验同步 | `python3 render_profile.py --check` | 与模板一致退出 `0`；未生成、有差异或产物被手改退出 `3` |
| 校验时忽略未生成 | `python3 render_profile.py --check --allow-missing` | 只关心漂移；未生成不算失败，手改或过期仍退出 `3` |
| 覆盖手改 | `python3 render_profile.py --force` | 生成物被手改过时的显式入口 |
| 渲染并测配置 | `python3 render_profile.py --test --mihomo-home <HomeDir>` | 渲染后调 `mihomo -t`；缺 `--mihomo-home` / `MIHOMO_HOME` 返回 `2` |

`--list` 会先打印实际输出目录，再扫描该目录；识别依据是 `.generated.yaml` 后缀或文件头指纹，所以 `demo.yaml`、`mihomo.template.yaml` 这类手写文件不会混进来：

```text
输出目录: /home/<user>/Desktop/mihomo-profiles
已定义:
  default -> default.generated.yaml (最新)
  spider_lb_ch -> spider_lb_ch.generated.yaml (最新)

自定义(未在 profiles.json):
  crawler.generated.yaml (按 defaults，最新)
```

`--list --names` 只输出名字：已定义的给短名，自定义的给完整文件名，都能直接作为位置参数再喂回脚本：

```bash
python3 render_profile.py --list --names | while read -r name; do
  python3 render_profile.py "$name" --check
done
```

注意：用 `--from` 生成的自定义产物，`--check` 时要带上同样的 `--from`，否则会按 `defaults` 比对而报差异。

`--print` 的约定：stdout 只留配置正文（进度与汇总走 stderr），单份时可以直接重定向成文件；多份时每份前有一行 `# ===== <文件名> =====` 注释分隔，只是预览，不是一份可直接加载的 YAML。它不写盘、不建目录，也不与 `--check` / `--test` / `--dry-run --test` 组合使用。脚本被重定向时会显式按 UTF-8 输出，三平台落盘一致。

Windows 上 PowerShell 5.1 的 `>` 会把输出转成 UTF-16，需要时改用 `--print | Out-File -Encoding utf8 preview.yaml`；pwsh 7 与 bash 的 `>` 没有这个问题。

退出码与其它脚本一致：`0` 成功、`1` 运行或配置解析失败（含 `--test` 失败）、`2` 用法错误（参数冲突、缺 `--mihomo-home`、未知目标）、`3` 状态差异（`--check` 发现差异、未生成、产物被手改需要 `--force`）。`--check --allow-missing` 只把“未生成”降级为成功，漂移仍返回 `3`。

## 改订阅更新节奏的正确位置

订阅节奏属于“每份产物的差异值”，改 `profiles.json`，不要改生成物。可以写在 `subscriptions` 的每个订阅上，也可以只写一次默认值：

```json
{
  "subscriptionInterval": 43200,
  "subscriptions": {
    "online-sub1": { "url": "https://..." },
    "online-sub2": { "url": "https://...", "interval": 21600 }
  }
}
```

| 取值 | 约合 |
| --- | --- |
| `43200` | 每 12 小时，约每天 2 次 |
| `86400` | 每 24 小时，每天 1 次 |
| `64800` | 每 18 小时，约每天 1.3 次 |

改完走一遍“渲染 → 应用 → 核验”，更新机制本身（启动判定、退避、缓存位置）见 [mihomo@订阅和规则集的自动更新@interval与手动触发@状态核验](./mihomo@订阅和规则集的自动更新@interval与手动触发@状态核验.md)。

## 生成物指纹怎么用

- `--check` 读文件头指纹并与正文重算结果比对：正文被手改、或模板已更新而产物未重渲染，都会报差异并退出 `3`；只有“未生成”可以在加 `--allow-missing` 时不报错
- 渲染时若发现目标文件被手改，脚本要求显式 `--force`（同样退出 `3`），避免静默覆盖
- 所以“临时在产物上试一下”的做法会立刻被下次 `--check` 抓到，确认有用再回写到模板和值文件

## 与运行态的关系

渲染只改输出目录里的 `*.yaml`（默认在桌面）。内核实际加载的是 GUI 生成的那份配置，两者不会自动同步：

```text
输出目录/default.generated.yaml
  → 在 Clash Verge 里重新应用/切换当前 profile
  → Verge 的 profiles/<uid>.yaml（导入的副本）
  → Verge 生成的 clash-verge.yaml（内核 -f 加载的就是它）
```

本机实证（2026-11-12 的一次对比）：当时的 `profiles/default.generated.yaml`（当时文件名 `spider_lb.generated.yaml`）的 SHA256 是 `9AC12055…`，而 Verge 的 profile 副本是 `3B1AD67D…`（8 月版本），当时运行态里订阅 provider 的 `interval` 还是 `86400`、规则还是 `IN-PORT`，与生成内容不一致。

判断“当前跑的是哪一版”，不要看仓库文件时间，要看：

- Verge 工作目录下 `clash-verge.yaml` 的 mtime，以及其中是否存在最新特征（如 `IN-NAME`、`interval: 43200`）
- `/providers/proxies` 与 `/providers/rules` 的 `updatedAt` 是否符合新节奏

## 验收清单

- `python3 render_profile.py --check` 退出码 `0`
- 生成物头部指纹存在，且与正文重算一致（脚本自检即可）
- 新增或调整国家入口后，旧国家的端口没有变化（连号模式只能追加，迁移到显式表可彻底避免重排）
- 新增在线订阅后，`use-providers` 里自动出现该 provider，生成物能被 `mihomo -t` 通过
- `--test --mihomo-home <HomeDir>` 或 `mihomo -t -d <HomeDir> -f <产物>` 通过
- 在 GUI 重新应用后，`clash-verge.yaml` 里能看到本次改动（如 `interval: 43200`、`IN-NAME`）
- 用只读脚本确认 provider 新鲜度：`python3 check_provider_status.py --secret '<secret>'`
- `python3 -m unittest discover -s tests` 全部通过
