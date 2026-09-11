"""
web/app.py — 公司求职背调 Web UI（Flask）

启动：
    python -m web.app
    或 python web/app.py
    默认监听 127.0.0.1:8765

打开浏览器访问 http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

# 让 import data_fetcher 能找到
SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from flask import (  # type: ignore
    Flask, request, jsonify, send_file, render_template_string,
    abort, Response,
)

import data_fetcher as df  # noqa: E402

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False  # 中文不转义

# 加载配置（JSON，不引入 yaml 依赖）
try:
    from config_loader import load_config
    CONFIG = load_config()
except Exception as e:
    print(f"[web] 配置加载失败，使用内置默认: {e}", file=__import__("sys").stderr)
    CONFIG = {
        "rate_limit": 0.3, "engines": {}, "output": {"dir": str(SKILL_ROOT / "output")},
        "site_strategy": {}, "blocked_retries": 1, "warmup": True,
        "human_like_delay": {"min": 0.0, "max": 0.0}, "proxy": {"enabled": False},
    }

# 内存中的最近一次报告（避免重复跑全流程）
_LAST_REPORT: dict[str, dict] = {}
_LAST_REPORT_LOCK = threading.Lock()

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>公司求职背调</title>
<style>
:root {
  --bg:#0f172a; --card:#1e293b; --card-2:#334155;
  --text:#e2e8f0; --muted:#94a3b8;
  --green:#22c55e; --yellow:#eab308; --red:#ef4444;
  --accent:#3b82f6;
}
* { box-sizing:border-box; }
body {
  margin:0; font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg); color:var(--text); line-height:1.6;
}
.container { max-width:920px; margin:0 auto; padding:32px 20px; }
h1 { margin:0 0 8px; font-size:28px; }
.subtitle { color:var(--muted); margin:0 0 24px; font-size:14px; }
.card { background:var(--card); border-radius:12px; padding:24px; margin-bottom:16px; }
label { display:block; font-size:13px; color:var(--muted); margin:8px 0 4px; }
input, select, textarea {
  width:100%; padding:10px 12px; border:1px solid var(--card-2);
  background:var(--bg); color:var(--text); border-radius:8px; font-size:14px;
  font-family:inherit;
}
input:focus, select:focus, textarea:focus { outline:none; border-color:var(--accent); }
.row { display:grid; grid-template-columns:2fr 1fr 1fr; gap:12px; }
.row3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
@media (max-width:600px) { .row, .row3 { grid-template-columns:1fr; } }
button {
  padding:10px 18px; border:none; background:var(--accent); color:white;
  border-radius:8px; font-size:14px; font-weight:600; cursor:pointer;
  margin-top:12px;
}
button:hover:not(:disabled) { background:#2563eb; }
button:disabled { background:var(--card-2); cursor:not-allowed; }
.status { margin-top:16px; padding:12px; border-radius:8px; font-size:13px; }
.status.info { background:#1e3a8a; color:#dbeafe; }
.status.ok { background:#14532d; color:#bbf7d0; }
.status.err { background:#7f1d1d; color:#fecaca; }
pre {
  background:var(--bg); border:1px solid var(--card-2); border-radius:8px;
  padding:16px; overflow:auto; max-height:480px; font-size:12px;
  font-family:"JetBrains Mono",Consolas,monospace; line-height:1.5;
}
.kbd {
  display:inline-block; padding:2px 6px; background:var(--card-2);
  border-radius:4px; font-family:monospace; font-size:12px;
}
.tips { color:var(--muted); font-size:13px; }
.tag {
  display:inline-block; padding:2px 8px; background:var(--card-2);
  border-radius:4px; font-size:11px; margin-right:4px;
}
</style>
</head>
<body>
<div class="container">
  <h1>🔍 公司求职背调</h1>
  <p class="subtitle">基于 <span class="kbd">company-due-diligence</span> skill · L1 curl_cffi 指纹爬取 · 30+ 风险关键词扫描</p>

  <div class="card">
    <form id="form">
      <label>公司名 <span class="tips">（平台展示名也行，会自动消歧到工商全称）</span></label>
      <input id="name" name="name" placeholder="例如：亿达信息 / 菜鸟 / 华为 / Stripe" required>

      <div class="row">
        <div>
          <label>司法辖区</label>
          <select id="jurisdiction" name="jurisdiction">
            <option value="CN" selected>中国大陆 CN</option>
            <option value="US">美国 US</option>
            <option value="UK">英国 UK</option>
            <option value="SG">新加坡 SG</option>
            <option value="HK">香港 HK</option>
            <option value="TW">台湾 TW</option>
            <option value="Other">其他 Other</option>
          </select>
        </div>
        <div>
          <label>搜索引擎</label>
          <select id="engines" name="engines">
            <option value="auto" selected>auto（默认）</option>
            <option value="baidu,bing">百度+必应</option>
            <option value="bing,baidu">必应+百度</option>
            <option value="bing">仅必应</option>
            <option value="baidu">仅百度</option>
          </select>
        </div>
        <div>
          <label>限速（秒/关键词）</label>
          <input id="rate" name="rate" type="number" value="0.3" min="0" max="5" step="0.1">
        </div>
      </div>

      <div class="row3">
        <div>
          <label><input type="checkbox" id="skip_cache" name="skip_cache"> 跳过缓存</label>
        </div>
        <div>
          <label><input type="checkbox" id="include_reviews" name="include_reviews" checked> 收集员工评价入口</label>
        </div>
        <div>
          <label><input type="checkbox" id="save_html" name="save_html" checked> 保存 HTML 报告</label>
        </div>
      </div>

      <button type="submit" id="btn">开始背调</button>
      <span class="tips">首次跑全流程约 30-90 秒，结果会缓存 1-30 天</span>
    </form>

    <div id="status" class="status info" style="display:none"></div>
  </div>

  <div id="result" class="card" style="display:none">
    <h2 id="r-title">报告</h2>
    <div id="r-summary"></div>
    <div style="margin-top:16px; display:flex; gap:8px; flex-wrap:wrap">
      <button id="dl-md">下载 Markdown</button>
      <button id="dl-html">下载 HTML</button>
      <button id="dl-json">下载原始 JSON</button>
    </div>
    <h3 style="margin-top:24px">JSON 预览</h3>
    <pre id="r-json"></pre>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const status = (msg, kind='info') => {
  const el = $('#status');
  el.className = 'status ' + kind;
  el.textContent = msg;
  el.style.display = 'block';
};

$('#form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = $('#name').value.trim();
  if (!name) return;
  const engines = $('#engines').value;
  const jurisdiction = $('#jurisdiction').value;
  const opts = {
    name, jurisdiction,
    engines: engines === 'auto' ? null : engines.split(','),
    rate: parseFloat($('#rate').value),
    skip_cache: $('#skip_cache').checked,
    include_reviews: $('#include_reviews').checked,
    save_html: $('#save_html').checked,
  };

  $('#btn').disabled = true;
  status('正在跑全流程（消歧 → 工商 → 关键词扫描 → 新闻 → 评价入口）……', 'info');
  $('#result').style.display = 'none';

  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(opts),
    });
    const j = await r.json();
    if (!j.ok) { status('失败：' + (j.error || 'unknown'), 'err'); return; }

    status('完成 · 风险等级 ' + j.report.summary.risk_level + ' · 总分 ' + j.report.summary.score, 'ok');

    // 摘要
    const s = j.report.summary;
    $('#r-title').textContent = '报告：' + j.report.company + '（' + j.report.jurisdiction + '）';
    $('#r-summary').innerHTML = `
      <p><span class="tag">${s.risk_level}</span>
         <span class="tag">红线命中 ${s.red_lines_hit}</span>
         <span class="tag">扫描关键词 ${s.keywords_scanned}</span>
         <span class="tag">消歧候选 ${s.candidates_count}</span></p>
      <p>${s.verdict || ''}</p>
    `;
    $('#r-json').textContent = JSON.stringify(j.report, null, 2);

    // 下载链接
    $('#dl-md').onclick = () => downloadFile('/api/download/md', opts);
    $('#dl-html').onclick = () => downloadFile('/api/download/html', opts);
    $('#dl-json').onclick = () => downloadFile('/api/download/json', opts);

    $('#result').style.display = 'block';
  } catch (e) {
    status('请求失败：' + e.message, 'err');
  } finally {
    $('#btn').disabled = false;
  }
});

function downloadFile(path, opts) {
  // 简单方案：跳转到带 query 的 URL
  const u = new URL(path, location.origin);
  u.searchParams.set('name', opts.name);
  u.searchParams.set('jurisdiction', opts.jurisdiction);
  if (opts.engines) u.searchParams.set('engines', opts.engines.join(','));
  location.href = u.toString();
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 简单的配置（从 config_loader 加载）
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "rate_limit": 0.3,
    "engines": None,           # None = data_fetcher 默认
    "skip_cache": False,
    "include_reviews": True,
    "save_html": True,
    "output_dir": str(SKILL_ROOT / "output"),
}


def _run_report(opts: dict) -> dict:
    """
    调 data_fetcher.run_all 生成报告（同步版）。
    opts 字段：name, jurisdiction, engines, rate, skip_cache, include_reviews, save_html
    """
    name = opts["name"]
    jur = opts.get("jurisdiction", "CN")
    is_global = jur not in ("CN", "HK", "TW")  # 简化判断

    # 引擎优先级：用户传入 > 配置按辖区选 > None（用 data_fetcher 默认）
    engines = opts.get("engines")
    if not engines:
        engines = CONFIG.get("engines", {}).get(jur)

    # 限速：用户传入 > 配置
    rate = opts.get("rate")
    if rate is None:
        rate = CONFIG.get("rate_limit", 0.3)

    # 构造一个 opts 对象（模拟 argparse Namespace）
    class _O:
        pass
    o = _O()
    o.global_mode = is_global
    o.engines = engines
    o.rate_limit = float(rate)
    o.no_cache = bool(opts.get("skip_cache", False))
    o.markdown = bool(opts.get("save_md", False))
    o.outdir = None
    o.verbose = False
    o.keywords = None
    o.timeout = CONFIG.get("timeout", 20)
    o._cache = df.Cache()  # run_all / cmd_* 都需要

    # run_all 内部已经整合 resolve / basic / keyword-sweep / news / reviews / 评分
    report = df.run_all(name, o)
    return report


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/run", methods=["POST"])
def api_run():
    opts = request.get_json(force=True)
    if not opts or not opts.get("name"):
        return jsonify({"ok": False, "error": "name required"}), 400
    try:
        report = _run_report(opts)
        key = f"{opts.get('jurisdiction','CN')}:{opts['name']}"
        with _LAST_REPORT_LOCK:
            _LAST_REPORT[key] = report
        return jsonify({"ok": True, "report": report})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


def _parse_qs_opts():
    """从 query string 解析 opts（用于下载）"""
    name = request.args.get("name", "").strip()
    if not name:
        abort(400, "name required")
    jur = request.args.get("jurisdiction", "CN")
    engines_str = request.args.get("engines", "")
    engines = [e for e in engines_str.split(",") if e] if engines_str else None
    return {
        "name": name, "jurisdiction": jur, "engines": engines,
        "rate": 0.3, "skip_cache": False, "include_reviews": True,
    }


def _get_or_run(opts: dict) -> dict:
    """从内存取上次的报告；没有就跑一次"""
    key = f"{opts.get('jurisdiction','CN')}:{opts['name']}"
    with _LAST_REPORT_LOCK:
        if key in _LAST_REPORT:
            return _LAST_REPORT[key]
    report = _run_report(opts)
    with _LAST_REPORT_LOCK:
        _LAST_REPORT[key] = report
    return report


@app.route("/api/download/md")
def dl_md():
    opts = _parse_qs_opts()
    report = _get_or_run(opts)
    md = df.render_markdown(report)
    return Response(
        md.encode("utf-8"),
        mimetype="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="report-{opts["name"]}.md"',
        },
    )


@app.route("/api/download/html")
def dl_html():
    opts = _parse_qs_opts()
    report = _get_or_run(opts)
    outdir = Path(CONFIG.get("output", {}).get("dir") or DEFAULT_CONFIG["output_dir"])
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"report-{opts['name']}.html"
    ok = df.render_html(report, out)
    if not ok or not out.exists():
        abort(500, "render_html failed")
    return send_file(out, as_attachment=True,
                     download_name=f"report-{opts['name']}.html")


@app.route("/api/download/json")
def dl_json():
    opts = _parse_qs_opts()
    report = _get_or_run(opts)
    data = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        data, mimetype="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="report-{opts["name"]}.json"',
        },
    )


@app.route("/api/health")
def health():
    """健康检查：返回可用状态 + L1/L2/L3 可用性"""
    return jsonify({
        "ok": True,
        "skill": "company-due-diligence",
        "l1": True,  # curl_cffi
        "l2": _is_l2_available(),
        "l3": _is_l3_available(),
    })


def _is_l2_available() -> bool:
    try:
        import real_browser
        return real_browser.is_available()
    except Exception:
        return False


def _is_l3_available() -> bool:
    try:
        import fingerprint_browser
        return bool(os.environ.get("BITBROWSER_API") or
                    os.environ.get("ADSPOWER_API"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main():
    import argparse
    web_cfg = CONFIG.get("web", {})
    p = argparse.ArgumentParser(description="公司求职背调 Web UI")
    p.add_argument("--host", default=web_cfg.get("host", "127.0.0.1"))
    p.add_argument("--port", type=int, default=web_cfg.get("port", 8765))
    p.add_argument("--debug", action="store_true",
                   default=web_cfg.get("debug", False))
    args = p.parse_args()
    print(f"  启动 Web UI: http://{args.host}:{args.port}")
    print(f"  健康检查:    http://{args.host}:{args.port}/api/health")
    print(f"  L1: ✓ curl_cffi  |  L2: {'✓' if _is_l2_available() else '✗ undetected-chromedriver 缺'}  |  "
          f"L3: {'✓' if _is_l3_available() else '✗ 指纹浏览器未配置'}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
