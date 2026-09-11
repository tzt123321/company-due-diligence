#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cache.py — SQLite 缓存层（公司背调 skill 专用）

设计要点（来自实战复盘）：
- 按数据类别分档 TTL：basic/resolve 30 天，search/review 7 天，risk 3 天，news 1 天
- 删除支持 SQL LIKE 模糊匹配（修复：缓存 key 模糊匹配失败 → 改用 LIKE %name%）
- 所有读写走同一连接 + 线程锁，脚本库双用法安全

CLI 用法：
    python cache.py --stats
    python cache.py --clear-cache              # 清空全部
    python cache.py --clear-cache 示例     # 模糊删除（LIKE %示例%）
    python cache.py --clear-cache 示例 --category risk

环境变量：
    DD_CACHE_DIR   覆盖缓存目录（默认 Windows: %LOCALAPPDATA%/company_due_diligence）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def default_cache_dir() -> str:
    """默认缓存放 skill 自己的 data/cache 目录（随 skill 走、免权限问题）；
    可用 DD_CACHE_DIR 覆盖（例如多人共用时的 %LOCALAPPDATA%/company_due_diligence）。"""
    if os.environ.get("DD_CACHE_DIR"):
        return os.environ["DD_CACHE_DIR"]
    return str(Path(__file__).resolve().parent.parent / "data" / "cache")


# 数据类别 → TTL（秒）
TTL_SECONDS: dict[str, int] = {
    "basic": 30 * 86400,     # 工商档案/基本信息：最稳定，30 天
    "resolve": 30 * 86400,   # 公司名消歧结果：30 天
    "search": 7 * 86400,     # 普通搜索结果：7 天
    "risk": 3 * 86400,       # 风险信号扫描：3 天（风险会变，不能太旧）
    "news": 1 * 86400,       # 新闻：1 天
    "review": 7 * 86400,     # 员工评价入口：7 天
}

_DEFAULT_TTL = 7 * 86400


class Cache:
    """线程安全的 SQLite 缓存。key 为字符串，value 自动 JSON 序列化。"""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(default_cache_dir(), "cache.db")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " key TEXT PRIMARY KEY,"
            " category TEXT NOT NULL,"
            " value TEXT NOT NULL,"
            " created_at REAL NOT NULL)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_category ON cache(category)")
        self._conn.commit()

    # ------------------------------------------------------------------ 读写
    def get(self, key: str, category: str = "search") -> str | None:
        """命中且未过期返回 JSON 字符串；否则 None（并顺手删除过期项）。"""
        ttl = TTL_SECONDS.get(category, _DEFAULT_TTL)
        with self._lock:
            row = self._conn.execute(
                "SELECT value, created_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        value, created = row
        if time.time() - created > ttl:
            self.delete(key=key)
            return None
        return value

    def get_json(self, key: str, category: str = "search") -> object | None:
        raw = self.get(key, category)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set(self, key: str, category: str, value: object) -> None:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache(key, category, value, created_at) VALUES(?,?,?,?)",
                (key, category, value, time.time()),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ 删除
    def delete(self, key: str | None = None, pattern: str | None = None,
               category: str | None = None) -> int:
        """key 精确删除；pattern 用 SQL LIKE %pattern% 模糊删除（修复过的问题）。"""
        sql = "DELETE FROM cache WHERE 1=1"
        args: list[object] = []
        if pattern is not None:
            sql += " AND key LIKE ?"
            args.append(f"%{pattern}%")
        if key is not None:
            sql += " AND key = ?"
            args.append(key)
        if category is not None:
            sql += " AND category = ?"
            args.append(category)
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------ 统计
    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            by_cat = self._conn.execute(
                "SELECT category, COUNT(*), MAX(created_at) FROM cache GROUP BY category"
            ).fetchall()
        return {
            "path": self.path,
            "total_entries": total,
            "by_category": [{"category": c, "count": n, "last_write": ts} for c, n, ts in by_cat],
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="公司背调缓存工具")
    parser.add_argument("--stats", action="store_true", help="显示缓存统计")
    parser.add_argument("--clear-cache", nargs="?", const="", default=None,
                        help="删除缓存。不带参数=清空全部；带参数=按 LIKE 模糊删除")
    parser.add_argument("--category", default=None, help="仅操作该类别（basic/search/risk/news/review/resolve）")
    args = parser.parse_args()

    cache = Cache()
    try:
        if args.stats:
            print(json.dumps(cache.stats(), ensure_ascii=False, indent=2))
        if args.clear_cache is not None:
            pattern = args.clear_cache or None
            n = cache.delete(pattern=pattern, category=args.category)
            print(f"deleted {n} entries (pattern={pattern or '*'}, category={args.category or '*'})")
        if not args.stats and args.clear_cache is None:
            parser.print_help()
            return 1
        return 0
    finally:
        cache.close()


if __name__ == "__main__":
    sys.exit(main())
