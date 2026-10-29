"""RAG 向量检索：营销案例库语义检索。

把 marketing.jsonl 里的营销案例切块 → embedding 向量化 → 存 SQLite → 语义检索。
用于文案生成时，检索最相关的爆款/营销案例作为参照。

依赖：用户端点上的 qwen3.7-text-embedding 模型（OpenAI 兼容协议）。
"""
import json
import math
import sqlite3
from pathlib import Path

from openai import OpenAI

from .config import QWEN_BASE_URL, QWEN_API_KEY

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "marketing.db"
EMBED_MODEL = "qwen3.7-text-embedding"
EMBED_DIM = 1024  # qwen3.7-text-embedding 默认维度，动态适配


def _client() -> OpenAI:
    return OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)


def _embed(text: str) -> list[float]:
    """调用 embedding 模型，把文本转成向量。"""
    client = _client()
    resp = client.embeddings.create(model=EMBED_MODEL, input=text)
    return resp.data[0].embedding


def init_db():
    """建营销案例向量表。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS marketing_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT,
            title TEXT,
            chunk_id INTEGER,
            text TEXT,
            vec TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _vec_to_str(vec: list[float]) -> str:
    return json.dumps(vec)


def _str_to_vec(s: str) -> list[float]:
    return json.loads(s)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def ingest_marketing(jsonl_path: str, progress=lambda i, n: None, append: bool = False):
    """从 marketing.jsonl 导入：切块 → embedding → 存向量库。

    append=False 时全量重建（清空后重灌）；append=True 时增量追加，不清空旧数据。
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    if not append:
        conn.execute("DELETE FROM marketing_chunks")
        conn.commit()

    total_chunks = 0
    with open(jsonl_path, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]

    for idx, line in enumerate(lines):
        d = json.loads(line)
        brand = d.get("brand", "")
        title = d.get("title", "")
        chunks = d.get("chunks", [])
        # 如果没有现成 chunks，按 500 字切
        if not chunks:
            content = d.get("content", "")
            chunks = [
                {"chunk_id": i, "text": content[i * 500 : (i + 1) * 500]}
                for i in range(0, (len(content) // 500) + 1)
                if content[i * 500 : (i + 1) * 500].strip()
            ]
        for c in chunks:
            text = (c.get("text") or "").strip()
            if len(text) < 20:
                continue
            try:
                vec = _embed(text)
            except Exception:
                continue
            conn.execute(
                "INSERT INTO marketing_chunks (brand, title, chunk_id, text, vec) VALUES (?,?,?,?,?)",
                (brand, title, c.get("chunk_id", 0), text, _vec_to_str(vec)),
            )
            total_chunks += 1
        progress(idx + 1, len(lines))

    conn.commit()
    conn.close()
    return total_chunks


def search_marketing(query: str, top_k: int = 3) -> list[dict]:
    """语义检索：输入需求 → 返回最相关的营销案例片段。"""
    init_db()
    try:
        qvec = _embed(query)
    except Exception:
        return []

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, brand, title, chunk_id, text, vec FROM marketing_chunks"
    ).fetchall()

    scored = []
    for r in rows:
        try:
            vec = _str_to_vec(r[5])
        except Exception:
            continue
        score = _cosine(qvec, vec)
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    conn.close()

    results = []
    for score, r in scored[:top_k]:
        results.append(
            {
                "score": round(score, 4),
                "brand": r[1],
                "title": r[2],
                "text": r[4][:600],
            }
        )
    return results
