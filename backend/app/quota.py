"""额度限制：限制每个访客的生成次数 + 全部访客的总生成次数。

规则：
- 每个访客（按浏览器指纹/IP 识别）最多生成 QUOTA_PER_USER 次
- 所有访客加起来最多生成 QUOTA_TOTAL 次（用完后需手动重置）
- 计数持久化在 SQLite，重启不丢

识别访客：优先用请求头里的访客标识（X-Visitor-Id），退化为 IP。
"""
import sqlite3
import time
from pathlib import Path

from .config import QUOTA_PER_USER, QUOTA_TOTAL

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "quota.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quota (
            visitor_id TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0,
            updated_at REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quota_total (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            count INTEGER DEFAULT 0
        )
        """
    )
    conn.execute("INSERT OR IGNORE INTO quota_total (id, count) VALUES (1, 0)")
    conn.commit()
    conn.close()


def _get_total() -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT count FROM quota_total WHERE id = 1").fetchone()
    conn.close()
    return row[0] if row else 0


def _get_visitor(visitor_id: str) -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT count FROM quota WHERE visitor_id = ?", (visitor_id,)).fetchone()
    conn.close()
    return row[0] if row else 0


def check_quota(visitor_id: str) -> dict:
    """检查是否还能生成。返回 {"allowed": bool, "reason": str, "remaining": int}。"""
    total = _get_total()
    if total >= QUOTA_TOTAL:
        return {
            "allowed": False,
            "reason": "总次数已用完（50/50），请联系管理员重置额度。",
            "remaining": 0,
        }
    used = _get_visitor(visitor_id)
    if used >= QUOTA_PER_USER:
        return {
            "allowed": False,
            "reason": f"你已达到个人上限（{QUOTA_PER_USER} 次），无法继续生成。",
            "remaining": 0,
        }
    return {
        "allowed": True,
        "reason": "",
        "remaining": min(QUOTA_PER_USER - used, QUOTA_TOTAL - total),
    }


def consume(visitor_id: str):
    """成功生成后，把访客计数和总计数各 +1。"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO quota (visitor_id, count, updated_at) VALUES (?, 1, ?)
        ON CONFLICT(visitor_id) DO UPDATE SET count = count + 1, updated_at = excluded.updated_at
        """,
        (visitor_id, time.time()),
    )
    conn.execute("UPDATE quota_total SET count = count + 1 WHERE id = 1")
    conn.commit()
    conn.close()


def reset_all():
    """重置所有额度（管理员用）。"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM quota")
    conn.execute("UPDATE quota_total SET count = 0 WHERE id = 1")
    conn.commit()
    conn.close()
