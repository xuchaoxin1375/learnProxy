[toc]

> 上级入口：[仓库根 README](../README.md)（脚本、模板与文档总索引）

## 适用场景

第一次在一台新设备上把多实例 mihomo 负载均衡跑起来：从准备二进制、创建私有清单、渲染配置，到启动 A/B 实例、验证节点与出口。本文只给最短路径；模板细节、端口方案和排错展开见[配置模板与生成物](./mihomo@配置模板与生成物@render-profile渲染与校验.md)与[后台服务多实例](./mihomo@后台服务多实例@启动状态停止.md)。

## 两个仓库怎么分工

- **learnProxy**：模板、私有清单、配置渲染、实例启动/停止、provider 状态与手动更新。配置负载均衡主要用这个仓库。
- **skills-for-developer**：通用网络选路、代理入口探测、mihomo 配置/节点/分组只读体检。它不是 learnProxy 的依赖，但装好后可以用 `inspect_mihomo.py --list-instances` 和 `probe_local_proxies.py` 做运行态核对。
- 两个仓库可以独立使用；只部署其中一个也能工作，只是少一套检查工具。

## 前置

- Python 3.10+，脚本只依赖标准库。
- Git，用于获取两个仓库。
- 一个 mihomo 二进制：官方 Release 的 `mihomo`，或 Clash Verge 自带的 `verge-mihomo.exe`。
- 一个可用的机场订阅 URL。真实订阅只放在私有清单，不提交到仓库。
- 可选：Clash Verge 用于日常 GUI；后台采集实例不依赖它。

