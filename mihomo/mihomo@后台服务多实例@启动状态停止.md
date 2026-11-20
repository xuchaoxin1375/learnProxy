[toc]

> 上级入口：[仓库根 README](../README.md)（脚本、模板与文档总索引）

## 这套用法解决什么

默认把负载均衡拆成多个独立 mihomo 后台实例，由 `mihomo_instance.py` 管理；不靠切换 Clash Verge profile。这样可以同时保留：

- 日常浏览用的 GUI profile；
- 需要轮换 IP 的轮询实例；
- 需要目标粘性的实例；
- 需要短会话粘性的实例。

每个实例有自己的 `-d` 工作目录、mixed 入口、controller 控制口和入口 band，互不争用。

第一次部署先看[新用户部署：从零到可用](./mihomo@新用户部署@从零到可用.md)；本文以 Windows PowerShell 为例，Linux/macOS 把 `Copy-Item`/`$env:USERPROFILE` 换成 `cp`/`$HOME`，脚本命令相同。

## 实例与端口

| 实例 | profile | 入口 mixed / 控制口 controller | 业务入口 | 策略 | 典型用途 |
| --- | --- | --- | --- | --- | --- |
| A | `spider_lb_robin` | `17797` / `18997` | `171xx` | `round-robin` | 429、Shopify `/products.json` 等轮换任务 |
| B | `spider_lb_ch` | `17897` / `19097` | `172xx` | `consistent-hashing` | 反爬/会话站，同一目标固定出口 |
| C | `spider_lb_sticky` | `17997` / `19197` | `173xx` | `sticky-sessions` | 10 分钟会话粘性；按需启动 |
| GUI | 雪山 Link 等 | `7897` / `9097` | 无 | 日常 | 日常浏览，不承载采集负载均衡 |

`17797/17897/17997` 是爬虫入口，`18997/19097/19197` 是控制 API；两者不要混用。

`default.generated.yaml` 仍是 GUI/legacy 的 `171xx` + `7897/9097`。不要把它当后台服务启动；它和 A 都用 `171xx`，会冲突。切回 GUI 的 `default.generated.yaml` 前，先停 `spider_lb_robin`。

## 前置：私有清单

复制骨架到桌面或仓库外目录，填真实订阅：

```powershell
Copy-Item .\templates\spider_lb.profiles.local.example.json `
  "$env:USERPROFILE\Desktop\spider_lb.profiles.local.json"

notepad "$env:USERPROFILE\Desktop\spider_lb.profiles.local.json"
```

编辑 `defaults.subscriptions.online-sub1.url`。如果有多条订阅，可在 `subscriptions` 下增加 `online-sub2`，再在对应 profile 里覆盖 `subscriptions`。

渲染：

```powershell
python -X utf8 render_profile.py `
  --manifest "$env:USERPROFILE\Desktop\spider_lb.profiles.local.json"
```

产物默认在 `$env:USERPROFILE\Desktop\mihomo-profiles`。不要编辑 `*.generated.yaml`，它们是渲染产物；真实订阅只写私有清单。

## 启动

先设置三个路径变量：

```powershell
$Mihomo = "C:\Program Files\Clash Verge\verge-mihomo.exe"
$Root = "$env:USERPROFILE\mihomo-sticky"
$Profiles = "$env:USERPROFILE\Desktop\mihomo-profiles"
```

没有 Clash Verge 时，把 `$Mihomo` 换成官方 Release 的 `mihomo` 路径；也可以设置 `MIHOMO_BIN`，后面省略 `--mihomo`。Linux/macOS 把路径换成 `/usr/local/bin/mihomo` 等实际位置。

启动 A（轮询）：

```powershell
python -X utf8 mihomo_instance.py start `
  --config "$Profiles\spider_lb_robin.generated.yaml" `
  --home "$Root\robin" `
  --mihomo $Mihomo --verify
```

启动 B（目标粘性）：

```powershell
python -X utf8 mihomo_instance.py start `
  --config "$Profiles\spider_lb_ch.generated.yaml" `
  --home "$Root\ch" `
  --mihomo $Mihomo --verify
```

按需启动 C（会话粘性）：

```powershell
python -X utf8 mihomo_instance.py start `
  --config "$Profiles\spider_lb_sticky.generated.yaml" `
  --home "$Root\sticky" `
  --mihomo $Mihomo --verify
