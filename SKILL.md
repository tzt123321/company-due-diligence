---
name: company-due-diligence
description: >
  求职视角的公司背景调研（背调）。聚焦求职风险：被执行/经营异常/劳动仲裁/欠薪/社保问题
  等强信号重点标记，叠加员工真实评价入口，输出是否值得投递的判断、3-5 个具体坑点、
  面试重点提问清单，以及可交互的红绿灯 HTML 报告。当用户要求"背调某公司/查公司有没有坑/
  值不值得投递面试"时使用。本地 Python 脚本结构化抓取（L1 curl_cffi 指纹模拟真实浏览器），
  大模型负责分析、判红与报告撰写。
---

# Company Due-Diligence（求职背调）Skill

> 给求职者用的公司风险背调。**不是投资尽调**：只关心"这公司值不值得投递、面试时问什么"。

## 设计哲学（务必遵守）

1. **脚本能拿到的结构化返回，拿不到的标 manual_required 并给入口** —— 决策权在用户。
2. **未验证 ≠ 无风险**。搜索结果 0 命中 ≠ 公司干净，官方渠道进不去就标"未验证"，
   不许假装全绿。
3. **平台名 ≠ 工商全称**。招聘平台显示"某科技"，工商主体可能是
   "某科技有限公司"及其多个地区注册主体 —— 先消歧，再背调。
4. **红线一票否决**（7 条，见 references/red-line-rules.md），但必须证据可核验。

## 快速开始

```bash
cd skills/company-due-diligence/scripts
pip install curl_cffi beautifulsoup4          # 仅 L1 必需；undetected-chromedriver 可选（L2）
python data_fetcher.py all "公司名"           # 全流程：消歧→工商→风险扫描→新闻→评价→评分→报告
python data_fetcher.py all "OpenAI" --global-mode --engines bing,baidu
```

产物自动写入 `output/<公司名>/`：`<公司名>.json`（机器可读）、`.md`（报告骨架）、`.html`（红绿灯仪表盘）。

## LLM 工作流（背调一家公司时按此执行）

### Step 0 — 判定模式
- 含中文 → CN 模式（默认，百度主引擎）；纯英文/境外 → `--global-mode`（Bing 主引擎）。
- 用户给的是平台简称（如"某科技"）→ 先跑 `resolve`；给的是全称 → 直接跑 `all`。

### Step 1 — 主体消歧
```bash
python data_fetcher.py resolve "示例科技"
```
解读：`matched` / `recommended` / `candidates`。同名主体多（家族聚合）时，
**报告中必须提示用户按招聘信息里的城市/地址/岗位确认具体主体**，再针对该主体核验。

### Step 2 — 全流程抓取
```bash
python data_fetcher.py all "<工商全称或已消歧主体>"            # 默认 16 个风险关键词
python data_fetcher.py all "<公司名>" --keywords 欠薪,劳动仲裁   # 自定义关键词
```
`all` 内部依次执行：resolve → basic（爱企查工商面板）→ keyword-sweep（16 关键词×多引擎）
→ news → reviews。**耗时约 1-5 分钟**（限速 0.3s/关键词 + 百度页 1MB），有缓存后秒回。

### Step 3 — 分析 JSON（核心工作）
`all` 输出 JSON 的关键字段（供大模型消费）：

| 字段 | 含义 | 微调/分析要点 |
|---|---|---|
| `basic.resolve` | 消歧结果 | 确认主体；同名多→风险归属存疑 |
| `basic.enterprise_basic` | 法定代表人/注册资本/成立时间/状态 | 状态=吊销/注销 → 红线 2 疑似命中 |
| `red_lines[]` | 7 条红线 {hit\|clean\|unverified} + 证据 | hit→一票否决；unverified→人工核实 |
| `signals[]` | 每关键词 {n_hits, strong_hits[]} | strong_hits 带标题+URL，逐条看 |
| `score` | 100 分制 + 🟢🟡🔴 | 结论速览依据 |
| `pitfalls` | 脚本预生成的坑点 | 大模型要加工成"具体可执行的坑点" |
| `interview_questions` | 8 条默认提问 | 按公司情况增删 |
| `manual_required` | 需人工核验清单（官方渠道+验证码站） | 必须原样保留进报告 |

