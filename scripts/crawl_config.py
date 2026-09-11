#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crawl_config.py — 站点爬取配置生成器（CLI + 库）

设计目标：
  - 一步生成"真实可执行"的爬取配置（headers / cookie / 限速）
  - 直接给大模型复制贴入或人脑读
  - apply 命令能写到 browser_http 缓存让 data_fetcher 自动用

CLI 用法：
    py crawl_config.py list                         # 列出所有预定义站点
    py crawl_config.py show baidu.com                # 显示某站配置
    py crawl_config.py emit baidu.com                # 输出 Python 代码块 + curl 命令
    py crawl_config.py emit baidu.com --format json  # 输出 JSON 配置
    py crawl_config.py apply baidu.com               # 写入 browser_http 缓存

库用法：
    from crawl_config import get_crawler_snippet
    snippet = get_crawler_snippet("baidu.com")
    print(snippet)
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 复用同一目录的配置数据源
sys.path.insert(0, str(Path(__file__).parent))
try:
    from crawl_configs import CRAWL_CONFIGS, get_config, list_domains, UA_POOL
except ImportError as e:
    print(f"无法导入 crawl_configs: {e}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 格式化：人类可读
# ---------------------------------------------------------------------------

def format_config_human(cfg: dict) -> str:
    """把配置格式化成人类可读的 markdown"""
    lines = []
    lines.append(f"# 站点爬取配置：{cfg['name']} ({cfg.get('homepage', '')})")
    lines.append("")
    lines.append(f"- **首页**：`{cfg.get('homepage', 'N/A')}`")
    lines.append(f"- **搜索 URL**：`{cfg.get('search_url', 'N/A')}`")
    lines.append(f"- **搜索参数名**：`{cfg.get('search_param', 'q')}`")
    lines.append(f"- **限速**：{cfg['rate_limit']} 秒/请求")
    lines.append(f"- **最大重试**：{cfg['max_retries']} 次")
    lines.append(f"- **风控后重试**：{cfg.get('blocked_retries', 0)} 次")
    lines.append("")
    lines.append("## 限速 / 重试策略")
    lines.append(f"- 每次请求间隔 ≥ {cfg['rate_limit']}s")
    lines.append(f"- 失败自动重试 {cfg['max_retries']} 次，backoff 1s, 2s, 4s")
    if cfg.get('blocked_retries', 0):
        lines.append(f"- 触发风控后额外重试 {cfg['blocked_retries']} 次，间隔 5-10s")
    lines.append("")
    lines.append("## Warmup 步骤（必须先做）")
    for step in cfg.get('warmup_steps', []):
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Headers（直接复制）")
    lines.append("```python")
    lines.append("headers = {")
    for k, v in cfg['headers'].items():
        # 转义字符串值
        v_escaped = v.replace("'", "\\'")
        lines.append(f"    '{k}': '{v_escaped}',")
    lines.append("}")
    lines.append("```")
    lines.append("")
    if cfg.get('parse_hints'):
        lines.append("## 解析提示")
        for k, v in cfg['parse_hints'].items():
            lines.append(f"- **{k}**：`{v}`")
        lines.append("")
    if cfg.get('anti_bot_notes'):
        lines.append("## 反爬说明")
        lines.append(cfg['anti_bot_notes'])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 格式化：Python 代码（可直接复制贴入脚本）
# ---------------------------------------------------------------------------

def format_config_python(cfg: dict) -> str:
    """生成可直接 import / 复制贴入的 Python 爬虫代码"""
    domain = cfg.get('homepage', 'https://example.com/').split('//')[1].rstrip('/')
    safe_name = domain.replace('.', '_').replace('-', '_')

    return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
{cfg['name']} 爬虫（自动生成）
域名：{domain}
限速：{cfg['rate_limit']}s/次
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from curl_cffi import requests as cr
except ImportError:
    print("pip install curl_cffi", file=sys.stderr)
    sys.exit(1)


DOMAIN = "{domain}"
SEARCH_URL = "{cfg.get('search_url', '')}"
SEARCH_PARAM = "{cfg.get('search_param', 'q')}"
RATE_LIMIT = {cfg['rate_limit']}
WARMUP_URL = "{cfg.get('homepage', '')}"

# 真实 Chrome 131 headers（带指纹）
DEFAULT_HEADERS = {repr(cfg['headers'])}

_session = None


def get_session():
    global _session
    if _session is None:
        _session = cr.Session(impersonate="chrome131")
    return _session


def warmup():
    """先访问首页拿 Cookie"""
    s = get_session()
    s.get(WARMUP_URL, headers=DEFAULT_HEADERS, timeout=15)


def search(keyword: str, limit: int = 10) -> list[dict]:
    """
    搜索关键词，返回 [(title, url), ...]
    """
    import time
    s = get_session()
    warmup()  # 拿 cookie
    time.sleep(RATE_LIMIT)
    params = {{SEARCH_PARAM: keyword}}
    r = s.get(SEARCH_URL, params=params, headers=DEFAULT_HEADERS, timeout=20)
    if r.status_code != 200 or len(r.text) < 30000:
        return []  # 被风控
    # TODO: 按 parse_hints.result_selector 解析
    return []  # 由调用方按站点定制解析


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python {safe_name}_crawler.py <关键词>")
        sys.exit(1)
    results = search(sys.argv[1])
    for t, u in results:
        print(f"- {{t}}")
        print(f"  {{u}}")
'''


# ---------------------------------------------------------------------------
# 格式化：curl 命令
# ---------------------------------------------------------------------------

def format_config_curl(cfg: dict) -> str:
    """生成 curl 命令（人脑/Postman/终端用）"""
    lines = []
    lines.append(f"# {cfg['name']} curl 爬取示例")
    lines.append("")
    lines.append("# 1. Warmup（拿 cookie）")
    lines.append(f'curl -c cookies.txt -A "{cfg["headers"]["User-Agent"]}" \\')
    lines.append(f'  -H "Accept: {cfg["headers"]["Accept"][:50]}..." \\')
    lines.append(f'  "{cfg.get("homepage", "")}"')
    lines.append("")
    lines.append("# 2. 搜索")
    params = f'{cfg.get("search_param", "q")}=亿达信息技术有限公司+欠薪'
    lines.append(f'curl -b cookies.txt -A "{cfg["headers"]["User-Agent"]}" \\')
    lines.append(f'  -H "Referer: {cfg.get("homepage", "")}" \\')
    lines.append(f'  -H "Accept-Language: zh-CN,zh;q=0.9" \\')
    lines.append(f'  "{cfg.get("search_url", "")}?{params}"')
    lines.append("")
    lines.append(f"# 限速：每 {cfg['rate_limit']} 秒一次")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 格式化：JSON
# ---------------------------------------------------------------------------

def format_config_json(cfg: dict) -> str:
    return json.dumps(cfg, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# apply: 写入 browser_http 缓存
# ---------------------------------------------------------------------------

def apply_config(domain: str) -> dict:
    """
    把站点配置写入 browser_http 的 session cache。
    之后 data_fetcher.py 访问该域名时会自动用。
    """
    cfg = get_config(domain)
    if not cfg:
        return {"ok": False, "error": f"未找到 {domain} 的配置"}

    # 写入 cache.py 的 SQLite kv 存储
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from cache import Cache
        cache = Cache()
        key = f"crawl_config:{domain}"
        # Cache.set 签名: (self, key, category, value)
        cache.set(key, "crawl_config", cfg)
        return {"ok": True, "key": key, "domain": domain}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="站点爬取配置生成器（求职背调场景专用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # list
    sub.add_parser("list", help="列出所有预定义站点")

    # show
    sh = sub.add_parser("show", help="显示某站配置（人类可读）")
    sh.add_argument("domain")

    # emit
    em = sub.add_parser("emit", help="输出可执行的 Python / curl / JSON")
    em.add_argument("domain")
    em.add_argument("--format", choices=["python", "curl", "json", "md"],
                    default="python")

    # apply
    ap = sub.add_parser("apply", help="把配置写入 browser_http 缓存")
    ap.add_argument("domain")

    args = p.parse_args()

    if args.cmd == "list":
        print("已配置的爬取站点：")
        print(f"  {'域名':<30s}  {'名称':<20s}  {'限速':<6s}  备注")
        print(f"  {'-'*30}  {'-'*20}  {'-'*6}  {'-'*30}")
        for d in list_domains():
            cfg = CRAWL_CONFIGS[d]
            note = cfg.get('anti_bot_notes', '')[:30].replace('\n', ' ')
            print(f"  {d:<30s}  {cfg['name']:<20s}  {cfg['rate_limit']}s    {note}")
        print()
        print(f"共 {len(list_domains())} 个站点。使用 'show <domain>' 查看详情。")

    elif args.cmd == "show":
        cfg = get_config(args.domain)
        if not cfg:
            print(f"✗ 未找到 {args.domain} 的配置", file=sys.stderr)
            print(f"  可用站点: {', '.join(list_domains())}", file=sys.stderr)
            sys.exit(1)
        print(format_config_human(cfg))

    elif args.cmd == "emit":
        cfg = get_config(args.domain)
        if not cfg:
            print(f"✗ 未找到 {args.domain} 的配置", file=sys.stderr)
            sys.exit(1)
        if args.format == "python":
            print(format_config_python(cfg))
        elif args.format == "curl":
            print(format_config_curl(cfg))
        elif args.format == "json":
            print(format_config_json(cfg))
        elif args.format == "md":
            print(format_config_human(cfg))

    elif args.cmd == "apply":
        result = apply_config(args.domain)
        if result.get("ok"):
            print(f"✓ {args.domain} 的配置已写入缓存（key={result.get('key')}）")
            print("  后续 data_fetcher.py 访问该域名时会自动用此配置")
        else:
            print(f"✗ 写入失败: {result.get('error')}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