```

`start` 会先跑 `mihomo -t`；校验失败不会启动。`--home` 是必填项，避免多实例共用 PID 和日志。`--verify` 会短查控制 API 与 proxy provider：节点为空、provider 404 或 API 不可达时返回 3，但进程保留，用 `status --verify` 复测或看日志。

## 查看状态

一次看全部：

```powershell
python -X utf8 mihomo_instance.py list --root "$env:USERPROFILE\mihomo-sticky"
```

看单个：

```powershell
python -X utf8 mihomo_instance.py status --home "$env:USERPROFILE\mihomo-sticky\robin" --verify
python -X utf8 mihomo_instance.py status --home "$env:USERPROFILE\mihomo-sticky\ch" --verify
```

`--verify` 读配置里的 `external-controller` 与 `secret`，短查 `/version` 和 `/providers/proxies`；空 provider 或 API 不可达返回 3。它只读，不切节点。

检查监听端口：

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 17100,17110,17111,17200,17210,17211,17300,17310,17311,17797,17897,17997,18997,19097,19197 } |
  Select-Object LocalAddress, LocalPort, OwningProcess |
  Sort-Object LocalPort
```

检查控制器：

```powershell
curl.exe -sS --noproxy "*" -H "Authorization: Bearer 1" http://127.0.0.1:18997/version
curl.exe -sS --noproxy "*" -H "Authorization: Bearer 1" http://127.0.0.1:19097/version
```

检查 provider（A/B 的控制口不同，必须显式 `--api`）：

```powershell
python -X utf8 check_provider_status.py --api http://127.0.0.1:18997 --secret 1 --summary
python -X utf8 check_provider_status.py --api http://127.0.0.1:19097 --secret 1 --summary
```

检查出口：

```powershell
curl.exe -sS --max-time 30 -x http://127.0.0.1:17111 https://api.ipify.org?format=json
curl.exe -sS --max-time 30 -x http://127.0.0.1:17211 https://api.ipify.org?format=json
```

重复请求验证策略（每次 `curl` 是新的连接）：

```powershell
1..5 | ForEach-Object {
  curl.exe -sS --max-time 30 -x http://127.0.0.1:17111 https://api.ipify.org
  ""
}
```

A 的出口可能变化，但节点池太小或连接复用时也可能不变；B 对同一目标应稳定，换目标才可能换节点；C 在 10 分钟窗口内同源同目标应稳定。

判读：

- A 是 `round-robin`，实际是否换 IP 取决于组内可用节点和连接分配，不能保证每次请求都变。
- B 是 `consistent-hashing`，同一目标应稳定在同一出口；换目标可能换节点。
- C 是 `sticky-sessions`，同一来源 + 目标保持 10 分钟。

## 停止与重启

```powershell
python -X utf8 mihomo_instance.py stop --home "$env:USERPROFILE\mihomo-sticky\robin"
python -X utf8 mihomo_instance.py stop --home "$env:USERPROFILE\mihomo-sticky\ch"
python -X utf8 mihomo_instance.py stop --home "$env:USERPROFILE\mihomo-sticky\sticky"
```

`stop` 只停 PID 文件里记录的进程，并按命令行核对归属；不会按进程名误伤 Clash Verge。

## 清理

确认三个实例都停止后，按需删除：

- `$env:USERPROFILE\mihomo-sticky\<实例名>`：PID、日志与实例级缓存；
- 桌面 `mihomo-profiles\*.generated.yaml`：可随时从模板重新渲染；
- 私有清单与订阅缓存：确认不再需要后再删。

不要删除 Clash Verge 自己的工作目录；后台实例和 GUI 是两套运行态。

## 改订阅或端口后

编辑桌面私有清单，先检查再渲染：

```powershell
python -X utf8 render_profile.py `
  --manifest "$env:USERPROFILE\Desktop\spider_lb.profiles.local.json" --check

python -X utf8 render_profile.py `
  --manifest "$env:USERPROFILE\Desktop\spider_lb.profiles.local.json"
```

渲染后重启受影响的实例。模板变更时，`--check` 会把旧产物标为需重新渲染；重新渲染并重启实例即可。

## 排错

| 现象 | 先查 |
| --- | --- |
| `start` 报端口占用 | 用上面的端口命令看 171xx/172xx/173xx/controller；A 和 `default` 都用 171xx |
| `status` 显示已退出 | 看实例目录下的 `mihomo.log` 末尾；PID 文件会保留，`stop` 会清理过期 PID |
| 实例运行但节点为空 | `status --home ... --verify`；或按实例跑 `check_provider_status.py --api http://127.0.0.1:<control> --secret 1`；检查私有清单 URL、网络与 filter |
| 改订阅后仍用旧节点 | 重新渲染并重启实例；不要只改生成的 YAML |
| 旧配置仍报 pipe 冲突 | 重新渲染；新模板不再写 `external-controller-pipe` |
| GUI 切 profile 后采集入口消失 | GUI profile 和后台实例是两套；采集入口以 `mihomo_instance.py list` 为准 |

## 安全

- 私有清单和生成的配置都含订阅地址与节点信息；只放在桌面或仓库外目录，不要提交。
- 模板里的 `secret: '1'` 只适合本机；需要局域网面板时同时改 `external-controller` 监听地址和 secret。
- 不要把带真实订阅的配置复制回仓库，也不要用 `git add -f` 强行加入被忽略的文件。
