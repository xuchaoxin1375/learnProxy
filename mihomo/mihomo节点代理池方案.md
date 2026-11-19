[toc]

## abstract

> **传统代理客户端并不是只能“永远只用一个节点”**

一个具体的 TCP/HTTP 请求最终通常只会走**一个出口节点**，但 Clash/Mihomo 可以让**不同连接**按规则、测速、故障转移或负载均衡走不同节点。

**Mihomo** 支持 `select`、`url-test`、`fallback`、`load-balance` 等策略组；

- 其中 `load-balance` 的 `round-robin` 会在**组内不同节点之间**分配请求，
- `consistent-hashing` 会让**同一目标地址固定到同一节点**，
- `sticky-sessions` 会按源地址和目标地址保持短时间粘性。

references:

([proxy-groups/select MetaCubex](https://wiki.metacubex.one/en/config/proxy-groups/select/)) 

([proxy-groups/url-test MetaCubex](https://wiki.metacubex.one/en/config/proxy-groups/url-test/))

([proxy-groups/fallback MetaCubex](https://wiki.metacubex.one/en/config/proxy-groups/fallback/))

([proxy-groups/load-balance MetaCubex](https://wiki.metacubex.one/en/config/proxy-groups/load-balance/))

------

## 1. 代理池最简单方案：让 Mihomo 内部做负载均衡

这种方式下，应用程序(例如,Python )仍然只连本机一个端口，比如 `127.0.0.1:7890`，但 Mihomo 在内部决定本次连接走哪个节点。Mihomo 的 `mixed-port` 是一个同时支持 HTTP(S) 和 SOCKS5 的入口端口，任何支持 HTTP/SOCKS 代理的程序都可以连接它。([MetaCubex](https://wiki.metacubex.one/en/config/inbound/port/))

示例配置思路：

```yaml
mixed-port: 7890
allow-lan: false
mode: rule
log-level: info

proxies:
  # 这里放订阅导出的节点
  # 不要把 uuid/password 发布到公开仓库或日志里

proxy-groups:
  - name: PY_POOL
    type: load-balance
    strategy: round-robin
    proxies:
      - "🇺🇸美·洛杉矶|三网-DS1"
      - "🇺🇸美·洛杉矶|三网-DS2"
      - "🇰🇷韩国SK·三网|家宽1"
      - "🇰🇷韩国SK·三网|家宽2"
    url: "https://www.gstatic.com/generate_204"
    interval: 300

rules:
  - MATCH,PY_POOL
```

Python：

```python
import requests

PROXY = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890",
}

def fetch(url: str) -> str:
    r = requests.get(url, proxies=PROXY, timeout=15)
    r.raise_for_status()
    return r.text

print(fetch("https://httpbin.org/ip"))
```

这个方案的优点是简单、稳定。缺点是 Python 不知道具体走了哪个节点，也不适合你想“本次请求强制指定某个节点”的场景。

------

## 2. Python 通过 Mihomo的api控制：每次请求前切换节点

Mihomo 有 REST 控制 API。文档中 `/proxies` 可以获取代理信息，`PUT /proxies/{group_name}` 可以为指定策略组选择节点。

- [MetaCubex](https://wiki.metacubex.one/en/api/)
- [external-control-api|General configuration - mihomo docs](https://wiki.metacubex.one/en/config/general/#external-control-api)

你需要在配置里开启：

```yaml
mixed-port: 7890
external-controller: 127.0.0.1:9090
secret: "change-me"

proxy-groups:
  - name: PY_SELECT
    type: select
    proxies:
      - "🇺🇸美·洛杉矶|三网-DS1"
      - "🇺🇸美·洛杉矶|三网-DS2"
      - "🇰🇷韩国SK·三网|家宽1"
      - "🇰🇷韩国SK·三网|家宽2"

rules:
  - MATCH,PY_SELECT
```

Python 示例：

```python
import random
import time
from urllib.parse import quote

import requests


CLASH_API = "http://127.0.0.1:9090"
SECRET = "change-me"
GROUP = "PY_SELECT"

LOCAL_PROXY = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890",
}

API_HEADERS = {
    "Authorization": f"Bearer {SECRET}",
}


def api_url(path: str) -> str:
    return f"{CLASH_API}{path}"


def get_group_nodes() -> list[str]:
    group = quote(GROUP, safe="")
    r = requests.get(api_url(f"/proxies/{group}"), headers=API_HEADERS, timeout=10)
    r.raise_for_status()

    data = r.json()
    nodes = data.get("all", [])

    return [
        n for n in nodes
        if n not in {"DIRECT", "REJECT", "GLOBAL"}
    ]


def switch_node(node_name: str) -> None:
    group = quote(GROUP, safe="")
    r = requests.put(
        api_url(f"/proxies/{group}"),
        headers=API_HEADERS,
        json={"name": node_name},
        timeout=10,
    )
    r.raise_for_status()


def fetch_with_node(url: str, node_name: str) -> str:
    switch_node(node_name)

    # 给 Mihomo 一点点时间处理选择状态；通常不需要很长
    time.sleep(0.2)

    r = requests.get(url, proxies=LOCAL_PROXY, timeout=20)
    r.raise_for_status()
    return r.text


if __name__ == "__main__":
    nodes = get_group_nodes()
    print("可用节点：", nodes)

    for i in range(5):
        node = random.choice(nodes)
        print(f"\n第 {i + 1} 次使用节点：{node}")
        print(fetch_with_node("https://httpbin.org/ip", node))
```

这个方案适合**串行请求**。
它的关键问题是：`PY_SELECT` 的选择状态是 Mihomo 的全局状态。

如果你在多线程/异步并发里同时切换节点，就会互相抢状态，导致“线程 A 以为自己用节点 1，实际请求可能走了线程 B 刚切过去的节点 2”。

------

## 3. 真正适合并发的方案：多个本地端口 = 多个固定出口

如果你想让 Python 在并发里做到：

```text
请求 A → 节点 1
请求 B → 节点 2
请求 C → 节点 3
```

更稳的做法是：**为每个节点启动一个独立本地代理端口**。

例如：

```text
127.0.0.1:7901 → 洛杉矶 DS1
127.0.0.1:7902 → 洛杉矶 DS2
127.0.0.1:7903 → 韩国 家宽1
127.0.0.1:7904 → 韩国 家宽2
```

然后 Python 随机选择端口：

```python
import random
import requests


LOCAL_PROXIES = [
    {"name": "LA-DS1", "proxy": "http://127.0.0.1:7901"},
    {"name": "LA-DS2", "proxy": "http://127.0.0.1:7902"},
    {"name": "KR-HOME1", "proxy": "http://127.0.0.1:7903"},
    {"name": "KR-HOME2", "proxy": "http://127.0.0.1:7904"},
]


def fetch(url: str) -> tuple[str, str]:
    item = random.choice(LOCAL_PROXIES)
    proxy_url = item["proxy"]

    proxies = {
        "http": proxy_url,
        "https": proxy_url,
    }

    r = requests.get(url, proxies=proxies, timeout=20)
    r.raise_for_status()

    return item["name"], r.text


if __name__ == "__main__":
    for _ in range(5):
        node, body = fetch("https://httpbin.org/ip")
        print("使用节点：", node)
        print(body)
```

这种方式比“每次请求前切换 Mihomo 策略组”更适合并发，因为每个本地端口背后固定一个节点，不会互相抢全局状态。

------

## 4. HTTP 代理还是 SOCKS5 代理？

如果用 Mihomo 的 `mixed-port`，Python 可以用 HTTP 代理写法：

```python
proxies = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890",
}
```

也可以用 SOCKS5，但需要安装额外依赖：

```bash
python -m pip install "requests[socks]"
```

然后：

```python
proxies = {
    "http": "socks5h://127.0.0.1:7890",
    "https": "socks5h://127.0.0.1:7890",
}
```

Requests 官方文档说明 SOCKS 支持是可选依赖；`socks5` 会在客户端解析 DNS，而 `socks5h` 会把 DNS 解析交给代理端。([requests.readthedocs.io](https://requests.readthedocs.io/en/master/user/advanced/))

------

## 5. 推荐选择

你的场景可以这样选：

| 需求                             | 推荐方案                             |
| -------------------------------- | ------------------------------------ |
| 只是想让出口不总是一个 IP        | Mihomo `load-balance`                |
| 想串行地指定“本次请求用哪个节点” | Python 调 Mihomo API 切 `select` 组  |
| 想并发、每个请求独立选择节点     | 多个本地端口，每个端口固定一个节点   |
| 想低维护、稳定抓取公开数据       | 控频 + 缓存 + API 优先，代理只做辅助 |

我个人建议你采用第三种：**多个本地端口 + Python 随机/轮询选择端口**。这是最接近“代理池”的结构，也不会因为 Mihomo 全局切换状态导致并发混乱。