安装与目录规划见[命令行启动参数与进程取证](./mihomo@命令行@启动参数与进程取证.md#安装与目录规划)。Windows 如果只装了 Clash Verge，可以直接用它的 `verge-mihomo.exe`，但不要和 GUI 共用 `-d` 工作目录。

## 从零到可用

1. **部署 skills 仓库（可选）**：克隆 `skills-for-developer`，按仓库 README 运行 `scripts/link-skills.ps1` 或 `scripts/link-skills.sh`，再用 `-VerifyOnly` / `--verify-only` 确认链接。
2. **克隆 learnProxy**：`git clone https://github.com/xuchaoxin1375/learnProxy.git`，后续命令都在仓库根目录执行。
3. **创建私有清单**：把 `templates/spider_lb.profiles.local.example.json` 复制到仓库外，例如桌面或 `$HOME/.config/learnProxy/`。不要直接在公开的 `spider_lb.profiles.json` 里写真实订阅。
4. **填订阅**：编辑私有清单的 `defaults.subscriptions.online-sub1.url`。如果 B 实例要用另一条订阅，再覆盖 `spider_lb_ch.generated.yaml` 条目的 `subscriptions`。
5. **渲染**：先 `--list` 看输出目录和产物状态，再 `--dry-run` 预览，最后正式渲染。
6. **校验**：用 `mihomo_instance.py validate --mihomo <mihomo>` 校验目标 profile；也可以 `render_profile.py --test --mihomo-home <HomeDir> --mihomo <mihomo>`。
7. **启动 A/B**：A 是 `171xx` 轮询，B 是 `172xx` 目标粘性；C（`173xx` 会话粘性）按需启动。推荐加 `--verify`。
8. **验证**：`mihomo_instance.py list` 看实例，`status --verify` 看 API 与 provider；再用控制器和出口检查确认链路。
9. **接入爬虫**：A 用 `http://127.0.0.1:17111`（美国）或 `17100`（all）；B 用 `17211` 或 `17200`；C 用 `17311` 或 `17300`。
10. **停止与清理**：`stop` 只停进程；生成物、实例目录、日志、PID 与 provider 缓存需要按需清理。

## 最短命令

Windows PowerShell：

```powershell
$Repo = "$env:USERPROFILE\learnProxy"
$Private = "$env:USERPROFILE\Desktop\spider_lb.profiles.local.json"
$Mihomo = "C:\Program Files\Clash Verge\verge-mihomo.exe"
$Profiles = "$env:USERPROFILE\Desktop\mihomo-profiles"
$Root = "$env:USERPROFILE\mihomo-sticky"

Copy-Item "$Repo\templates\spider_lb.profiles.local.example.json" $Private
notepad $Private

python -X utf8 "$Repo\render_profile.py" --manifest $Private --list
python -X utf8 "$Repo\render_profile.py" --manifest $Private

python -X utf8 "$Repo\mihomo_instance.py" start `
  --config "$Profiles\spider_lb_robin.generated.yaml" `
  --home "$Root\robin" --mihomo $Mihomo --verify

python -X utf8 "$Repo\mihomo_instance.py" start `
  --config "$Profiles\spider_lb_ch.generated.yaml" `
  --home "$Root\ch" --mihomo $Mihomo --verify

python -X utf8 "$Repo\mihomo_instance.py" list --root $Root
```

Linux/macOS：

```bash
REPO="$HOME/learnProxy"
PRIVATE="$HOME/spider_lb.profiles.local.json"
MIHOMO="/usr/local/bin/mihomo"
PROFILES="$HOME/mihomo-profiles"
ROOT="$HOME/mihomo-sticky"

cp "$REPO/templates/spider_lb.profiles.local.example.json" "$PRIVATE"
"${EDITOR:-vi}" "$PRIVATE"

python3 "$REPO/render_profile.py" --manifest "$PRIVATE" --list
python3 "$REPO/render_profile.py" --manifest "$PRIVATE"

python3 "$REPO/mihomo_instance.py" start \
  --config "$PROFILES/spider_lb_robin.generated.yaml" \
  --home "$ROOT/robin" --mihomo "$MIHOMO" --verify

python3 "$REPO/mihomo_instance.py" start \
  --config "$PROFILES/spider_lb_ch.generated.yaml" \
  --home "$ROOT/ch" --mihomo "$MIHOMO" --verify

python3 "$REPO/mihomo_instance.py" list --root "$ROOT"
```

没有 `mihomo` 在 PATH 时，`--mihomo` 是显式入口；也可以设置 `MIHOMO_BIN`。`render_profile.py --test` 同样接受 `--mihomo`。

## 验证清单

Windows 用 `curl.exe`，Linux/macOS 用 `curl`；下面的 `--noproxy '*'` 两边都适用。

- `mihomo_instance.py status --home <实例目录> --verify`：应看到 API 版本和 proxy provider 节点数；空 provider 或 API 不可达会返回 3。
- 控制器：`curl --noproxy '*' -H "Authorization: Bearer 1" http://127.0.0.1:18997/version`（A）或 `19097`（B）。
- 节点：`curl --noproxy '*' -H "Authorization: Bearer 1" http://127.0.0.1:19097/providers/proxies`，确认订阅 provider 不是空数组。
- 出口：`curl --noproxy '*' --max-time 30 -x http://127.0.0.1:17111 https://api.ipify.org?format=json`，B 换成 `17211`。
- 装了 skills 仓库时：`python -X utf8 <skills>/network-access/scripts/inspect_mihomo.py --list-instances` 可一次看 PID、`-d`/`-f`、mixed、controller、listeners 与策略；`probe_local_proxies.py --json` 可核对入口协议与出口。

## 策略怎么选

- **A：`spider_lb_robin`（171xx）**：`round-robin`，按连接轮换出口。适合 429、公开 JSON、多连接下载等不需要会话一致性的任务。
- **B：`spider_lb_ch`（172xx）**：`consistent-hashing`，同一目标稳定到同一出口。适合反爬、需要稳定 IP 的站点。
- **C：`spider_lb_sticky`（173xx）**：`sticky-sessions`，同一来源 + 目标保持约 10 分钟。适合登录态、购物车、验证码流程。
- `17100/17200/17300` 是不分国家的 all 入口；`17111/17211/17311` 等国家入口来自 `listeners`。默认顺序是 us/jp/hk/sg/de/fr/th/ru/tw/uk，所以 `+11` 通常是美国；具体映射以清单的 `countryOrder` 和渲染后的配置为准。

`round-robin` 不保证每个请求都换 IP；节点池太小或连接复用都会让观察结果看起来“没变”。需要验证时多做几次独立请求，并确认节点池有足够可用节点。

## 常见卡点

- **`render_profile.py --test` 报找不到 mihomo**：加 `--mihomo <路径>`，或设置 `MIHOMO_BIN`；也可以改用 `mihomo_instance.py validate --mihomo`。
- **`start` 显示已启动但节点为空**：用 `status --verify` 复测；看日志里的 `online-sub1 ... 404/timeout`，检查订阅 URL、网络与 provider 的 `filter`。`--verify` 返回 3 表示进程在跑但健康检查未通过。
- **端口占用**：`default.generated.yaml` 和 A 都使用 `171xx`，已有 Clash Verge 时不要启动 `default`；A/B/C 的 mixed 与 controller 也必须各自唯一。
- **mixed 与 controller 混用**：`17797/17897/17997` 是爬虫入口，`18997/19097/19197` 是控制 API；不要把 controller 填进 `HTTP_PROXY`。
- **规则集或 Geo 数据下载失败**：首次启动可能需要下载 jsDelivr 规则集与 Geo 数据；国内网络不稳时按[GeoX 文档](./Geox@GeoIP@Geosite.md)准备缓存或调整下载代理。
- **改订阅后仍是旧节点**：重新渲染并重启对应实例；不要只改 `*.generated.yaml`。

## 清理

```powershell
python -X utf8 mihomo_instance.py stop --home "$env:USERPROFILE\mihomo-sticky\robin"
python -X utf8 mihomo_instance.py stop --home "$env:USERPROFILE\mihomo-sticky\ch"
python -X utf8 mihomo_instance.py stop --home "$env:USERPROFILE\mihomo-sticky\sticky"
```

确认实例停止后，按需删除 `mihomo-sticky` 下的实例目录、桌面生成物和 provider 缓存；Linux/macOS 用 `rm -rf` 删对应目录。不要删除 Clash Verge 自己的工作目录；`mihomo_instance.py` 只管理自己 PID 文件记录的进程。