### Step 4 — 判红与结论
- 任一红线 hit → 🔴 不建议投递（除非用户能推翻证据链）。
- 无 hit 但 unverified 多 → 🟡 谨慎 + 把核实项列清楚。
- 全部 clean 且评价无重大负面 → 🟢 可正常评估。
- **重点标记**：被执行/经营异常/劳动仲裁/欠薪/社保类信号，命中就在报告顶部红字列出。

### Step 5 — 撰写报告（九段结构，见 references/output-template.md）
Markdown 正文 + HTML 仪表盘（已自动生成骨架，直接补充完善）：
1. 结论速览（评分/信号灯/一句话结论）2. 主体识别 3. 工商信息 4. 红线核验表
5. 风险信号扫描 6. 员工评价入口 7. 坑点清单（3-5 个，每条带证据+面试怎么问）
8. 面试提问清单 9. manual_required。

## CLI 参考

```bash
# 各子命令
python data_fetcher.py resolve "示例科技"
python data_fetcher.py basic "示例科技有限公司"
python data_fetcher.py keyword-sweep "公司名" --keywords 欠薪,劳动仲裁,被执行
python data_fetcher.py news "公司名"
python data_fetcher.py reviews "公司名"
python data_fetcher.py all "公司名" [--markdown]

# 公共参数（子命令前后都可放）
--engines baidu,bing       # 搜索引擎优先级（境外: bing,baidu[,ddg]）
--rate-limit 0.3           # 关键词间隔秒数
--no-cache                 # 跳过缓存
--global-mode              # 境外模式
--outdir DIR               # 输出目录

# 缓存管理（顶层参数，不依赖子命令）
python data_fetcher.py --clear-cache            # 清空全部
python data_fetcher.py --clear-cache 示例   # LIKE 模糊删除
python cache.py --stats                         # 查看缓存统计
```

环境变量：`DD_CACHE_DIR`（缓存目录）、`DD_BRAND_MAP`（品牌映射表路径）、
`OPENCORPORATES_API_KEY`（境外注册库）、`BITBROWSER_API/BITBROWSER_PROFILE_ID` 或
`ADSPOWER_API/ADSPOWER_USER_ID`（L3 指纹浏览器）。

## 三层浏览器架构（反爬阶梯）

| 层 | 实现 | 默认 | 何时用 |
|---|---|---|---|
| L1 | curl_cffi 模拟 Chrome 131 TLS 指纹（`browser_http.py`） | ✅ 开 | 绝大多数场景；裸 requests 被百度秒识别，L1 实测 0→9 条命中 |
| L2 | undetected-chromedriver 真实 Chrome（`real_browser.py`） | 关 | L1 被验证码拦截/0 命中时；本机已装 |
| L3 | 指纹浏览器 API BitBrowser/AdsPower（`fingerprint_browser.py`） | 关 | 裁判文书网/执行公开网等强风控站；需付费服务 |

## 已知限制（写进报告的边界）

1. CN 官方数据源（裁判文书网/执行公开网/工商系统）需验证码/登录 → 只能给 manual_required 入口。
2. OpenCorporates 公共 API 偶发 401 → 设 API key。
3. Bing 中文搜索质量差（会把中文公司名拆成单字）→ CN 公司用百度主引擎。
4. DDG 部分网络超时 → 自动降级，不影响主流程。
5. 员工评价只收集入口链接，不抓原文（合规）。
6. 小众公司搜不到 ≠ 没风险，报告里明确写"公开网页无记录，不代表无风险"。

## 微调指南（大模型如何定制这套 skill）

**架构认知**：脚本是"数据管道"，大模型是"分析师"。微调 = 改管道的参数 + 改分析的规则。

