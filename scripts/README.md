# scripts — 公司背调抓取脚本

## 安装

```bash
pip install curl_cffi beautifulsoup4        # L1 必需（已装：curl_cffi 0.15 / bs4 4.12）
pip install undetected-chromedriver          # L2 可选（本机已装 3.5.5，需本机 Chrome）
pip install websocket-client                 # L3 CDP 取回可选
```

## 文件职责

| 文件 | 职责 |
|---|---|
| `browser_http.py` | **L1 指纹层**：curl_cffi 模拟 Chrome 131，百度/Bing/DDG 搜索解析，GBK 跳转还原，验证码检测 |
| `fuzzy_resolve.py` | **消歧**：brand_map / suffix_complete / opencorporates / bing / ddg 五策略 + 家族聚合打分 |
| `data_fetcher.py` | **主抓取器**：resolve/basic/keyword-sweep/news/reviews/all 子命令 + 红线评估 + 评分 + 报告渲染 |
| `cache.py` | SQLite 缓存（basic/resolve 30d、search/review 7d、risk 3d、news 1d），LIKE 模糊删除 |
| `real_browser.py` | **L2**：undetected-chromedriver 驱动真实 Chrome（可过验证码场景） |
| `fingerprint_browser.py` | **L3**：BitBrowser/AdsPower 指纹浏览器 API 接口（需付费服务） |

## 快速上手

```bash
# 全流程（推荐）：消歧 → 工商 → 16 关键词风险扫描 → 新闻 → 评价入口 → 评分 → 三份报告
python data_fetcher.py all "示例科技有限公司"

# 境外公司
python data_fetcher.py all "OpenAI" --global-mode --engines bing,baidu

# 只看某个维度
python data_fetcher.py resolve "示例科技"
python data_fetcher.py keyword-sweep "示例科技有限公司" --keywords 欠薪,劳动仲裁
python data_fetcher.py reviews "公司名"

# 缓存
python data_fetcher.py --clear-cache 示例     # 顶层参数，LIKE 模糊删除
python cache.py --stats
```

输出：`output/<公司名>/{<公司名>.json, .md, .html}`（HTML 是红绿灯仪表盘，JSON 供大模型分析）。

## 实测数据（某公司 case，2026-08）

| 模式 | 裸 requests | L1（curl_cffi + warmup） |
|---|---|---|
| 百度页大小 | 305KB / 0 标题 | **1.19MB / 9 标题** |
| "示例公司 欠薪"命中 | 0 | **9 条**（含判决书/欠薪黑名单/招聘/劳动保障公告） |

## 已知限制与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `blocked: true` | 引擎验证码/风控 | 稍等重试；或 L2 `real_browser.py`；或换引擎 |
| OpenCorporates 401 | 公共 API 限流 | 设 `OPENCORPORATES_API_KEY` |
| Bing 中文结果差 | Bing 把中文拆单字 | CN 公司用默认 `baidu,bing` 顺序 |
| DDG 超时 | 网络环境 | 自动降级，不影响主流程 |
| 缓存删不掉 | key 编码差异 | `--clear-cache <关键词>` 是 LIKE 匹配，已修复 |
| argparse 参数报错 | flag 位置 | 公共参数主/子 parser 双声明，放哪都行 |

## 环境变量

| 变量 | 用途 |
|---|---|
| `DD_CACHE_DIR` | 缓存目录（默认 skill 内 data/cache） |
| `DD_BRAND_MAP` | 品牌映射表路径 |
| `OPENCORPORATES_API_KEY` | OpenCorporates API key |
| `BITBROWSER_API` / `BITBROWSER_PROFILE_ID` | L3 BitBrowser 指纹浏览器 |
| `ADSPOWER_API` / `ADSPOWER_USER_ID` | L3 AdsPower 指纹浏览器 |
