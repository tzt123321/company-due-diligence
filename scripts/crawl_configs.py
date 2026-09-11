#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crawl_configs.py — 站点爬取配置数据源

设计目标：
  - 给大模型/用户"真实可执行"的爬取配置（不是 Web 生成的 dummy UA）
  - 覆盖求职背调场景常用的 7 个站点
  - 字段：headers、cookie_jar、限速、重试、warmup 步骤
  - 用户可扩充

使用：
  from crawl_configs import CRAWL_CONFIGS, get_config
  cfg = get_config("baidu.com")
  print(cfg["headers"])
  print(cfg["rate_limit"])
"""

# ---------------------------------------------------------------------------
# 通用 User-Agent 池（真实 Chrome 131 / Edge 131 / Firefox 132 / Safari 17）
# ---------------------------------------------------------------------------

UA_POOL = {
    "chrome_131_win": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "chrome_131_mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "edge_131_win": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    ),
    "firefox_132_win": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) "
        "Gecko/20100101 Firefox/132.0"
    ),
    "safari_17_mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
}

# Sec-CH-UA 配套（Chrome 109+ 发送）
SEC_CH_UA = {
    "131.0.0.0": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
}


def _chrome_headers(referer: str = None) -> dict:
    """生成完整 Chrome 131 headers"""
    ua = UA_POOL["chrome_131_win"]
    h = {
        "User-Agent": ua,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "max-age=0",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-CH-UA": SEC_CH_UA["131.0.0.0"],
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if not referer else "same-origin",
        "Sec-Fetch-User": "?1",
    }
    if referer:
        h["Referer"] = referer
    return h


# ---------------------------------------------------------------------------
# 站点配置
# ---------------------------------------------------------------------------

CRAWL_CONFIGS = {
    "baidu.com": {
        "name": "百度搜索",
        "homepage": "https://www.baidu.com/",
        "search_url": "https://www.baidu.com/s",
        "search_param": "wd",
        "rate_limit": 0.5,
        "max_retries": 3,
        "blocked_retries": 2,
        "warmup_steps": [
            "GET https://www.baidu.com/  # 拿 BAIDUID / BD_HOME cookie"
        ],
        "headers": _chrome_headers(referer="https://www.baidu.com/"),
        "anti_bot_notes": (
            "百度对裸 requests 一秒识别（TLS 指纹不符）。"
            "本 skill 默认 L1 curl_cffi 已能拿到搜索结果。"
            "如返回 1.4KB 短页 → 被风控，需等 5-10 分钟或换 IP。"
        ),
        "parse_hints": {
            "result_selector": '<h3 class="t"><a href="URL">TITLE</a></h3>',
            "count_text": "约 X 个结果（百度新版已不显示，可看 <span class=\"nums_text\">）",
        },
    },

    "www.bing.com": {
        "name": "Bing 搜索",
        "homepage": "https://www.bing.com/",
        "search_url": "https://www.bing.com/search",
        "search_param": "q",
        "rate_limit": 0.2,
        "max_retries": 2,
        "blocked_retries": 1,
        "warmup_steps": [
            "GET https://www.bing.com/  # 拿 MUID / SRCHHPGUSR cookie"
        ],
        "headers": _chrome_headers(referer="https://www.bing.com/"),
        "anti_bot_notes": (
            "Bing 反爬较松，但中文长查询常被拆成单字匹配。"
            "建议搜索时用引号包公司全称，如 \"亿达信息技术有限公司\"。"
        ),
        "parse_hints": {
            "result_selector": '<h2><a href="URL">TITLE</a></h2>',
            "count_text": "约 X 条结果（或 X results）",
        },
    },

    "www.google.com": {
        "name": "Google 搜索",
        "homepage": "https://www.google.com/",
        "search_url": "https://www.google.com/search",
        "search_param": "q",
        "rate_limit": 1.0,
        "max_retries": 3,
        "blocked_retries": 2,
        "warmup_steps": [
            "GET https://www.google.com/  # 拿 CONSENT / SOCS cookie"
        ],
        "headers": _chrome_headers(referer="https://www.google.com/"),
        "anti_bot_notes": (
            "Google 严格风控，常出 'unusual traffic'。"
            "需要 L2 undetected-chromedriver 才能稳定拿到结果。"
        ),
        "parse_hints": {
            "result_selector": '<h3 class="LC20lb"><a href="URL">TITLE</a></h3>',
            "count_text": "约 X 个结果（约 X results）",
        },
    },

    "www.sogou.com": {
        "name": "搜狗搜索",
        "homepage": "https://www.sogou.com/",
        "search_url": "https://www.sogou.com/web",
        "search_param": "query",
        "rate_limit": 0.5,
        "max_retries": 2,
        "blocked_retries": 1,
        "warmup_steps": [
            "GET https://www.sogou.com/  # 拿 SUID / SUV cookie"
        ],
        "headers": _chrome_headers(referer="https://www.sogou.com/"),
        "anti_bot_notes": (
            "搜狗对脚本 UA 也算松，可用 L1。"
            "但微信文章搜索需登录态。"
        ),
        "parse_hints": {
            "result_selector": '<h3><a href="URL">TITLE</a></h3>',
        },
    },

    "s.weibo.com": {
        "name": "微博搜索（公开）",
        "homepage": "https://s.weibo.com/",
        "search_url": "https://s.weibo.com/weibo",
        "search_param": "q",
        "rate_limit": 1.5,
        "max_retries": 2,
        "blocked_retries": 2,
        "warmup_steps": [
            "GET https://s.weibo.com/  # 拿 SUB / SUBP cookie"
        ],
        "headers": _chrome_headers(referer="https://s.weibo.com/"),
        "anti_bot_notes": (
            "微博公开搜索限流严，每分钟 ≤ 10 次。"
            "建议 L2 真实 Chrome + 登录态拿更多结果。"
        ),
        "parse_hints": {
            "result_selector": '.card-wrap .from a 或 .txt',
        },
    },

    "www.zhihu.com": {
        "name": "知乎搜索",
        "homepage": "https://www.zhihu.com/",
        "search_url": "https://www.zhihu.com/search",
        "search_param": "q",
        "rate_limit": 2.0,
        "max_retries": 2,
        "blocked_retries": 2,
        "warmup_steps": [
            "GET https://www.zhihu.com/  # 拿 z_c0 cookie（需登录）"
        ],
        "headers": _chrome_headers(referer="https://www.zhihu.com/"),
        "anti_bot_notes": (
            "知乎基本要求 L2 真实 Chrome + 登录态。L1 curl_cffi 拿不到搜索结果。"
            "如确需爬取，建议用 L3 指纹浏览器配知乎账号。"
        ),
        "parse_hints": {
            "result_selector": '.SearchResult-Card 或 .ContentItem',
        },
    },

    "www.sohu.com": {
        "name": "搜狐搜索",
        "homepage": "https://www.sohu.com/",
        "search_url": "https://search.sohu.com/",
        "search_param": "keyword",
        "rate_limit": 0.5,
        "max_retries": 2,
        "blocked_retries": 1,
        "warmup_steps": [
            "GET https://www.sohu.com/  # 拿 IPLOC cookie"
        ],
        "headers": _chrome_headers(referer="https://www.sohu.com/"),
        "anti_bot_notes": (
            "搜狐搜索限流较松，可 L1。"
        ),
        "parse_hints": {
            "result_selector": '.result-title a',
        },
    },
}


# 额外两个"职业背调核心"站点配置（合规来源）

CRAWL_CONFIGS["wenshu.court.gov.cn"] = {
    "name": "中国裁判文书网",
    "homepage": "https://wenshu.court.gov.cn/",
    "search_url": "https://wenshu.court.gov.cn/website/wenshu/181010CARHS5BS3C/",
    "search_param": "keyword",
    "rate_limit": 3.0,
    "max_retries": 2,
    "blocked_retries": 3,
    "warmup_steps": [
        "GET https://wenshu.court.gov.cn/  # 需先过人机验证（必）",
        "建议 L2 undetected-chromedriver + 手动过一次滑块"
    ],
    "headers": _chrome_headers(referer="https://wenshu.court.gov.cn/"),
    "anti_bot_notes": (
        "裁判文书网**强制人机验证**，L1 curl_cffi 100% 失败。"
        "必须 L2 真实 Chrome 手动过一次滑块后才能批量。"
        "本 skill 设计为：脚本不爬，提供查询入口由用户人工使用。"
    ),
    "parse_hints": {},
}

CRAWL_CONFIGS["zxgk.court.gov.cn"] = {
    "name": "中国执行信息公开网",
    "homepage": "http://zxgk.court.gov.cn/",
    "search_url": "http://zxgk.court.gov.cn/zhzxgk/",
    "search_param": "search_keyword",
    "rate_limit": 3.0,
    "max_retries": 2,
    "blocked_retries": 3,
    "warmup_steps": [
        "GET http://zxgk.court.gov.cn/  # 需先过人机验证（必）"
    ],
    "headers": _chrome_headers(referer="http://zxgk.court.gov.cn/"),
    "anti_bot_notes": (
        "执行公开网**强制人机验证**，L1 100% 失败。"
        "建议用户手动查询，脚本仅提供入口。"
    ),
    "parse_hints": {},
}


# ---------------------------------------------------------------------------
# 查询接口
# ---------------------------------------------------------------------------

def get_config(domain: str) -> dict | None:
    """按域名获取配置（不区分带不带 www）"""
    if domain in CRAWL_CONFIGS:
        return CRAWL_CONFIGS[domain]
    # 去 www. 前缀
    if domain.startswith("www."):
        bare = domain[4:]
        if bare in CRAWL_CONFIGS:
            return CRAWL_CONFIGS[bare]
    # 加 www. 前缀
    with_www = "www." + domain
    if with_www in CRAWL_CONFIGS:
        return CRAWL_CONFIGS[with_www]
    return None


def list_domains() -> list[str]:
    """列出所有已配置的域名"""
    return sorted(CRAWL_CONFIGS.keys())


if __name__ == "__main__":
    # 简单 CLI：列出所有
    print("已配置的爬取站点：")
    for d in list_domains():
        cfg = CRAWL_CONFIGS[d]
        print(f"  {d:35s}  {cfg['name']}  (限速 {cfg['rate_limit']}s)")
