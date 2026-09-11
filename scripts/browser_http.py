#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
browser_http.py — L1 浏览器指纹抓取层（核心）

目标：用 curl_cffi 模拟真实 Chrome 131 的 TLS/HTTP2 指纹去查询搜索引擎，
行为上接近 dsh-browser 里真实浏览器做的查询，从而绕开裸 requests 的"秒识别机器人"问题。

实战结论（某公司 case）：
    裸 requests  ：百度返回 305KB / 0 标题（被风控）
    L1 curl_cffi ：百度返回 1.07MB / 9 个真实标题（含 aiqicha 企业信息面板）

本模块只做"取回 + 解析"：
    - search(engine, query) -> dict{engine, query, results[], blocked, raw_len, errors}
    - 引擎：baidu（CN 主引擎）/ bing（备选）/ ddg（可选，部分网络超时）
    - 内置：按 host 复用 Session、warmup、GBK 重定向解析、验证码/风控标记检测、
            0.3s 限速（调用方控制）、2 次重试
依赖：pip install curl_cffi beautifulsoup4
"""
from __future__ import annotations

import html as html_mod
import json
import re
import sys
import time
from urllib.parse import quote, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from curl_cffi import requests as cr

try:
    from bs4 import BeautifulSoup  # 可选，装了更稳；没装自动退回正则
    HAS_BS4 = True
except Exception:  # pragma: no cover
    HAS_BS4 = False

# ---------------------------------------------------------------- 常量
DEFAULT_IMPERSONATE = "chrome131"
DEFAULT_TIMEOUT = 20
DEFAULT_RATE_LIMIT = 0.3        # 每次搜索之间的间隔（秒）
MAX_RETRIES = 2

# 风控/验证码标记：命中任意一条 => blocked=True
BLOCKED_MARKERS = [
    "安全验证", "请输入验证码", "验证码", "wappass", "captcha",
    "访问过于频繁", "异常请求", "网络不给力", "verify",
]

# 搜索引擎地址
SEARCH_URLS = {
    "baidu": "https://www.baidu.com/s",
    "bing": "https://www.bing.com/search",
    "ddg": "https://html.duckduckgo.com/html/",
}

# 模块级 Session 缓存：按 host 复用（修复：每次 new 实例 warmup 失效的问题）
_browser_http_cache: dict[str, cr.Session] = {}


# ---------------------------------------------------------------- 会话管理
def get_session(host: str = "www.baidu.com") -> cr.Session:
    s = _browser_http_cache.get(host)
    if s is None:
        s = cr.Session(impersonate=DEFAULT_IMPERSONATE, timeout=DEFAULT_TIMEOUT)
        _browser_http_cache[host] = s
    return s


def warmup(host: str = "https://www.baidu.com/") -> None:
    """先访问一次主页，让会话带上完整 cookie/指纹上下文，降低首次搜索被拒概率。"""
    try:
        get_session(urlparse(host).netloc).get(host, timeout=DEFAULT_TIMEOUT)
    except Exception:
        pass  # warmup 失败不致命，后续搜索仍会尝试


# ---------------------------------------------------------------- 工具函数
def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_url(url: str) -> str:
    return html_mod.unescape(url).replace("&amp;", "&").strip()


def resolve_baidu_link(url: str, depth: int = 0) -> str:
    """把 www.baidu.com/link?url=... / www.baidu.com/baidu.php?url=... 跳转链接解析成真实地址。

    百度 302 的 Location 头是 GBK 编码的字节，HTTP 解析器按 latin-1 解码后变乱码，
    所以用 allow_redirects=False 取原始头，再 latin-1 -> gbk 还原。
    """
    if ("baidu.com/link?" not in url and "baidu.com/baidu.php" not in url) or depth > 2:
        return url
    try:
        s = get_session("www.baidu.com")
        r = s.get(url, allow_redirects=False, headers={"Referer": "https://www.baidu.com/"})
        loc = r.headers.get("Location")
        if not loc:
            return url
        if "baidu.com/link?" in loc or "baidu.com/baidu.php" in loc:
            return resolve_baidu_link(loc, depth + 1)
        # GBK 还原
        fixed = loc.encode("latin-1", errors="replace").decode("gbk", errors="replace")
        if fixed.startswith("http"):
            return fixed
        return loc
    except Exception:
        return url


def _is_blocked(text: str) -> bool:
    """判定页面是否被风控：
    - 页面极小（<30KB，正常百度结果页 ~1MB）→ 风控短页
    - 页面前 8KB 出现验证码/安全标记（大页面深处出现"验证码"字样是正常内容，不算）"""
    if len(text) < 30_000:
        return True
    head = text[:8000]
    return any(m in head for m in ("wappass", "安全验证", "请输入验证码"))


def _rate_limit(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(seconds)


# ---------------------------------------------------------------- 各引擎解析
def parse_baidu(html_text: str) -> list[dict]:
    """百度搜索结果解析。

    1) 常规结果：<h3 class="c-title"><a href=...>标题</a></h3>，标题优先取 aria-label="标题:..."（更准）
    2) 爱企查企业面板（vmp-zxenterprise-*）：抽出 法定代表人/注册资本/成立时间/状态标签，挂在第一条结果的
       enterprise_basic 字段 —— 这是 basic 命令最值钱的结构化信息
    3) 摘要：取本 h3 到下一个 h3 之间的 c-abstract / c-span-last / content-right 文本
    """
    results: list[dict] = []
    if HAS_BS4:
        soup = BeautifulSoup(html_text, "lxml")
        h3s = soup.find_all("h3")
        for i, h3 in enumerate(h3s):
            a = h3.find("a")
            if not a or not a.get("href"):
                continue
            aria = a.get("aria-label") or ""
            m = re.match(r"标题[:：](.*)", aria)
            title = _strip_tags(str(a))
            if m:
                title = m.group(1).strip()
            url = _norm_url(a["href"])
            if url.startswith("javascript") or url.startswith("#"):
                continue
            # 摘要窗口
            start = h3
            end = h3s[i + 1] if i + 1 < len(h3s) else soup
            window = ""
            try:
                seg = start.find_next_sibling()
                while seg is not None and seg is not end:
                    window += str(seg)
                    seg = seg.find_next_sibling()
                    if len(window) > 6000:
                        break
            except Exception:
                window = ""
            snippet = ""
            for cls in ("c-abstract", "c-span-last", "content-right", "cos-color-text"):
                fm = re.search(rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)</(?:div|span|p)>', window, re.S)
                if fm:
                    snippet = _strip_tags(fm.group(1))
                    if snippet:
                        break
            if not snippet:
                # 退而求其次：窗口内全部文本
                mtext = re.findall(r">([^<>]{12,})<", window)
                snippet = _strip_tags(" ".join(mtext))[:200]
            results.append({"rank": len(results) + 1, "title": title, "url": url, "snippet": snippet})
        # 企业面板
        panel = soup.find("div", class_=re.compile(r"vmp-zxenterprise-basic"))
        if panel:
            kv: dict[str, str] = {}
            for p in panel.find_all("p"):
                txt = _strip_tags(str(p))
                if "：" in txt:
                    k, v = txt.split("：", 1)
                    kv[k.strip()] = v.strip()
            tags = [t.get_text(" ", strip=True) for t in soup.select("div.tag-lists-wrap span, div[class*=tag-lists] span")]
            if results:
                results[0]["enterprise_basic"] = {"fields": kv, "tags": tags}
    else:  # 正则兜底
        hits = re.findall(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.S)
        for u, ti in hits:
            url = _norm_url(u)
            if url.startswith("javascript"):
                continue
            results.append({"rank": len(results) + 1, "title": _strip_tags(ti), "url": url, "snippet": ""})
    return results


def parse_bing(html_text: str) -> list[dict]:
    results: list[dict] = []
    if HAS_BS4:
        soup = BeautifulSoup(html_text, "lxml")
        for li in soup.select("li.b_algo"):
            a = li.find("h2")
            a = a.find("a") if a else None
            if not a or not a.get("href"):
                continue
            url = _norm_url(a["href"])
            if not url.startswith("http"):
                continue
            title = _strip_tags(str(a))
            p = li.find("p")
            snippet = _strip_tags(str(p)) if p else ""
            results.append({"rank": len(results) + 1, "title": title, "url": url, "snippet": snippet})
    else:  # 正则兜底
        hits = re.findall(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', html_text, re.S)
        for u, ti in hits:
            url = _norm_url(u)
            if not url.startswith("http"):
                continue
            results.append({"rank": len(results) + 1, "title": _strip_tags(ti), "url": url, "snippet": ""})
    return results


def parse_ddg(html_text: str) -> list[dict]:
    results: list[dict] = []
    if HAS_BS4:
        soup = BeautifulSoup(html_text, "lxml")
        for res in soup.select("div.result"):
            a = res.select_one("a.result__a")
            if not a or not a.get("href"):
                continue
            url = _norm_url(a["href"])
            sn = res.select_one(".result__snippet")
            results.append({
                "rank": len(results) + 1,
                "title": _strip_tags(str(a)),
                "url": url,
                "snippet": _strip_tags(str(sn)) if sn else "",
            })
    return results


# ---------------------------------------------------------------- 主入口
def search(engine: str, query: str, limit: int = 10, timeout: int = DEFAULT_TIMEOUT,
           rate_limit: float = DEFAULT_RATE_LIMIT, retries: int = MAX_RETRIES) -> dict:
    """查询一个引擎，返回结构化结果。任何异常都不会抛出，而是进入 errors 列表。

    返回结构（供 data_fetcher / LLM 消费）：
    {
      "engine": "baidu", "query": "...", "results": [{rank,title,url,snippet}...],
      "blocked": false,          # 命中验证码/风控标记
      "raw_len": 123456,         # 原始页大小，<30KB 基本可判定被风控
      "elapsed": 1.2,
      "errors": []
    }
    """
    engine = engine.lower()
    if engine not in SEARCH_URLS:
        return {"engine": engine, "query": query, "results": [], "blocked": False,
                "raw_len": 0, "elapsed": 0.0, "errors": [f"unknown engine: {engine}"]}

    _rate_limit(rate_limit)
    url = SEARCH_URLS[engine]
    headers = {}
    params: dict = {}
    if engine == "baidu":
        params = {"wd": query, "ie": "utf-8", "rn": str(limit)}
        headers = {"Referer": "https://www.baidu.com/"}
        host = "www.baidu.com"
    elif engine == "bing":
        params = {"q": query, "setlang": "zh-hans", "mkt": "zh-CN", "count": str(limit)}
        host = "www.bing.com"
    else:  # ddg
        params = {"q": query}
        host = "html.duckduckgo.com"

    last_err = ""
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            s = get_session(host)
            r = s.get(url, params=params, headers=headers, timeout=timeout)
            text = r.text
            blocked = _is_blocked(text) or len(text) < 30_000
            if engine == "baidu":
                results = parse_baidu(text)
                for res in results:  # 解析跳转链接（只有 baidu 有）
                    if "baidu.com/link?" in res["url"]:
                        res["url"] = resolve_baidu_link(res["url"])
            elif engine == "bing":
                results = parse_bing(text)
            else:
                results = parse_ddg(text)
            results = results[:limit]
            return {
                "engine": engine, "query": query, "results": results,
                "blocked": blocked, "raw_len": len(text),
                "elapsed": round(time.time() - t0, 2), "errors": [],
            }
        except Exception as e:  # 网络错误等
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(1.0 * (attempt + 1))
    return {
        "engine": engine, "query": query, "results": [], "blocked": False,
        "raw_len": 0, "elapsed": 0.0, "errors": [last_err],
    }


def search_fallback(query: str, engines: list[str] | None = None, limit: int = 10,
                    rate_limit: float = DEFAULT_RATE_LIMIT) -> dict:
    """按优先级依次查询多个引擎，返回第一个非空（非 blocked）的结果；全部失败返回汇总。

    engines 默认 ["baidu", "bing"]；CN 公司名百度质量最好，境外公司建议 ["bing", "baidu", "ddg"]。
    """
    engines = engines or ["baidu", "bing"]
    combined: list[dict] = []
    errors: list[str] = []
    for eng in engines:
        r = search(eng, query, limit=limit, rate_limit=rate_limit)
        if r["errors"]:
            errors.extend(r["errors"])
        if r["results"] and not r["blocked"]:
            combined.extend(r["results"])
            return {
                "engine": eng, "query": query, "results": combined,
                "blocked": False, "raw_len": sum(x["raw_len"] for x in [r]),
                "elapsed": r["elapsed"], "errors": errors, "engines_tried": engines,
            }
        if r["blocked"] and r["results"]:
            combined.extend(r["results"])  # 风控但有结果：保留并标记
            return {
                "engine": eng, "query": query, "results": combined,
                "blocked": True, "raw_len": r["raw_len"], "elapsed": r["elapsed"],
                "errors": errors, "engines_tried": engines,
            }
        errors.append(f"{eng}: no results")
    return {
        "engine": "+".join(engines), "query": query, "results": combined,
        "blocked": False, "raw_len": 0, "elapsed": 0.0, "errors": errors,
        "engines_tried": engines,
    }


def fetch_page(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """抓取单个页面（用于打开 aiqicha/百科等详情页）。同样走指纹会话。"""
    try:
        host = urlparse(url).netloc or "www.baidu.com"
        r = get_session(host).get(url, timeout=timeout,
                                  headers={"Referer": "https://www.baidu.com/"})
        return {"url": url, "status": r.status_code, "text": r.text,
                "blocked": _is_blocked(r.text), "raw_len": len(r.text)}
    except Exception as e:
        return {"url": url, "status": 0, "text": "", "blocked": False,
                "raw_len": 0, "errors": [f"{type(e).__name__}: {e}"]}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L1 浏览器指纹抓取层自测")
    parser.add_argument("query", nargs="?", default="示例科技有限公司 欠薪")
    parser.add_argument("--engine", default="baidu", choices=list(SEARCH_URLS))
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    warmup()
    out = search(args.engine, args.query, limit=args.limit)
    print(json.dumps(out, ensure_ascii=False, indent=2))
