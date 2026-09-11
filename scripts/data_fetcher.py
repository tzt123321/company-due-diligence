#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_fetcher.py — 公司求职背调主抓取器（CLI + 库双用法）

定位：把"大模型每次从头联网搜索"变成"结构化数据管道"。脚本能拿到的直接结构化返回，
拿不到的标记 manual_required 并给出具体入口 —— 决策权始终在用户/大模型。

子命令：
    resolve        公司名消歧（品牌名 → 工商全称候选）
    basic          基础工商信息（爱企查面板：法定代表人/注册资本/成立时间/状态）
    keyword-sweep  风险关键词扫描（欠薪/仲裁/被执行/经营异常/社保...）
    news           近期新闻扫描
    reviews        员工评价入口收集（只看链接，不抓原文，合规）
    all            全流程：resolve → basic → sweep → news → reviews → 评分 → 报告

输出：JSON（机器可读，LLM 消费）+ Markdown（报告骨架）+ HTML（红绿灯仪表盘）

典型用法：
    python data_fetcher.py all "示例科技有限公司" --keywords 欠薪,劳动仲裁
    python data_fetcher.py keyword-sweep "示例科技有限公司" --json
    python data_fetcher.py all "OpenAI" --global-mode --engines bing,baidu

技术要点（来自实战复盘）：
    - L1 curl_cffi 指纹抓取（browser_http），裸 requests 会被百度秒识别
    - --clear-cache 是顶层参数，不依赖子命令
    - 公共参数在子命令和主 parser 双重声明（argparse parents 兼容问题）
    - 每个关键词 0.3s 限速，多引擎 fallback，任何单点失败都不中断
    - 未验证 ≠ 无风险：搜不到/被验证码挡住的，一律标 manual_required
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from cache import Cache
from browser_http import search, search_fallback, warmup
from fuzzy_resolve import resolve as fuzzy_resolve

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_HTML = SKILL_ROOT / "assets" / "report-template.html"

# ---------------------------------------------------------------- 风险信号定义
# keyword → (信号类别, 严重度, 强标记)
SIGNAL_DEFS: dict[str, tuple[str, str, list[str]]] = {
    "欠薪":        ("欠薪/劳动违法", "severe", ["欠薪", "拖欠工资", "欠薪黑名单", "劳动保障违法"]),
    "拖欠工资":    ("欠薪/劳动违法", "severe", ["拖欠工资", "欠薪", "工资被拖欠"]),
    "劳动仲裁":    ("劳动仲裁",       "medium", ["劳动仲裁", "劳动争议", "仲裁裁决", "仲裁委员会公告"]),
    "劳动争议":    ("劳动仲裁",       "medium", ["劳动争议", "劳动仲裁"]),
    "被执行":      ("被执行/失信",    "severe", ["被执行人", "失信被执行人", "限制消费", "执行标的"]),
    "失信":        ("被执行/失信",    "severe", ["失信", "列入失信", "限制高消费"]),
    "经营异常":    ("经营异常",       "medium", ["列入经营异常", "经营异常名录", "经营异常"]),
    "社保欠缴":    ("社保问题",       "medium", ["社保欠缴", "欠缴社保", "未缴社保", "社保被追缴"]),
    "社保":        ("社保问题",       "medium", ["社保"]),
    "裁员":        ("经营恶化",       "low",    ["裁员", "大规模裁员", "优化人员"]),
    "降薪":        ("经营恶化",       "low",    ["降薪", "停薪"]),
    "诉讼":        ("诉讼风险",       "medium", ["诉讼", "判决书", "开庭公告", "起诉"]),
    "破产清算":    ("经营恶化",       "severe", ["破产", "清算", "注销公告", "停业"]),
    "跑路":        ("经营恶化",       "severe", ["跑路", "失联", "卷款"]),
    "诈骗":        ("经营恶化",       "severe", ["诈骗", "骗局", "传销"]),
    "法人变更":    ("治理异常",       "low",    ["法定代表人变更", "法人变更", "股权变更"]),
}

