"""
web/config_loader.py — JSON 配置加载与覆盖

为什么用 JSON 而不是 YAML？
  - 零额外依赖（PyYAML 需要 pip install）
  - 注释支持 JSON5 也偏门，直接 JSON + 旁路 .default 模板

用法：
    from web.config_loader import load_config
    cfg = load_config()  # 默认读 skill 根目录 config.json
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_ROOT / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "_comment": "公司求职背调 skill 配置。删除字段会自动回退到默认值。",
    "rate_limit": 0.3,
    "timeout": 20,
    "max_retries": 2,
    "engines": {
        "_comment": "搜索引擎优先级。按顺序试，第一个非空且未 blocked 的胜出",
        "CN": ["baidu", "bing"],
        "US": ["bing", "baidu", "ddg"],
        "UK": ["bing", "baidu"],
        "SG": ["bing", "baidu"],
        "HK": ["bing", "baidu"],
        "TW": ["bing", "baidu"],
        "Other": ["bing", "baidu", "ddg"],
    },
    "site_strategy": {
        "_comment": "针对特定站点的限速/重试覆写。域名作为 key",
        "www.baidu.com": {"rate_limit": 0.5, "max_retries": 3, "blocked_retries": 2},
        "www.bing.com": {"rate_limit": 0.2, "max_retries": 2},
        "html.duckduckgo.com": {"rate_limit": 1.0, "max_retries": 1},
    },
    "blocked_retries": 1,
    "warmup": True,
    "human_like_delay": {
        "_comment": "人类节奏延迟范围（秒），每次请求随机选",
        "min": 0.0,
        "max": 0.0,
    },
    "proxy": {
        "_comment": "代理设置（暂未启用，留接口）",
        "enabled": False,
        "http": "",
        "https": "",
    },
    "output": {
        "dir": str(SKILL_ROOT / "output"),
        "save_html": True,
        "save_markdown": False,
        "save_json": False,
    },
    "web": {
        "host": "127.0.0.1",
        "port": 8765,
        "debug": False,
    },
}


def load_config(path: str | Path | None = None) -> dict:
    """
    加载配置：DEFAULT_CONFIG ← 用户 config.json (覆盖)
    """
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            # 浅覆盖（不去掉 DEFAULT 的字段，让用户能只覆盖关心的部分）
            _deep_merge(cfg, user_cfg)
        except Exception as e:
            print(f"[config] 警告：{path} 解析失败 ({e})，用默认配置", file=__import__("sys").stderr)
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 dict（override 覆盖 base）"""
    for k, v in override.items():
        if k.startswith("_comment"):
            continue
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def save_default_config(path: str | Path | None = None) -> Path:
    """写出默认配置模板（首次运行用）"""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    return path


if __name__ == "__main__":
    # 单独跑：生成默认 config.json
    p = save_default_config()
    print(f"已生成默认配置: {p}")
