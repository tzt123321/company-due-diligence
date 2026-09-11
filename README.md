🎉 **本 skill 是 [Linux Do](https://linux.do) 社区的友链项目** — 欢迎在 Linux Do 分享使用体验

# company-due-diligence · 公司求职风险背调 Skill

> **项目初衷（作者原话）**：这是一个关于背调公司的 skills。用于关注公司的劳动仲裁信息，
> 避免打工人被坑。里面使用了类似指纹浏览器的设置，内置了脚本用于检索信息和模糊匹配公司工商信息。

> 给求职者用的公司背景调研（背调）：**聚焦求职风险，不是投资尽调**。
> 自动扫描被执行/经营异常/劳动仲裁/欠薪/社保等强信号，叠加员工真实评价入口，
> 输出是否值得投递的判断、3-5 个具体坑点、面试重点提问清单，以及可交互的红绿灯报告。

**Company due-diligence skill for job seekers.** It focuses on employment risks —
enforcement, business anomalies, labor arbitration, wage arrears, social-security
problems — cross-checked with employee-review entries, and produces a go/no-go
verdict, concrete pitfalls, and interview question lists in Markdown + an
interactive traffic-light HTML report. All fetching is done by local Python
scripts that mimic a real browser (TLS fingerprinting); the LLM does the analysis.

[English](#english-readme) ｜ [中文文档](#) ｜ License: [GPL-3.0](./LICENSE)



## ✨ 功能特性

- 🔍 **品牌名消歧**：招聘平台写的"某科技" → 自动识别出"某科技有限公司"及其多个地区注册主体，提示按城市/地址确认目标主体（5 策略 + 多源印证打分）
- 🚨 **7 条强红线一票否决**：被执行人 / 经营异常·吊销 / 欠薪黑名单 / 劳动仲裁频繁 / 法人频繁变更 / 诉讼频繁 / 社保欠缴
- ⚠️ **16 个风险关键词扫描**：欠薪、劳动仲裁、被执行、失信、经营异常、社保、裁员、诉讼、破产清算、跑路……带"归属判定"，杜绝张冠李戴
- 💬 **员工评价入口收集**：看准/脉脉/BOSS直聘/知乎/小红书等入口链接（合规：不抓取评价原文）
- 📊 **三份输出**：结构化 JSON（喂给大模型）＋ Markdown 报告骨架 ＋ 交互式红绿灯 HTML 仪表盘
- 🧪 **三层反爬架构**：L1 curl_cffi 指纹模拟（默认）→ L2 真实 Chrome → L3 指纹浏览器 API
- 💾 **SQLite 分级缓存**：工商 30 天 / 风险 3 天 / 新闻 1 天，二次背调秒回
- 🌍 **支持境外公司**：`--global-mode` 切换 Bing 主引擎 + OpenCorporates 注册库
- 🖥 **Web UI（v1.3+）**：浏览器开箱即用，零命令行

## 📸 示例输出

![示例报告](docs/screenshot.png)

*示例：演示数据生成的红绿灯仪表盘（完全虚构的公司与链接，不含任何真实企业信息）*

## 📦 项目结构

```
company-due-diligence/
├── SKILL.md                          # Skill 主入口（LLM 工作流 + CLI 速查 + 微调指南）
├── README.md                         # 本文件
├── LICENSE                           # GPL-3.0
├── conversation-summary-2026-08-30.md# 设计过程复盘（v1.0→L1/L2/L3 架构演进）
├── assets/
│   └── report-template.html          # 红绿灯仪表盘模板（自包含单文件）
├── references/
│   ├── data-sources.md               # 按司法辖区的数据源清单
│   ├── risk-signals.md               # 风险信号定义与评分模型
│   ├── red-line-rules.md             # 7 条强红线判定规则
│   └── output-template.md            # 报告九段结构模板
├── data/
│   └── brand_map.json                # 品牌→工商全称映射表（可扩充）
├── scripts/
│   ├── data_fetcher.py               # 主抓取器（CLI + 库双用法）
│   ├── browser_http.py               # L1 指纹抓取层（curl_cffi）
│   ├── fuzzy_resolve.py              # 公司名消歧（5 策略）
│   ├── cache.py                      # SQLite 分级 TTL 缓存
│   ├── real_browser.py               # L2 真实 Chrome（可选）
│   ├── fingerprint_browser.py        # L3 指纹浏览器 API（可选）
│   ├── requirements.txt
│   └── README.md                     # 脚本使用说明
└── web/                              # C 端 Web UI（v1.3+）
    ├── app.py                        # Flask 服务
    └── config_loader.py              # JSON 配置加载
```

## 🚀 安装

### 方式一：作为 DSH（DeepSeek Harness）Skill 安装

```bash
# 用户级：所有会话可用（推荐）
mkdir -p ~/.dsh/skills
cp -r company-due-diligence ~/.dsh/skills/

# 或项目级：仅当前项目可用
mkdir -p <项目根>/.dsh/skills
cp -r company-due-diligence <项目根>/.dsh/skills/
```

新开会话后，在技能库里选择 `company-due-diligence`，然后直接说：
**"帮我背调一下 XX 公司"** 即可。

### 方式二：作为 MiniMax / Claude Code Agent Skill 安装

```bash
mkdir -p ~/.minimax/skills      # 或 ~/.agents/skills
cp -r company-due-diligence ~/.minimax/skills/
```

### 方式三：独立脚本使用（不依赖任何 Agent）

```bash
cd company-due-diligence/scripts
pip install -r requirements.txt        # 仅需 curl_cffi + beautifulsoup4（L1）

python data_fetcher.py all "示例科技有限公司"          # 全流程背调
python data_fetcher.py all "OpenAI" --global-mode --engines bing,baidu   # 境外公司
python data_fetcher.py resolve "示例科技"               # 只做公司名消歧
python data_fetcher.py keyword-sweep "公司名" --keywords 欠薪,劳动仲裁
python data_fetcher.py --clear-cache           # 清空缓存
```

输出自动写入 `output/<公司名>/`：`<公司名>.json`（机器可读）、`.md`（报告骨架）、`.html`（仪表盘）。

### 方式四：C 端 Web UI（v1.3+，零命令行）

```bash
# 1) 装依赖（已有 flask/curl_cffi 即可）
pip install flask curl_cffi

# 2) 启动 Web UI
cd company-due-diligence
python web/app.py
# 启动后会显示：
#   启动 Web UI: http://127.0.0.1:8765
#   L1: ✓ curl_cffi  |  L2: ✗ undetected-chromedriver 缺  |  L3: ✗ 指纹浏览器未配置

# 3) 浏览器打开 http://127.0.0.1:8765
#    - 输入公司名 → 点"开始背调"
#    - 30-90 秒后出红绿灯报告
#    - 一键下载 MD / HTML / JSON
```

**配置文件**（`config.json`，自动生成在 skill 根目录）：

```json
{
  "rate_limit": 0.3,
  "engines": {
    "CN": ["baidu", "bing"],
    "US": ["bing", "baidu", "ddg"]
  },
  "site_strategy": {
    "www.baidu.com": { "rate_limit": 0.5, "max_retries": 3 }
  },
  "output": { "dir": "<skill>/output" },
  "web": { "host": "127.0.0.1", "port": 8765 }
}
```

**REST API**（可被前端/agent 调用）：

| 路由 | 方法 | 用途 |
|---|---|---|
| `/` | GET | 暗色仪表盘界面 |
| `/api/run` | POST | 跑全流程，返回 JSON 报告 |
| `/api/download/md?name=X&jurisdiction=CN` | GET | 下载 Markdown |
| `/api/download/html?name=X&jurisdiction=CN` | GET | 下载 HTML 仪表盘 |
| `/api/download/json?name=X&jurisdiction=CN` | GET | 下载原始 JSON |
| `/api/health` | GET | L1/L2/L3 可用性检查 |

## 🧠 设计要点

### 三层反爬架构（模拟真人查询）

| 层 | 实现 | 默认 | 说明 |
|---|---|---|---|
| L1 | curl_cffi 模拟 Chrome 131 TLS 指纹 | ✅ | 零额外成本。实测百度 305KB/0 标题（裸 requests）→ **1.19MB/9 标题** |
| L2 | undetected-chromedriver 真实 Chrome | 可选 | `pip install undetected-chromedriver`，过验证码场景 |
| L3 | BitBrowser/AdsPower 指纹浏览器 API | 可选 | 裁判文书网等强风控站，需付费服务 |

### 消歧 5 策略

`brand_map`（映射表 O(1)）→ `suffix_complete`（补全后缀）→ `opencorporates`（多辖区注册库）
→ `bing` → `duckduckgo`。同一候选被多个独立来源命中 +10 分；家族多主体互证 → 判定品牌真实存在。

### 报告九段结构

结论速览（评分/信号灯）→ 主体识别 → 工商信息 → 红线核验表（7 条带证据）
→ 风险信号扫描 → 员工评价入口 → 坑点清单（3-5 个）→ 面试提问清单 → manual_required（人工核实清单）

**设计哲学：未验证 ≠ 无风险。** 官方渠道（裁判文书网/执行公开网/工商系统）需验证码时，
脚本一律标记 `manual_required` 并给入口，绝不让大模型假装"全绿"。

## 🆕 v1.3 C 端优化变更

| 改动 | 收益 |
|---|---|
| 新增 `web/app.py` (Flask 3.1) | 浏览器开箱即用，零命令行 |
| 新增 `web/config_loader.py` | JSON 配置支持 site-specific 限速/重试/代理（不引入 YAML 依赖）|
| Web UI 暗色主题 + 进度提示 | 现代感、可读性 |
| 一键下载 MD/HTML/JSON | 报告可分享、可归档 |
| `/api/health` 路由 | L1/L2/L3 可用性可视化 |
| README 加 Web UI 章节 + REST API 文档 | 降低上手门槛 |

**踩坑经验（之前会话总结）**：
- `argparse` 全局 flag 必须同时在主 parser 和子 parser `parents` 双声明
- `_cache` 必须在 opts 对象上提前挂好
- `--clear-cache` 改用 SQL `LIKE %name%` 才能清掉带 `days` 后缀的 key
- L1（curl_cffi）已默认开启，**L2/L3 主动放弃抓员工评价**（合规优先）

## 🔧 微调指南

脚本是"数据管道"，大模型是"分析师"。定制方式：

- **关键词/严重度**：`scripts/data_fetcher.py` 顶部 `SIGNAL_DEFS`、`DEFAULT_SWEEP_KEYWORDS`
- **红线规则**：`references/red-line-rules.md`（人读）与 `RED_LINES`（机读）同步改
- **评分权重**：`score_report()`（severe 40 / medium 25 / low 12）
- **坑点/提问**：`PITFALL_TEMPLATES` / `INTERVIEW_QUESTIONS`
- **品牌映射扩充**：`data/brand_map.json`（高频公司名沉淀后 O(1) 命中）
- **报告 UI**：`assets/report-template.html`（自包含，改样式/文案直接编辑）

## ⚠️ 已知限制

1. CN 官方数据源需验证码/登录 → 只能提供人工核验入口
2. OpenCorporates 公共 API 偶发 401（可设 `OPENCORPORATES_API_KEY`）
3. Bing 中文搜索质量差（会把中文公司名拆成单字）→ CN 公司默认百度主引擎
4. DDG 部分网络超时 → 自动降级
5. 员工评价只收集入口链接，不抓原文（合规）
6. 小众公司搜不到 ≠ 没风险，报告会明确标注

## ⚖️ 合规声明

- 遵守目标站点 robots/限速（默认 0.3s/次），不做高频爬取
- 不自动抓取员工评价原文、不采集个人信息
- 报告如实标注证据等级：官方公告 > 新闻媒体 > 论坛问答 > 招聘平台
- 数据仅来自公开搜索引擎结果，用途限于求职决策参考

## 🤝 贡献

欢迎 PR：
- 扩充 `brand_map.json`（品牌 → 工商全称）
- 新增风险关键词与红线规则
- 改进各司法辖区数据源接入（见 `references/data-sources.md`）
- 报告模板 UI 优化

## 📄 License

[GPL-3.0](./LICENSE)

---

<a id="english-readme"></a>

## English Readme (Summary)

**company-due-diligence** is a job-seeker oriented company background-check skill
for LLM agents (DeepSeek Harness / MiniMax / Claude Code) with local Python
fetchers. It resolves brand names to registered entities, scans 16 risk keywords
(wage arrears, labor arbitration, enforcement, business anomalies, social
security, layoffs, lawsuits, bankruptcy...), checks 7 one-vote-veto red lines
with attributable evidence, collects employee-review entry links, and emits a
scored verdict with pitfalls and interview questions in Markdown + an interactive
HTML dashboard.

**Install:** copy the folder to `~/.dsh/skills/` (DSH), `~/.minimax/skills/`
or `~/.agents/skills/`, or run standalone: `pip install -r scripts/requirements.txt`
then `python scripts/data_fetcher.py all "Company Name"`.
For non-Chinese companies add `--global-mode`.

**Design philosophy:** *unverified ≠ no risk.* Captcha-gated official registries
are always reported as `manual_required` entries with direct links instead of
being faked as clean.
