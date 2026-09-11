# 站点爬取配置（reference）

> 当用户说"帮我爬 XXX"、"用脚本读取 XXX 站点 3 条"时，skill 应该**真实可执行**的爬取配置：
> 把大模型的即兴 Header / Cookie / 限速 生成已知站点上的 Python 代码 / curl 命令。

---

## 1. 9 个预制站点的"现成可爬"配置

| 域名 | 名称 | 限速 | 风控难度 | 推荐层级 |
|---|---|---|---|---|
| `baidu.com` | 百度搜索 | 0.5s/次 | ★★☆ | L1 curl_cffi |
| `www.bing.com` | Bing 搜索 | 0.2s/次 | ★☆☆ | L1 curl_cffi |
| `www.google.com` | Google 搜索 | 1.0s/次 | ★★★★ | L2 真实 Chrome |
| `www.sogou.com` | 搜狗搜索 | 0.5s/次 | ★★☆ | L1 |
| `s.weibo.com` | 微博搜索 | 1.5s/次 | ★★★ | L2 |
| `www.zhihu.com` | 知乎搜索 | 2.0s/次 | ★★★★ | L2 + 登录态 |
| `www.sohu.com` | 搜狐搜索 | 0.5s/次 | ★★☆ | L1 |
| `wenshu.court.gov.cn` | 中国裁判文书网 | 3.0s/次 | ★★★★★ | L2 + 人工过滑块 |
| `zxgk.court.gov.cn` | 中国执行信息公开网 | 3.0s/次 | ★★★★★ | L2 + 人工过滑块 |

后两个**必须 L2 真实 Chrome + 手动过一次滑块**才能用。本 skill 的策略是
**脚本不爬，提供查询入口**让用户人工查。

---

## 2. 完整配置长什么样？

每条配置包含 6 大块：

### 2.1 基本信息
```python
{
    "name": "百度搜索",
    "homepage": "https://www.baidu.com/",
    "search_url": "https://www.baidu.com/s",
    "search_param": "wd",  # 搜索关键词的参数名
}
```

### 2.2 限速 / 重试
```python
{
    "rate_limit": 0.5,         # 每次请求间隔（秒）
    "max_retries": 3,          # 失败重试次数
    "blocked_retries": 2,      # 被风控后额外重试次数
}
```

### 2.3 Warmup 步骤
```python
[
    "GET https://www.baidu.com/  # 拿 BAIDUID / BD_HOME cookie"
]
```
**Warmup 是必须的**——搜索引擎靠 Cookie 区分真人/机器人。

### 2.4 Headers（真实 Chrome 131 指纹）
```python
{
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-CH-UA": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Referer": "https://www.baidu.com/",
}
```

### 2.5 解析提示
```python
{
    "result_selector": '<h3 class="t"><a href="URL">TITLE</a></h3>',
    "count_text": "约 X 个结果（百度新版已不显示）",
}
```

### 2.6 反爬说明
```
百度对裸 requests 一秒识别（TLS 指纹不符）。本 skill 默认 L1 curl_cffi
已能拿到搜索结果。如返回 1.4KB 短页 → 被风控，需等 5-10 分钟或换 IP。
```

---

## 3. 三种输出格式

### 3.1 Markdown 文档（`show` 命令）
人类可读，含反爬说明、解析提示。可贴到 README / 文档。

```bash
python scripts/crawl_config.py show baidu.com
```

### 3.2 Python 爬虫代码（`emit --format python`）
可执行：直接 `python xxx.py <关键词>` 跑。

```bash
python scripts/crawl_config.py emit baidu.com --format python > baidu_crawler.py
python baidu_crawler.py "亿达信息技术有限公司 欠薪"
```

代码模板（`curl_cffi.Session(impersonate="chrome131")`）：
```python
from curl_cffi import requests as cr

DOMAIN = "www.baidu.com"
SEARCH_URL = "https://www.baidu.com/s"
SEARCH_PARAM = "wd"
RATE_LIMIT = 0.5
WARMUP_URL = "https://www.baidu.com/"
DEFAULT_HEADERS = {...}  # 完整 Chrome 131 头

_session = None
def get_session():
    global _session
    if _session is None:
        _session = cr.Session(impersonate="chrome131")
    return _session

def warmup():
    get_session().get(WARMUP_URL, headers=DEFAULT_HEADERS, timeout=15)

def search(keyword: str, limit: int = 10):
    s = get_session()
    warmup()  # 拿 cookie
    time.sleep(RATE_LIMIT)
    r = s.get(SEARCH_URL, params={SEARCH_PARAM: keyword}, headers=DEFAULT_HEADERS)
    if r.status_code != 200 or len(r.text) < 30000:
        return []  # 被风控
    return []  # 按 parse_hints.result_selector 解析
```

### 3.3 curl 命令（`emit --format curl`）
人脑 / Postman / 终端用。

```bash
python scripts/crawl_config.py emit baidu.com --format curl
# 输出：
# 1. Warmup（拿 cookie）
# curl -c cookies.txt -A "Mozilla/5.0 ..." "https://www.baidu.com/"
# 2. 搜索
# curl -b cookies.txt -A "Mozilla/5.0 ..." "https://www.baidu.com/s?wd=亿达信息技术有限公司"
```

---

## 4. apply：把配置写入 browser_http 缓存

```bash
python scripts/crawl_config.py apply baidu.com
# ✓ baidu.com 的配置已写入缓存（key=crawl_config:baidu.com）
#   后续 data_fetcher.py 访问该域名时会自动用此配置
```

`apply` 调用 `cache.py` 的 `Cache.set()`，把配置存到 `~/.minimax/cache/.../cache.db` 里。
**30 天 TTL**。

---

## 5. 扩充新站点

在 `scripts/crawl_configs.py` 的 `CRAWL_CONFIGS` 字典里加：

```python
CRAWL_CONFIGS["example.com"] = {
    "name": "示例站点",
    "homepage": "https://example.com/",
    "search_url": "https://example.com/search",
    "search_param": "q",
    "rate_limit": 0.5,
    "max_retries": 2,
    "blocked_retries": 1,
    "warmup_steps": [
        "GET https://example.com/  # 拿 cookie"
    ],
    "headers": _chrome_headers(referer="https://example.com/"),
    "anti_bot_notes": "风控特点...",
    "parse_hints": {"result_selector": "..."},
}
```

**User-Agent 来源**：
- ✅ 真实 Chrome 隐身模式（DevTools 查 Network）
- ✅ `curl -A "..."` 配合 Chrome 的 User-Agent
- ❌ 不要用网上 Web 工具生成的"匿名 UA"
- ❌ 不要用 `python-requests/2.x` 这种明显机器人 UA

---

## 6. 与已有脚本层的关系

```
┌─────────────────────────────────────────────────────────┐
│ SKILL.md 步骤 0                                          │
│  "用户问爬取配置" → 大模型调 crawl_config.py            │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ crawl_config.py / crawl_configs.py                       │
│  list / show / emit / apply                              │
└─────────────────────────────────────────────────────────┘
                          ↓
                apply 写入 cache
                          ↓
┌─────────────────────────────────────────────────────────┐
│ data_fetcher.py / browser_http.py / fuzzy_resolve.py   │
│  默认 L1 curl_cffi 已经在跑；crawl_config 的 apply 走    │
│  用户配置层（不冲亵重写默认路径）                        │
└─────────────────────────────────────────────────────────┘
```

**核心原则**：crawl_config 是"用户配置层"（提供参考 + 写入覆盖），
不冲亵重写 browser_http 的默认 L1 实现。