DEFAULT_SWEEP_KEYWORDS = [
    "欠薪", "拖欠工资", "劳动仲裁", "劳动争议", "被执行", "失信", "经营异常",
    "社保欠缴", "社保", "裁员", "降薪", "诉讼", "破产清算", "跑路", "诈骗", "法人变更",
]

# 红线判定（与 references/red-line-rules.md 保持一致）
RED_LINES = [
    {"id": 1, "name": "当前被执行人 / 失信被执行人", "signals": ["被执行/失信"],
     "strong": ["被执行人", "失信被执行人", "限制消费", "执行标的"]},
    {"id": 2, "name": "经营异常名录 / 吊销 / 注销", "signals": ["经营异常"],
     "strong": ["列入经营异常", "经营异常名录", "吊销", "注销公告", "停业"]},
    {"id": 3, "name": "重大劳动保障违法 / 欠薪黑名单", "signals": ["欠薪/劳动违法"],
     "strong": ["欠薪黑名单", "重大劳动保障违法", "劳动保障违法", "拖欠工资"]},
    {"id": 4, "name": "近 1 年劳动仲裁频繁（≥5 起）", "signals": ["劳动仲裁"],
     "strong": ["劳动仲裁", "劳动争议", "仲裁裁决"]},
    {"id": 5, "name": "法定代表人/股东近 1 年频繁变更", "signals": ["治理异常"],
     "strong": ["法定代表人变更", "法人变更", "股权变更"]},
    {"id": 6, "name": "近 1 年法律诉讼频繁（≥10 起）", "signals": ["诉讼风险"],
     "strong": ["判决书", "开庭公告", "被告"]},
    {"id": 7, "name": "社保欠缴被公示 / 大规模社保投诉", "signals": ["社保问题"],
     "strong": ["社保欠缴", "欠缴社保", "未缴社保", "社保被追缴"]},
]

NEWS_DOMAINS = ["sina", "sohu", "163.com", "qq.com", "thepaper", "36kr", "ithome",
                "jiemian", "caixin", "cls.cn", "yicai", "eastmoney", "gelonghui",
                "ifeng", "chinanews", "xinhuanet", "people.com"]

REVIEW_PLATFORMS = {
    "kanyun": "看准网", "maimai": "脉脉", "zhipin": "BOSS直聘", "zhihu": "知乎",
    "xiaohongshu": "小红书", "jobui": "职友集", "lagou": "拉勾", "51job": "前程无忧",
    "liepin": "猎聘", "tianyancha": "天眼查", "qcc": "企查查",
}


# ================================================================ 各子命令
def cmd_resolve(name: str, opts) -> dict:
    return fuzzy_resolve(name, is_global=opts.global_mode)


def cmd_basic(name: str, opts) -> dict:
    r = fuzzy_resolve(name, is_global=opts.global_mode)
    out = {"query": name, "resolve": r}
    target = (r.get("recommended") or {}).get("name") or name

    cache = opts._cache
    cache_key = f"basic:{target}"
    if not opts.no_cache:
        cached = cache.get_json(cache_key, "basic")
        if cached:
            cached["_cache_hit"] = True
            return cached

    panel: dict | None = None
    sources: list[dict] = []
    manual: list[dict] = []
    engines = opts.engines or (["bing", "baidu"] if (r.get("is_global")) else ["baidu", "bing"])
    for eng in engines:
        s = search(eng, target, limit=8, rate_limit=opts.rate_limit)
        for res in s["results"]:
            eb = res.pop("enterprise_basic", None)
            sources.append({"engine": eng, "title": res["title"], "url": res["url"],
                            "snippet": res.get("snippet", "")})
            if eb:
                panel = eb
            url = res["url"]
            if "aiqicha.baidu.com" in url:
                manual.append({
                    "item": "爱企查企业详情（验证码拦截，需人工/浏览器打开核对）",
                    "url": url,
                    "what_to_check": "经营状态 / 被执行人 / 司法案件 / 行政处罚 / 变更记录",
                })
        if s["blocked"]:
            manual.append({"item": f"{eng} 被风控（验证码）", "url": "",
                           "what_to_check": "稍后重试或换 L2/L3 浏览器"})

    out.update({
        "resolved_name": target,
        "confidence": r.get("confidence"),
        "candidates": r.get("candidates", []),
        "enterprise_basic": panel or {},
        "sources": sources[:12],
        "manual_required": manual,
        "official_checklist": [
            {"item": "国家企业信用信息公示系统（gsxt）", "url": "https://www.gsxt.gov.cn/index.html",
             "what_to_check": "经营异常名录 / 严重违法失信 / 行政处罚 / 年报"},
            {"item": "中国执行信息公开网", "url": "http://zxgk.court.gov.cn/",
             "what_to_check": "被执行人 / 失信被执行人 / 限制消费"},
            {"item": "信用中国", "url": "https://www.creditchina.gov.cn/",
             "what_to_check": "行政处罚 / 失信惩戒 / 欠税公告"},
        ],
    })
    if not opts.no_cache:
        cache.set(cache_key, "basic", out)
    return out


