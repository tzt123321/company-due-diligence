# -*- coding: utf-8 -*-
"""生成演示用（完全虚构数据）的报告 HTML，用于开源 README 截图。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKILL = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL / "assets" / "report-template.html"
OUT = SKILL / "docs" / "demo.html"

demo = {
    "company": "示例科技有限公司（演示数据）",
    "basic": {
        "query": "示例科技",
        "resolve": {
            "query": "示例科技", "matched": True, "confidence": "medium",
            "recommended": {"name": "示例科技有限公司", "sources": ["baidu", "bing"], "score": 26},
            "candidates": [
                {"name": "示例科技有限公司", "sources": ["baidu", "bing"], "n_sources": 2, "score": 26},
                {"name": "示例科技有限公司（某市）", "sources": ["baidu"], "n_sources": 1, "score": 8},
                {"name": "示例科技有限公司（某区）", "sources": ["baidu"], "n_sources": 1, "score": 8},
            ],
            "note": "检测到同品牌多主体，品牌真实存在；投递前务必按招聘信息中的城市/地址确认具体主体。",
        },
        "enterprise_basic": {
            "fields": {"法定代表人": "示例人", "注册资本": "500万元", "成立时间": "2015-03-12"},
            "tags": ["开业", "科技型中小企业"],
        },
        "manual_required": [
            {"item": "企业详情页（验证码拦截，需人工核对）", "url": "https://example.com/company",
             "what_to_check": "经营状态 / 被执行人 / 司法案件 / 行政处罚 / 变更记录"},
        ],
        "official_checklist": [
            {"item": "国家企业信用信息公示系统（gsxt）", "url": "https://example.com/gsxt",
             "what_to_check": "经营异常名录 / 严重违法失信 / 行政处罚 / 年报"},
            {"item": "中国执行信息公开网", "url": "https://example.com/zxgk",
             "what_to_check": "被执行人 / 失信被执行人 / 限制消费"},
        ],
    },
    "signals": [
        {"keyword": "欠薪", "category": "欠薪/劳动违法", "severity": "severe", "n_hits": 6, "blocked": False,
         "strong_hits": [
             {"title": "示例科技有限公司拖欠工资被责令改正（演示数据）", "url": "https://example.com/1",
              "snippet": "某市人社局责令该公司限期支付工资", "hit_score": 2, "attributable": True}],
         "unattributed_hits": [
             {"title": "讨薪咨询热线广告（演示数据）", "url": "https://example.com/ad", "snippet": "", "hit_score": 1, "attributable": False}]},
        {"keyword": "劳动仲裁", "category": "劳动仲裁", "severity": "medium", "n_hits": 5, "blocked": False,
         "strong_hits": [
             {"title": "示例科技有限公司劳动争议仲裁公告（演示数据）", "url": "https://example.com/2",
              "snippet": "某区劳动人事争议仲裁委员会公告", "hit_score": 1, "attributable": True}],
         "unattributed_hits": []},
        {"keyword": "被执行", "category": "被执行/失信", "severity": "severe", "n_hits": 4, "blocked": False,
         "strong_hits": [
             {"title": "示例科技有限公司 被执行人查询（演示数据）", "url": "https://example.com/3",
              "snippet": "存在执行记录，需人工核对是否已结案", "hit_score": 1, "attributable": True}],
         "unattributed_hits": []},
        {"keyword": "经营异常", "category": "经营异常", "severity": "medium", "n_hits": 3, "blocked": False,
         "strong_hits": [], "unattributed_hits": []},
        {"keyword": "社保", "category": "社保问题", "severity": "medium", "n_hits": 3, "blocked": False,
         "strong_hits": [], "unattributed_hits": []},
        {"keyword": "裁员", "category": "经营恶化", "severity": "low", "n_hits": 4, "blocked": False,
         "strong_hits": [], "unattributed_hits": []},
        {"keyword": "诉讼", "category": "诉讼风险", "severity": "medium", "n_hits": 5, "blocked": False,
         "strong_hits": [
             {"title": "示例科技有限公司开庭公告（演示数据）", "url": "https://example.com/4",
              "snippet": "多起民事诉讼开庭安排", "hit_score": 1, "attributable": True}],
         "unattributed_hits": []},
    ],
    "news": {
        "items": [
            {"title": "示例科技获评科技型中小企业（演示数据）", "url": "https://example.com/news1",
             "snippet": "", "is_news_domain": True},
            {"title": "某集团发布年中财报（演示数据）", "url": "https://example.com/news2",
             "snippet": "", "is_news_domain": True},
        ]
    },
    "reviews": {
        "entries": [
            {"platform": "知乎", "title": "在示例科技工作是什么体验？（演示数据）", "url": "https://example.com/zhihu"},
            {"platform": "职友集", "title": "示例科技怎么样-工资待遇（演示数据）", "url": "https://example.com/jobui"},
            {"platform": "脉脉", "title": "示例科技员工点评（演示数据）", "url": "https://example.com/maimai"},
        ],
        "compliance_note": "只收集入口链接，不抓取评价原文。",
    },
    "red_lines": [
        {"id": 1, "name": "当前被执行人 / 失信被执行人", "status": "hit",
         "evidence": [{"title": "示例科技有限公司 被执行人查询（演示数据）", "url": "https://example.com/3"}]},
        {"id": 2, "name": "经营异常名录 / 吊销 / 注销", "status": "clean", "evidence": []},
        {"id": 3, "name": "重大劳动保障违法 / 欠薪黑名单", "status": "hit",
         "evidence": [{"title": "示例科技有限公司拖欠工资被责令改正（演示数据）", "url": "https://example.com/1"}]},
        {"id": 4, "name": "近 1 年劳动仲裁频繁（≥5 起）", "status": "unverified", "evidence": []},
        {"id": 5, "name": "法定代表人/股东近 1 年频繁变更", "status": "unverified", "evidence": []},
        {"id": 6, "name": "近 1 年法律诉讼频繁（≥10 起）", "status": "unverified", "evidence": []},
        {"id": 7, "name": "社保欠缴被公示 / 大规模社保投诉", "status": "unverified", "evidence": []},
    ],
    "score": {
        "points": 52, "light": "yellow",
        "summary": "存在若干风险信号，投递前务必逐条核实（演示数据，非真实公司）",
        "reasons": ["欠薪: 1 条强信号", "被执行: 1 条强信号", "劳动仲裁: 1 条强信号"],
    },
    "pitfalls": [
        {"category": "欠薪/劳动违法", "keyword": "欠薪",
         "risk": "存在欠薪/劳动违法记录，工资准时性风险高（演示数据）",
         "evidence": [{"title": "示例科技有限公司拖欠工资被责令改正（演示数据）", "url": "https://example.com/1"}]},
        {"category": "被执行/失信", "keyword": "被执行",
         "risk": "存在被执行记录，入职后可能面临工资执行难、账户冻结风险（演示数据）",
         "evidence": [{"title": "示例科技有限公司 被执行人查询（演示数据）", "url": "https://example.com/3"}]},
    ],
    "interview_questions": [
        "合同与哪家公司主体签署？社保公积金缴纳主体与比例？",
        "试用期多长、薪资结构？绩效是否有书面考核标准？",
        "近一年公司是否有裁员/降薪/欠薪情况？离职率如何？",
        "发薪日是哪天？是否有过延迟？",
        "正编/外包/项目制？合同期限与续签条件？",
        "加班频率与加班费/调休政策？",
        "公司近一年诉讼/仲裁情况如何？经营现金流？",
        "直属上级与团队规模、汇报关系？",
    ],
    "meta": {
        "generator": "company-due-diligence skill（演示数据）",
        "time": "2026-08-30 12:00:00", "duration": 96.3, "cache_hit": False,
        "engines": ["baidu", "bing"], "errors": [],
    },
}

html = TEMPLATE.read_text(encoding="utf-8")
payload = json.dumps(demo, ensure_ascii=False)
OUT.parent.mkdir(parents=True, exist_ok=True)
if "__REPORT_JSON__" in html:
    html = html.replace("__REPORT_JSON__", payload)
else:
    html = html.replace("</head>", f'<script id="report-data" type="application/json">{payload}</script></head>')
OUT.write_text(html, encoding="utf-8")
print("demo written:", OUT)