- **改关键词**：`data_fetcher.py` 顶部 `SIGNAL_DEFS` / `DEFAULT_SWEEP_KEYWORDS`，
  例如加"竞业限制""股权激励"等新维度；`--keywords` 命令行也可临时指定。
- **改红线**：`references/red-line-rules.md`（人读）+ `data_fetcher.py` 的 `RED_LINES`（机读）
  必须同步改。
- **改评分**：`score_report()` 的扣分权重（severe 40 / medium 25 / low 12）。
- **改坑点/提问**：`PITFALL_TEMPLATES` / `INTERVIEW_QUESTIONS`。
- **扩充品牌映射**：`data/brand_map.json`（品牌名 → 工商全称 + 国家 + 备注），
  微调时把高频公司名沉淀进去，O(1) 命中免搜索。
- **改报告模板**：`assets/report-template.html`（UI）+ `references/output-template.md`（结构）。
- **数据流**：`all 公司名` → `output/<公司名>.json` → 大模型按九段结构出报告。
  微调后自测：跑一家已知公司，核对消歧、红线判定、坑点是否合理。

## 合规红线（脚本与模型都必须遵守）

- 尊重 robots/限速（默认 0.3s/次），不做高频爬取。
- 不自动抓取员工评价原文、不采集个人信息。
- 报告如实标注证据等级：官方公告 > 新闻媒体 > 论坛问答 > 招聘平台。

## 步骤 0——C 端增强：爬取配置生成（headers / Cookie / 限速）

> 当用户问"帮我爬 XXX 网站"或"用脚本读取 XXX 站点 3 条"这类请求时，skill 应该**真实可执行**的爬取配置：
> 把大模型的即兴 Header / Cookie / 限速 生成已知站点上的 Python 代码/curl 命令。

### 使用方式

```bash
# 1. 查看某站点有哪些预定义好的爬取配置
python scripts/crawl_config.py show baidu.com

# 2. 生成完整的爬取工具包（Python 代码块 + curl 命令块）
python scripts/crawl_config.py emit baidu.com

# 3. 生成完整的爬取工具包并应用到 browser_http 缓存
python scripts/crawl_config.py apply baidu.com

# 4. 列出所有已预定义的站点
python scripts/crawl_config.py list
```

### 预定义的站点配置

源代码包含 **7 个常见站点**的配置 + 2 个优质资源站（`references/crawl-configs.md` 有完整文档）。
用户在 `scripts/crawl_configs.py` 中可以：

- 直接用 `show <domain>` 查看
- 用模板添加新站点（`CRAWL_CONFIGS` 字典）

### 生成的真实内容样例

```python
# scripts/crawl_config.py emit baidu.com 输出的一部分
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,...",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Sec-CH-UA": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "Referer": "https://www.baidu.com/",
}
# 限速：0.5 秒起，失败自动重试 3 次，重试 backoff 1s
# Cookie：先访问主页拿 BAIDUID / BD_HOME 等 session cookie
```

### 用法实例

> 用户："帮我爬百度 '亿达信息 欠薪'，按以下操作"

```bash
# 1. 查看百度的配置
python scripts/crawl_config.py show baidu.com

# 2. 生成完整的 Python 代码/curl 命令
python scripts/crawl_config.py emit baidu.com > /tmp/baidu_crawler.py

# 3. 直接 apply 到 browser_http 缓存
python scripts/crawl_config.py apply baidu.com

# 4. 用了！后续 data_fetcher.py 百度请求会自动用 baidu.com 的配置
```

### 与已有脚本作用的关系

- 标重**不冲亵重写** `browser_http.py` 现状，仅写它的**用户配置层**（session_headers / session_cookies / site_rates），不影响默认路径。
- 预定义：7 个常见站（baidu / bing / google / sogou / weibo / zhihu / sohu），遇到新站点可用原代码扩充 `scripts/crawl_configs.py` 中 `CRAWL_CONFIGS` 字典。
- 扩充方法：真正新的 User-Agent 应该来自**真实浏览器头**（curl -A UA 或 Chrome 开启隐身模式注查看），不要用 Web 生成的供使用的 UA 套。