def _hit_score(title: str, snippet: str, strong: list[str]) -> int:
    text = f"{title} {snippet}"
    return sum(1 for m in strong if m in text)


def _name_core(name: str) -> str:
    """从公司名提取可归属核心词（去后缀/地区括号），用于防张冠李戴判定。
    例："某科技有限公司" → "某科技"；"某科技有限公司（某市）" → "某科技"。
    实战教训：搜索结果可能同时含公司名与信号词但毫不相关（"诈骗"罗生门新闻列表），
    只有公司名出现在标题/摘要里，信号才能归属到该公司。"""
    s = name.strip()
    for suf in ("股份有限公司", "有限责任公司", "有限公司", "公司", "集团"):
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
            break
    s = re.sub(r"[（(][^（）()]*[）)]", "", s)
    return s.strip()


def cmd_keyword_sweep(name: str, opts) -> dict:
    keywords = [k.strip() for k in (opts.keywords or "").split(",") if k.strip()] or DEFAULT_SWEEP_KEYWORDS
    core = _name_core(name)
    cache = opts._cache
    signals: list[dict] = []
    for kw in keywords:
        cat, sev, strong = SIGNAL_DEFS.get(kw, (kw, "low", [kw]))
        q = f"{name} {kw}"
        cache_key = f"sweep:{q}"
        data = None
        if not opts.no_cache:
            data = cache.get_json(cache_key, "risk")
        if data is None:
            data = search_fallback(q, engines=opts.engines, limit=8, rate_limit=opts.rate_limit)
            if not opts.no_cache:
                cache.set(cache_key, "risk", data)
        hits = []
        for res in data.get("results", []):
            title = res["title"]
            snippet = res.get("snippet", "")
            attributable = core in f"{title} {snippet}" if len(core) >= 2 else True
            hits.append({
                "title": title, "url": res["url"], "snippet": snippet,
                "hit_score": _hit_score(title, snippet, strong),
                "attributable": attributable,
            })
        signals.append({
            "keyword": kw, "category": cat, "severity": sev,
            "query": q, "blocked": data.get("blocked", False),
            "engine": data.get("engine", ""),
            "errors": data.get("errors", []),
            "hits": hits,
            "n_hits": len(hits),
            "strong_hits": [h for h in hits if h["hit_score"] > 0 and h["attributable"]],
            "unattributed_hits": [h for h in hits if h["hit_score"] > 0 and not h["attributable"]],
        })
    return {"company": name, "signals": signals}


def cmd_news(name: str, opts) -> dict:
    cache = opts._cache
    out: dict = {"company": name, "items": [], "note": ""}
    queries = [f"{name} 新闻", f"{name} 通报", f"{name} 公告"]
    seen: set[str] = set()
    for q in queries:
        cache_key = f"news:{q}"
        data = None
        if not opts.no_cache:
            data = cache.get_json(cache_key, "news")
        if data is None:
            data = search_fallback(q, engines=opts.engines, limit=8, rate_limit=opts.rate_limit)
            if not opts.no_cache:
                cache.set(cache_key, "news", data)
        for res in data.get("results", []):
            url = res["url"]
            if url in seen:
                continue
            seen.add(url)
            is_news = any(d in url for d in NEWS_DOMAINS) or "新闻" in res["title"] or \
                      "通报" in res["title"] or "公告" in res["title"]
            out["items"].append({
                "title": res["title"], "url": url, "snippet": res.get("snippet", ""),
                "is_news_domain": is_news,
            })
    out["note"] = "新闻列表仅做线索提示；重要事件请人工打开原文核实日期与主体（同名公司需防张冠李戴）。"
    return out


