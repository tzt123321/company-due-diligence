#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fuzzy_resolve.py — 公司名模糊匹配消歧（5 策略 + 多源印证打分）

背景（来自实战复盘）：
    用户从招聘平台看到的往往是"品牌名/简称"，比如"某科技"，
    而工商全称可能是"某科技有限公司（某市）" / "某科技有限公司某区分公司" ——
    搜不到本质是名字对不上，不是公司不存在。

5 个独立消歧策略：
    S1 brand_map        品牌名 → 母公司映射表（data/brand_map.json，O(1) 命中，可扩充）
    S2 suffix_complete  自动补全后缀（"某科技" → 搜索 "某科技 公司" 提取候选）
    S3 opencorporates   多辖区注册数据库 API（需 OPENCORPORATES_API_KEY，公共 API 常 401）
    S4 bing             搜索引擎 + 实体名提取（境外公司主用）
    S5 duckduckgo       DDG 兜底（部分网络会超时，优雅降级）

打分规则：
    每来源命中加基础分（brand_map 15 / opencorporates 15 / baidu 8 / bing 8 / ddg 6 /
    suffix 派生 4）；同一候选被多个独立来源命中，每个额外来源再 +10（多源印证）。
    置信度：score>=30 high，>=20 medium，>=8 low，否则 manual_required。

CLI：
    python fuzzy_resolve.py "示例科技"
    python fuzzy_resolve.py "Yida Information" --global-mode
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from browser_http import search, warmup

# ---------------------------------------------------------------- 常量
SKILL_ROOT = Path(__file__).resolve().parent.parent
BRAND_MAP_PATH = Path(os.environ.get("DD_BRAND_MAP", SKILL_ROOT / "data" / "brand_map.json"))

CN_SUFFIX_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9（）()·—\-]{2,60}?(?:股份有限公司|有限责任公司|有限公司|公司|集团))"
)
GLOBAL_SUFFIX_RE = re.compile(
    r"([A-Za-z0-9&.,'’\- ]{2,60}?(?:Inc\.?|LLC|Ltd\.?|Pte\.?\s*Ltd|Co\.,?\s*Ltd|"
    r"Corp\.?|Corporation|GmbH|S\.?A\.?|B\.?V\.?|K\.?K\.?|Sdn\.?\s*Bhd|Holdings?))"
)
STRIP_CN_SUFFIX = ("股份有限公司", "有限责任公司", "有限公司", "公司", "集团")

BASE_SCORE = {"brand_map": 15, "opencorporates": 15, "baidu": 8, "bing": 8, "ddg": 6, "suffix": 4}
MULTI_SOURCE_BONUS = 10  # 多源印证 +10/次
EXACT_BONUS = 5


# ---------------------------------------------------------------- 基础工具
def normalize(name: str) -> str:
    """统一空格/全角/大小写，用于 key 与比较。"""
    s = unicodedata.normalize("NFKC", name or "").strip()
    s = re.sub(r"\s+", "", s)
    return s.lower()


def strip_suffix(name: str) -> str:
    """去掉 CN 公司后缀，得到品牌核心词。"""
    s = normalize(name)
    for suf in STRIP_CN_SUFFIX:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
            break
    # 去掉（某市）（某区）这类地区括号
    s = re.sub(r"[（(][^（）()]*[）)]", "", s)
    return s


