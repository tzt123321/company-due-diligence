#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
real_browser.py — L2 真实 Chrome 浏览器层（可选）

当 L1（curl_cffi 指纹）仍然 0 命中 / 被验证码拦截时启用：
用 undetected-chromedriver 驱动本机真实 Chrome，行为与真人一致，
能过掉大部分 L1 过不去的反爬（知乎/小红书/脉脉等强风控站）。

依赖：pip install undetected-chromedriver（本机已装 3.5.5）+ 本机安装 Chrome

用法（库）：
    from real_browser import search_with_real_browser
    out = search_with_real_browser("示例科技有限公司 欠薪", engine="baidu")
    print(out["results"][0]["title"])

用法（CLI）：
    python real_browser.py "示例科技有限公司 欠薪" --engine baidu --limit 8

返回结构与 browser_http.search 一致，可直接替换。
未安装/启动失败时不会抛异常，返回 errors 并给出安装指引。
"""
from __future__ import annotations

import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DRIVER_ERRORS: list[str] = []


def is_available() -> bool:
    try:
        import undetected_chromedriver  # noqa: F401
        return True
    except Exception:
        return False


def _get_driver(headless: bool = True, timeout: int = 30):
    import undetected_chromedriver as uc
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,900")
    options.add_argument("--lang=zh-CN")
    return uc.Chrome(options=options, version_main=None)


def search_with_real_browser(query: str, engine: str = "baidu", limit: int = 8,
                             timeout: int = 45) -> dict:
    """用真实 Chrome 搜索，返回与 browser_http.search 同构的结果。"""
    if not is_available():
        return {
            "engine": engine, "query": query, "results": [], "blocked": False,
            "raw_len": 0, "elapsed": 0.0,
            "errors": ["undetected-chromedriver 未安装：pip install undetected-chromedriver"],
        }
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By

    t0 = time.time()
    driver = None
    try:
        driver = _get_driver(headless=True, timeout=timeout)
        driver.set_page_load_timeout(timeout)
        if engine == "baidu":
            driver.get(f"https://www.baidu.com/s?wd={query}&ie=utf-8")
            time.sleep(2.5)
            nodes = driver.find_elements(By.CSS_SELECTOR, "h3 a")
        elif engine == "bing":
            driver.get(f"https://www.bing.com/search?q={query}&setlang=zh-hans&mkt=zh-CN")
            time.sleep(2.5)
            nodes = driver.find_elements(By.CSS_SELECTOR, "li.b_algo h2 a")
        elif engine == "ddg":
            driver.get(f"https://html.duckduckgo.com/html/?q={query}")
            time.sleep(2.5)
            nodes = driver.find_elements(By.CSS_SELECTOR, "a.result__a")
        else:
            return {"engine": engine, "query": query, "results": [], "blocked": False,
                    "raw_len": 0, "elapsed": 0.0, "errors": [f"unknown engine {engine}"]}

        results = []
        for i, node in enumerate(nodes[:limit]):
            try:
                title = node.text.strip() or node.get_attribute("aria-label") or ""
                url = node.get_attribute("href") or ""
                if not title or not url.startswith("http"):
                    continue
                results.append({"rank": len(results) + 1, "title": title, "url": url, "snippet": ""})
            except Exception:
                continue
        page_text = ""
        try:
            page_text = driver.page_source or ""
        except Exception:
            pass
        blocked = any(m in page_text for m in ("安全验证", "wappass", "请输入验证码"))
        return {
            "engine": f"{engine}(real-browser)", "query": query, "results": results,
            "blocked": blocked, "raw_len": len(page_text),
            "elapsed": round(time.time() - t0, 2), "errors": [],
        }
    except Exception as e:
        return {
            "engine": engine, "query": query, "results": [], "blocked": False,
            "raw_len": 0, "elapsed": round(time.time() - t0, 2),
            "errors": [f"real browser failed: {type(e).__name__}: {e}；"
                       "请确认本机已安装 Chrome，且网络可直连目标站点"],
        }
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def fetch_page_with_real_browser(url: str, timeout: int = 45) -> dict:
    """真实浏览器打开单个页面并返回 HTML（用于验证码站点的详情页核验）。"""
    if not is_available():
        return {"url": url, "status": 0, "text": "", "blocked": False, "raw_len": 0,
                "errors": ["undetected-chromedriver 未安装"]}
    import undetected_chromedriver as uc
    t0 = time.time()
    driver = None
    try:
        driver = _get_driver(headless=False, timeout=timeout)  # 非 headless，可人工过验证码
        driver.get(url)
        time.sleep(3)
        html = driver.page_source or ""
        return {"url": url, "status": 200, "text": html, "blocked": False,
                "raw_len": len(html), "elapsed": round(time.time() - t0, 2), "errors": []}
    except Exception as e:
        return {"url": url, "status": 0, "text": "", "blocked": False, "raw_len": 0,
                "elapsed": round(time.time() - t0, 2), "errors": [f"{type(e).__name__}: {e}"]}
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L2 真实浏览器抓取层")
    parser.add_argument("query", nargs="?", default="示例科技有限公司 欠薪")
    parser.add_argument("--engine", default="baidu", choices=["baidu", "bing", "ddg"])
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--page", default=None, help="改为直接打开该页面抓 HTML")
    args = parser.parse_args()
    if args.page:
        out = fetch_page_with_real_browser(args.page)
    else:
        out = search_with_real_browser(args.query, engine=args.engine, limit=args.limit)
    print(json.dumps(out, ensure_ascii=False, indent=2))