def cmd_reviews(name: str, opts) -> dict:
    cache = opts._cache
    queries = [f"{name} 怎么样", f"{name} 评价 工资", f"{name} 加班", f"{name} 面试"]
    entries: list[dict] = []
    seen: set[str] = set()
    for q in queries:
        cache_key = f"review:{q}"
        data = None
        if not opts.no_cache:
            data = cache.get_json(cache_key, "review")
        if data is None:
            data = search_fallback(q, engines=opts.engines, limit=8, rate_limit=opts.rate_limit)
            if not opts.no_cache:
                cache.set(cache_key, "review", data)
        for res in data.get("results", []):
            url = res["url"]
            if url in seen:
                continue
            seen.add(url)
            platform = "其他"
            for key, pname in REVIEW_PLATFORMS.items():
                if key in url:
                    platform = pname
                    break
            entries.append({
                "platform": platform, "title": res["title"], "url": url,
                "snippet": res.get("snippet", ""),
            })
    return {
        "company": name,
        "entries": entries,
        "compliance_note": "按合规要求，本脚本只收集员工评价入口链接，不自动抓取评价原文；"
                           "请由用户自行打开链接阅读，大模型只做入口汇总。",
    }


# ================================================================ 评分与红线
def evaluate_red_lines(sweep: dict) -> list[dict]:
    by_cat: dict[str, list[dict]] = {}
    for s in sweep.get("signals", []):
        by_cat.setdefault(s["category"], []).append(s)

    out = []
    for rl in RED_LINES:
        hits = []
        for cat in rl["signals"]:
            for s in by_cat.get(cat, []):
                for h in s.get("strong_hits", []):
                    hits.append(h)
        if hits:
            status = "hit"
        else:
            # 该类别所有关键词都搜过且无强命中 → 搜索层面干净
            searched = [s for cat in rl["signals"] for s in by_cat.get(cat, [])]
            if searched and all(not s.get("blocked") and not s.get("errors") for s in searched):
                status = "clean"
            else:
                status = "unverified"
        out.append({
            "id": rl["id"], "name": rl["name"],
            "status": status,  # hit | clean(搜索层面) | unverified
            "evidence": [{"title": h["title"], "url": h["url"]} for h in hits[:5]],
        })
    return out


def score_report(sweep: dict, red_lines: list[dict]) -> dict:
    points = 100
    reasons: list[str] = []
    if any(rl["status"] == "hit" for rl in red_lines):
        return {
            "points": 15, "light": "red",
            "summary": "命中强红线 → 一票否决：不建议投递/面试（除非能推翻证据链）",
            "reasons": [f"红线 {rl['id']} {rl['name']} 命中" for rl in red_lines if rl["status"] == "hit"],
        }
    penalty = {"severe": 40, "medium": 25, "low": 12}
    for s in sweep.get("signals", []):
        if s.get("strong_hits"):
            points -= penalty.get(s["severity"], 15)
            reasons.append(f"{s['keyword']}: {len(s['strong_hits'])} 条强信号")
    if points >= 70:
        light, summary = "green", "未见明显高危信号，可正常评估"
    elif points >= 40:
        light, summary = "yellow", "存在若干风险信号，投递前务必逐条核实"
    else:
        light, summary = "red", "风险信号密集，强烈建议谨慎"
    return {"points": max(points, 5), "light": light, "summary": summary, "reasons": reasons[:12]}