def load_brand_map() -> dict:
    if not BRAND_MAP_PATH.exists():
        return {}
    try:
        return json.loads(BRAND_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def extract_candidates(text: str, is_global: bool = False) -> list[str]:
    """从标题/文本中提取类公司实体名。"""
    pat = GLOBAL_SUFFIX_RE if is_global else CN_SUFFIX_RE
    return [m.group(1).strip().strip("，。、") for m in pat.finditer(text)]


# 候选名里的"句子杂质"子串：出现即丢弃（如"某科技是外包公司"）
JUNK_SUBSTRINGS = ["是外包", "请问", "怎么样", "怎幺样", "招聘", "评价", "工资",
                   "加班", "待遇", "这家", "那个", "好不好", "怎么样", "听说",
                   "为什么", "什么", "知乎", "百度知道"]


def base_name(name: str) -> str:
    """去地区括号得到家族基名："某科技有限公司（某市）" → "某科技有限公司" """
    return re.sub(r"[（(][^（）()]*[）)]", "", name)


def clean_candidate(candidate: str, core: str, is_global: bool = False) -> str | None:
    """过滤杂质候选，返回规整后的名字或 None。"""
    c = candidate.strip()
    if len(c) < 4 or len(c) > 40:
        return None
    if is_global:
        return c if relevant(c, core, is_global=True) else None
    # 去掉句首杂质词
    c = re.sub(r"^(请问|关于|据说|听说|这是|那个)", "", c)
    if any(sub in c for sub in JUNK_SUBSTRINGS):
        return None
    if not relevant(c, core):
        return None
    return c


def relevant(candidate: str, core: str, is_global: bool = False) -> bool:
    """候选是否与查询核心相关。"""
    c = normalize(candidate)
    k = normalize(core)
    if len(k) < 2:
        return True
    if is_global:
        # 英文：token 级子串匹配
        cw = set(re.findall(r"[a-z0-9&]+", c))
        kw = set(re.findall(r"[a-z0-9&]+", k))
        return len(kw) > 0 and len(kw & cw) >= max(1, len(kw) - 1)
    return k in c


# ---------------------------------------------------------------- 各策略
def strategy_brand_map(query: str) -> list[tuple[str, str, str]]:
    """S1：品牌映射表。返回 [(company, country, note)]"""
    bm = load_brand_map()
    q = normalize(query)
    out: list[tuple[str, str, str]] = []
    for brand, info in bm.items():
        nb = normalize(brand)
        if q == nb or (len(q) >= 4 and q in nb) or (len(nb) >= 4 and nb in q):
            out.append((info.get("company", brand), info.get("country", "CN"),
                        info.get("note", "brand_map 命中")))
    return out


def strategy_search_cn(core: str) -> list[tuple[str, str]]:
    """S2+S4(CN)：百度搜索"核心词"与"核心词 公司"，从标题提取候选。返回 [(company, source)]"""
    found: list[tuple[str, str]] = []
    for q in (core, f"{core} 公司", f"{core} 有限公司"):
        r = search("baidu", q, limit=10, rate_limit=0.4)
        for res in r["results"]:
            for cand in extract_candidates(res["title"], is_global=False):
                c = clean_candidate(cand, core)
                if c:
                    found.append((c, "baidu"))
    return found


def strategy_search_global(core: str) -> list[tuple[str, str]]:
    """S4(global)+S5：Bing/DDG 搜索并提取英文实体名。"""
    found: list[tuple[str, str]] = []
    for eng, q in (("bing", f'"{core}" company'), ("bing", core), ("ddg", core)):
        try:
            r = search(eng, q, limit=8, rate_limit=0.4)
        except Exception:
            continue
        for res in r["results"]:
            for cand in extract_candidates(res["title"], is_global=True):
                c = clean_candidate(cand, core, is_global=True)
                if c:
                    found.append((c, eng))
    return found


def strategy_opencorporates(core: str, is_global: bool) -> list[tuple[str, str]]:
    """S3：OpenCorporates API（多辖区注册库）。公共 API 常 401，需 API key。"""
    key = os.environ.get("OPENCORPORATES_API_KEY", "")
    if not key:
        return []
    try:
        from curl_cffi import requests as cr
        params: dict = {"q": core, "per_page": 5}
        if key:
            params["api_token"] = key
        r = cr.get("https://api.opencorporates.com/v0.4/companies/search",
                   params=params, impersonate="chrome131", timeout=15)
        if r.status_code != 200:
            return []
        comps = r.json().get("results", {}).get("companies", [])
        out = []
        for c in comps:
            co = c.get("company", {})
            name = co.get("name", "")
            if name and relevant(name, core, is_global):
                out.append((name, "opencorporates"))
        return out
    except Exception:
        return []


# ---------------------------------------------------------------- 主流程
def resolve(query: str, is_global: bool | None = None) -> dict:
    """消歧主入口。返回结构化结果供 LLM 消费。"""
    query = query.strip()
    core = strip_suffix(query)
    if is_global is None:
        is_global = not re.search(r"[\u4e00-\u9fa5]", query)

    sources_used: list[str] = []
    raw_hits: list[tuple[str, str]] = []  # (company, source)

    # S1 品牌映射
    for company, country, note in strategy_brand_map(query):
        raw_hits.append((company, "brand_map"))

    # S2/S4 搜索提取
    if is_global:
        raw_hits += strategy_search_global(core)
    else:
        raw_hits += strategy_search_cn(core)
        # S5 DDG 兜底（CN 公司名，失败静默）
        try:
            r = search("ddg", query, limit=8, rate_limit=0.4)
            for res in r["results"]:
                for cand in extract_candidates(res["title"]):
                    c = clean_candidate(cand, core)
                    if c:
                        raw_hits.append((c, "ddg"))
        except Exception:
            pass

    # S3 OpenCorporates
    raw_hits += strategy_opencorporates(core, is_global)

    if not raw_hits:
        return {
            "query": query, "normalized": normalize(query), "is_global": is_global,
            "matched": False, "candidates": [], "recommended": None,
            "confidence": "manual", "manual_required": True,
            "sources_used": [], "note": "0 命中：可能是反爬，也可能是公司太新/太小。"
                                        "建议：用 L2 真实浏览器重试，或核对招聘信息里的工商全称。",
        }

    # ---- 合并打分 ----
    merged: dict[str, dict] = {}
    for company, source in raw_hits:
        key = normalize(company)
        if key not in merged:
            merged[key] = {"name": company, "sources": set(), "exact": False}
        merged[key]["sources"].add(source)
        if normalize(company) == normalize(query):
            merged[key]["exact"] = True
        sources_used.append(source)

    candidates = []
    for key, m in merged.items():
        n_src = len(m["sources"])
        score = sum(BASE_SCORE.get(s, 0) for s in m["sources"]) + MULTI_SOURCE_BONUS * max(0, n_src - 1)
        if m["exact"]:
            score += EXACT_BONUS
        candidates.append({
            "name": m["name"],
            "normalized": key,
            "sources": sorted(m["sources"]),
            "n_sources": n_src,
            "score": score,
            "exact_match": m["exact"],
        })
    candidates.sort(key=lambda c: (-c["score"], -c["n_sources"]))

    candidates.sort(key=lambda c: (-c["score"], -c["n_sources"]))

    top = candidates[0]

    # ---- 家族聚合 ----
    # 实战教训：平台简称"某科技"对应"某科技有限公司"及其多个地区注册主体。
    # 单个主体可能只有 1 个来源（score=8），但同家族 ≥2 个主体互证 → 品牌真实存在。
    families: dict[str, list[dict]] = {}
    for c in candidates:
        families.setdefault(base_name(c["name"]), []).append(c)
    fam_name, members = max(
        families.items(), key=lambda kv: (len(kv[1]), max(x["score"] for x in kv[1]))
    )
    fam_n = len(members)
    fam_score = max(m["score"] for m in members)

    if top["score"] >= 30:
        confidence = "high"
    elif top["score"] >= 20:
        confidence = "medium"
    elif fam_n >= 2:
        confidence = "medium"  # 家族多主体互证
    elif top["score"] >= 8:
        confidence = "low"
    else:
        confidence = "manual"

    matched = confidence in ("high", "medium") or (confidence == "low" and top["exact_match"])

    recommended = top if matched else None
    if matched and fam_n >= 2 and confidence == "medium" and not top["exact_match"]:
        recommended = {
            "name": fam_name,
            "normalized": normalize(fam_name),
            "sources": sorted({s for m in members for s in m["sources"]}),
            "n_sources": len({s for m in members for s in m["sources"]}),
            "score": fam_score,
            "exact_match": False,
            "family_members": [m["name"] for m in members],
        }

    note = ("候选为同品牌下的不同注册主体；同名公司多时，请结合招聘信息里的"
            "城市/地址/岗位确认目标主体。")
    if fam_n >= 2:
        note = (f"检测到同品牌多主体（{fam_n} 个注册主体同属 '{fam_name}' 家族），"
                "品牌真实存在；但投递前务必按招聘信息中的城市/地址/岗位确认具体是哪个主体，"
                "再针对该主体核验风险。")

    return {
        "query": query,
        "normalized": normalize(query),
        "is_global": is_global,
        "matched": matched,
        "candidates": candidates,
        "recommended": recommended,
        "confidence": confidence,
        "manual_required": not matched,
        "sources_used": sorted(set(sources_used)),
        "note": note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="公司名模糊匹配消歧")
    parser.add_argument("name", help="要消歧的公司名/品牌名")
    parser.add_argument("--global-mode", action="store_true",
                        help="强制按境外公司处理（否则按是否含中文自动判断）")
    args = parser.parse_args()
    warmup()
    out = resolve(args.name, is_global=True if args.global_mode else None)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
