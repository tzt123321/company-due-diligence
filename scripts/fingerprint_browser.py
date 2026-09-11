#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fingerprint_browser.py — L3 指纹浏览器 API 层（可选，需付费服务）

用于 L1/L2 都过不掉的强风控场景（裁判文书网、执行公开网、工商系统等需验证码/登录的站点）。
通过指纹浏览器（BitBrowser / AdsPower）的本地 API 启动一个带独立指纹的浏览器实例，
再用 CDP 协议取回页面内容。

支持的平台（通过环境变量选择，二选一）：
    BitBrowser:
        BITBROWSER_API=http://127.0.0.1:54345
        BITBROWSER_PROFILE_ID=<profileId>
    AdsPower:
        ADSPOWER_API=http://127.0.0.1:50325
        ADSPOWER_USER_ID=<userId>

用法（库）：
    from fingerprint_browser import search_l3
    out = search_l3("示例科技有限公司 欠薪", engine="baidu")     # 返回与 browser_http.search 同构

    from fingerprint_browser import open_page_l3
    out = open_page_l3("https://aiqicha.baidu.com/detail/compinfo?pid=...")  # 详情页抓取

依赖（可选）：pip install websocket-client —— 有它才能通过 CDP 自动取回 HTML；
没有时返回页面已打开的提示和 ws 端点，由人工/其他工具接管。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _platform() -> str | None:
    if os.environ.get("BITBROWSER_API") or os.environ.get("BITBROWSER_PROFILE_ID"):
        return "bitbrowser"
    if os.environ.get("ADSPOWER_API") or os.environ.get("ADSPOWER_USER_ID"):
        return "adspower"
    return None


def start_browser(url: str) -> dict:
    """启动指纹浏览器并打开 url。返回 {ok, ws, info, errors}"""
    platform = _platform()
    if not platform:
        return {
            "ok": False, "ws": None,
            "errors": ["L3 未配置：请设置 BITBROWSER_API+BITBROWSER_PROFILE_ID 或 "
                       "ADSPOWER_API+ADSPOWER_USER_ID（见文件头注释）"],
        }
    from curl_cffi import requests as cr
    try:
        if platform == "bitbrowser":
            api = os.environ["BITBROWSER_API"].rstrip("/")
            profile_id = os.environ["BITBROWSER_PROFILE_ID"]
            r = cr.post(f"{api}/browser/start", json={"profileId": profile_id,
                                                      "open_urls": [url]},
                        impersonate="chrome131", timeout=60)
            d = r.json()
            ws = (d.get("data", {}) or {}).get("ws", {}) or {}
            return {"ok": bool(d.get("code") in (0, None) or d.get("status") == "success"),
                    "ws": ws.get("puppeteer") or ws.get("selenium") or ws.get("debuggerAddress"),
                    "info": d, "errors": []}
        else:  # adspower
            api = os.environ["ADSPOWER_API"].rstrip("/")
            user_id = os.environ["ADSPOWER_USER_ID"]
            r = cr.get(f"{api}/api/v1/browser/start",
                       params={"user_id": user_id, "open_urls": quote(url)},
                       impersonate="chrome131", timeout=60)
            d = r.json()
            ws = (d.get("data", {}) or {}).get("ws", {}) or {}
            return {"ok": d.get("code") == 0, "ws": ws.get("puppeteer"),
                    "info": d, "errors": []}
    except Exception as e:
        return {"ok": False, "ws": None, "info": None,
                "errors": [f"L3 start failed: {type(e).__name__}: {e}"]}


def _cdp_eval_html(ws_url: str, timeout: int = 20) -> str:
    """通过 CDP Runtime.evaluate 取回 document.documentElement.outerHTML。"""
    try:
        import websocket  # websocket-client
    except Exception:
        return ""
    try:
        import uuid
        ws = websocket.create_connection(ws_url, timeout=timeout)
        try:
            msg_id = str(uuid.uuid4())
            ws.send(json.dumps({
                "id": 1, "method": "Runtime.evaluate",
                "params": {"expression": "document.documentElement.outerHTML",
                           "returnByValue": True},
            }))
            deadline = time.time() + timeout
            while time.time() < deadline:
                data = json.loads(ws.recv())
                if data.get("id") == 1:
                    return (data.get("result", {}).get("result", {}).get("value") or "")
        finally:
            ws.close()
    except Exception:
        return ""
    return ""


def open_page_l3(url: str) -> dict:
    """打开单个页面（详情页/验证码站），尽力取回 HTML。"""
    start = start_browser(url)
    if not start["ok"]:
        return {"url": url, "ok": False, "text": "", "blocked": False,
                "raw_len": 0, "errors": start["errors"]}
    time.sleep(4)  # 等页面渲染
    html = ""
    if start.get("ws"):
        html = _cdp_eval_html(start["ws"])
    return {
        "url": url, "ok": True, "text": html, "blocked": False,
        "raw_len": len(html), "errors": [],
        "note": "页面已在指纹浏览器中打开；若 CDP 取回为空，请在浏览器里人工核验。",
    }


def search_l3(query: str, engine: str = "baidu", limit: int = 8) -> dict:
    """用指纹浏览器搜索，返回与 browser_http.search 同构的结果。"""
    if engine == "baidu":
        url = f"https://www.baidu.com/s?wd={quote(query)}&ie=utf-8"
        parser = "baidu"
    elif engine == "bing":
        url = f"https://www.bing.com/search?q={quote(query)}&setlang=zh-hans&mkt=zh-CN"
        parser = "bing"
    elif engine == "ddg":
        url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        parser = "ddg"
    else:
        return {"engine": engine, "query": query, "results": [], "blocked": False,
                "raw_len": 0, "elapsed": 0.0, "errors": [f"unknown engine {engine}"]}

    t0 = time.time()
    page = open_page_l3(url)
    if not page["ok"]:
        return {"engine": f"{engine}(L3)", "query": query, "results": [], "blocked": False,
                "raw_len": 0, "elapsed": round(time.time() - t0, 2), "errors": page["errors"]}
    # 复用 L1 的解析器
    from browser_http import parse_baidu, parse_bing, parse_ddg
    text = page.get("text") or ""
    if parser == "baidu":
        results = parse_baidu(text)
    elif parser == "bing":
        results = parse_bing(text)
    else:
        results = parse_ddg(text)
    blocked = any(m in text for m in ("安全验证", "wappass", "请输入验证码"))
    return {
        "engine": f"{engine}(L3)", "query": query, "results": results[:limit],
        "blocked": blocked, "raw_len": len(text),
        "elapsed": round(time.time() - t0, 2), "errors": [],
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L3 指纹浏览器 API 层")
    parser.add_argument("query", nargs="?", default="示例科技有限公司 欠薪")
    parser.add_argument("--engine", default="baidu", choices=["baidu", "bing", "ddg"])
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--page", default=None, help="改为直接打开该页面")
    args = parser.parse_args()
    if args.page:
        out = open_page_l3(args.page)
    else:
        out = search_l3(args.query, engine=args.engine, limit=args.limit)
    print(json.dumps(out, ensure_ascii=False, indent=2))