PITFALL_TEMPLATES = {
    "被执行/失信": "公司/关联主体有被执行或失信记录，入职后可能面临工资执行难、账户冻结风险",
    "欠薪/劳动违法": "存在欠薪/劳动违法记录（黑名单/处罚公告），工资准时性风险高",
    "劳动仲裁": "劳动争议/仲裁记录多，用工合规性存疑，离职时可能被刁难",
    "经营异常": "经营异常名录在列，可能影响社保缴纳与公积金办理",
    "社保问题": "社保欠缴/投诉记录，入职后社保可能无法按时足额缴纳",
    "经营恶化": "裁员/降薪/破产清算相关消息，岗位稳定性风险高",
    "治理异常": "法人/股权频繁变更，公司治理不稳定，可能换壳经营",
    "诉讼风险": "诉讼频繁且多为被告，经营现金流与商誉承压",
}

INTERVIEW_QUESTIONS = [
    "合同与哪家公司主体签署？社保公积金缴纳主体与比例？（防劳务派遣/外包/主体不一致）",
    "试用期多长、薪资结构（底薪/绩效占比）？绩效是否有书面考核标准？",
    "近一年公司是否有裁员/降薪/欠薪情况？离职率如何？",
    "发薪日是哪天？是否有过延迟？",
    "岗位编制归属：正编/外包/项目制？合同期限与续签条件？",
    "加班频率与加班费/调休政策？",
    "公司近一年诉讼/仲裁情况如何？经营现金流状况？",
    "直属上级与团队规模、汇报关系？",
]


def build_pitfalls(sweep: dict) -> list[dict]:
    out: list[dict] = []
    for s in sweep.get("signals", []):
        if s.get("strong_hits") and s["category"] in PITFALL_TEMPLATES:
            out.append({
                "category": s["category"],
                "keyword": s["keyword"],
                "risk": PITFALL_TEMPLATES[s["category"]],
                "evidence": [{"title": h["title"], "url": h["url"]} for h in s["strong_hits"][:3]],
            })
    # 去重
    seen = set()
    dedup = []
    for p in out:
        if p["category"] in seen:
            continue
        seen.add(p["category"])
        dedup.append(p)
    return dedup[:6]


# ================================================================ 报告渲染
def render_markdown(report: dict) -> str:
    q = report["company"]
    score = report["score"]
    lines = [
        f"# {q} 求职风险背调报告",
        "",
        f"> 生成时间：{report['meta']['time']} ｜ 耗时 {report['meta']['duration']}s ｜ "
        f"缓存：{'是' if report['meta'].get('cache_hit') else '否'}",
        "",
        "## 一、结论速览",
        f"- 评分：**{score['points']}/100** ｜ 信号灯：**{'🟢' if score['light']=='green' else '🟡' if score['light']=='yellow' else '🔴'} {score['light']}**",
        f"- 结论：{score['summary']}",
        *[f"- 原因：{r}" for r in score["reasons"]],
        "",
        "## 二、主体识别（消歧）",
    ]
    res = report.get("basic", {}).get("resolve", {})
    if res.get("matched"):
        lines.append(f"- 推荐主体：**{res['recommended']['name']}**（置信度 {res['confidence']}，"
                     f"来源 {res['recommended']['sources']}）")
        lines.append(f"- 候选（同名主体多）：")
        for c in res.get("candidates", [])[:6]:
            lines.append(f"  - {c['name']}（score {c['score']}，来源 {c['sources']}）")
    else:
        lines.append(f"- ⚠️ 未消歧成功（{res.get('confidence')}）：{res.get('note', '')}")
        for c in res.get("candidates", [])[:6]:
            lines.append(f"  - 候选：{c['name']}（score {c['score']}）")
    eb = report.get("basic", {}).get("enterprise_basic", {}) or {}
    if eb:
        lines += ["", "## 三、基础工商信息（爱企查面板）",
                  f"- 法定代表人：{eb.get('fields', {}).get('法定代表人', '未知')}",
                  f"- 注册资本：{eb.get('fields', {}).get('注册资本', '未知')}",
                  f"- 成立时间：{eb.get('fields', {}).get('成立时间', '未知')}",
                  f"- 状态/标签：{'、'.join(eb.get('tags', [])) or '未知'}"]
    lines += ["", "## 四、红线核验表（7 条）", "| # | 红线 | 状态 | 证据 |",
              "|---|------|------|------|"]
    status_icon = {"hit": "🚨 命中", "unverified": "❓ 未验证", "clean": "✅ 未见信号"}
    for rl in report.get("red_lines", []):
        ev = "；".join(f"[{e['title'][:30]}]({e['url']})" for e in rl.get("evidence", [])[:2]) or "—"
        lines.append(f"| {rl['id']} | {rl['name']} | {status_icon.get(rl['status'], rl['status'])} | {ev} |")
    lines += ["", "## 五、风险信号扫描"]
    for s in report.get("signals", []):
        n = len(s.get("strong_hits", []))
        unattr = len(s.get("unattributed_hits", []))
        mark = "🚨" if s["severity"] == "severe" and n else ("⚠️" if n else "✅")
        extra = ""
        if s.get("blocked"):
            extra += "，引擎被风控"
        if unattr:
            extra += f"，{unattr} 条未归属（标题无公司名，忽略）"
        lines.append(f"- {mark} `{s['keyword']}`（{s['category']}）：{s['n_hits']} 条结果，"
                     f"{n} 条强信号{extra}")
        for h in s.get("strong_hits", [])[:2]:
            lines.append(f"  - [{h['title'][:50]}]({h['url']})")
    lines += ["", "## 六、员工评价入口（请自行打开阅读原文）"]
    for e in report.get("reviews", {}).get("entries", [])[:10]:
        lines.append(f"- [{e['platform']}] [{e['title'][:50]}]({e['url']})")
    lines += ["", "## 七、坑点清单（投递前必读）"]
    for i, p in enumerate(report.get("pitfalls", []), 1):
        lines.append(f"{i}. **{p['risk']}**（信号：{p['keyword']}）")
        for ev in p.get("evidence", [])[:1]:
            lines.append(f"   - 证据：[{ev['title'][:50]}]({ev['url']})")
    lines += ["", "## 八、面试重点提问清单", ""]
    for i, qq in enumerate(report.get("interview_questions", []), 1):
        lines.append(f"{i}. {qq}")
    lines += ["", "## 九、需要人工核实的事项（manual_required）"]
    seen_manual = set()
    for m in report.get("basic", {}).get("manual_required", []):
        key = m.get("item", "")
        if key in seen_manual:
            continue
        seen_manual.add(key)
        lines.append(f"- **{m['item']}**：{m.get('what_to_check', '')} {m.get('url', '')}")
    for m in report.get("basic", {}).get("official_checklist", []):
        lines.append(f"- **{m['item']}**：{m.get('what_to_check', '')} {m.get('url', '')}")
    lines += ["", "---", "*本报告由 company-due-diligence skill 自动生成，红线判定需结合人工核实；"
                  "未验证 ≠ 无风险。*", ""]
    return "\n".join(lines)


def render_html(report: dict, out_path: Path) -> bool:
    if not TEMPLATE_HTML.exists():
        return False
    html = TEMPLATE_HTML.read_text(encoding="utf-8")
    payload = json.dumps(report, ensure_ascii=False)
    if "__REPORT_JSON__" in html:
        html = html.replace("__REPORT_JSON__", payload)
    else:
        html = html.replace("</head>", f'<script id="report-data" type="application/json">{payload}</script></head>')
    out_path.write_text(html, encoding="utf-8")
    return True


# ================================================================ 全流程
def run_all(name: str, opts) -> dict:
    t0 = time.time()
    cache = opts._cache
    report_cache_key = f"report:{name}"
    if not opts.no_cache:
        cached = cache.get_json(report_cache_key, "search")
        if cached:
            cached["meta"]["cache_hit"] = True
            cached["meta"]["duration"] = 0
            return cached

    basic = cmd_basic(name, opts)
    sweep = cmd_keyword_sweep(name, opts)
    news = cmd_news(name, opts)
    reviews = cmd_reviews(name, opts)

    red_lines = evaluate_red_lines(sweep)
    score = score_report(sweep, red_lines)
    pitfalls = build_pitfalls(sweep)

    report = {
        "company": name,
        "basic": basic,
        "signals": sweep.get("signals", []),
        "news": news,
        "reviews": reviews,
        "red_lines": red_lines,
        "score": score,
        "pitfalls": pitfalls,
        "interview_questions": INTERVIEW_QUESTIONS,
        "meta": {
            "generator": "company-due-diligence skill / data_fetcher.py",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration": round(time.time() - t0, 1),
            "cache_hit": False,
            "engines": opts.engines,
            "errors": [],
        },
    }
    if not opts.no_cache:
        cache.set(report_cache_key, "search", report)
    return report


# ================================================================ CLI
def _common_flags(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--engines", default=None, help="搜索引擎优先级，逗号分隔，如 baidu,bing 或 bing,baidu,ddg")
    sub.add_argument("--rate-limit", type=float, default=0.3, help="每个搜索间隔秒数（默认 0.3）")
    sub.add_argument("--timeout", type=int, default=20)
    sub.add_argument("--no-cache", action="store_true", help="跳过缓存读写")
    sub.add_argument("--json", dest="as_json", action="store_true", help="输出 JSON（默认）")
    sub.add_argument("--markdown", dest="as_markdown", action="store_true", help="输出 Markdown（all 命令）")
    sub.add_argument("--outdir", default=None, help="输出目录（默认 skills/company-due-diligence/output/<name>）")
    sub.add_argument("--verbose", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="data_fetcher", description="公司求职风险背调抓取器")
    parser.add_argument("--clear-cache", nargs="?", const="", default=None,
                        help="删除缓存（不依赖子命令）。带参数按 LIKE 模糊删除")
    parser.add_argument("--global-mode", action="store_true", help="按境外公司处理（英文名）")
    parser.add_argument("--keywords", default=None, help="keyword-sweep/all 用，逗号分隔")
    # 公共参数在主 parser 上也声明一遍（argparse parents 兼容问题修复）
    _common_flags(parser)

    sub = parser.add_subparsers(dest="command", required=False)
    for cmd in ("resolve", "basic", "keyword-sweep", "news", "reviews", "all"):
        p = sub.add_parser(cmd, help=f"{cmd} 子命令")
        _common_flags(p)
        p.add_argument("name", nargs="?", help="公司名/品牌名")
    return parser


def _out_dir(opts, name: str) -> Path:
    base = Path(opts.outdir) if opts.outdir else (SKILL_ROOT / "output")
    safe = re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "company"
    d = base / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # 顶层缓存清理（独立逻辑，不依赖子命令）
    if args.clear_cache is not None:
        cache = Cache()
        pattern = args.clear_cache or None
        n = cache.delete(pattern=pattern, category=None)
        print(f"cache cleared: {n} entries (pattern={pattern or '*'})")
        cache.close()
        return 0

    name = args.name
    if not name:
        parser.print_help()
        return 1
    if not args.command:
        args.command = "all"
    if not args.engines:
        args.engines = ["bing", "baidu"] if args.global_mode else ["baidu", "bing"]
    else:
        args.engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    cache = Cache()
    args._cache = cache
    t0 = time.time()
    warmup()

    if args.command == "resolve":
        out = cmd_resolve(name, args)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.command == "basic":
        out = cmd_basic(name, args)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.command == "keyword-sweep":
        out = cmd_keyword_sweep(name, args)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.command == "news":
        out = cmd_news(name, args)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.command == "reviews":
        out = cmd_reviews(name, args)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.command == "all":
        report = run_all(name, args)
        outdir = _out_dir(args, name)
        json_path = outdir / f"{name}.json"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md = render_markdown(report)
        md_path = outdir / f"{name}.md"
        md_path.write_text(md, encoding="utf-8")
        html_ok = render_html(report, outdir / f"{name}.html")
        print(f"[all] 评分 {report['score']['points']}/100 "
              f"({report['score']['light']}) 红线命中 {sum(1 for r in report['red_lines'] if r['status']=='hit')} 条", file=sys.stderr)
        print(f"[all] 输出目录: {outdir}", file=sys.stderr)
        print(f"[all] 文件: {json_path.name} / {md_path.name} / {name}.html ({'生成' if html_ok else '模板缺失'})", file=sys.stderr)
        if args.as_markdown:
            print(md)
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
    cache.close()
    print(f"[done] 总耗时 {round(time.time() - t0, 1)}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
