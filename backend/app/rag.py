"""可降级的混合 RAG：中文 FTS5 / n-gram + 可选 Embedding。"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from openai import OpenAI

from .config import DATA_DIR, EMBED_API_KEY, EMBED_BASE_URL, EMBED_DIMENSIONS, EMBED_MODEL

logger = logging.getLogger(__name__)
DB_PATH = DATA_DIR / "marketing.db"
MIN_CHUNK_CHARS = 20
TARGET_CHUNK_CHARS = 420
CHUNK_OVERLAP_CHARS = 60


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """创建新版 RAG 表和中文 trigram FTS5 索引。"""
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            chunk_id INTEGER NOT NULL,
            record_type TEXT NOT NULL DEFAULT 'marketing',
            platform TEXT DEFAULT '',
            brand TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            category TEXT DEFAULT '',
            title TEXT DEFAULT '',
            text TEXT NOT NULL,
            source_url TEXT DEFAULT '',
            source_domain TEXT DEFAULT '',
            source_tier TEXT DEFAULT '',
            strict_eligible INTEGER,
            content_hash TEXT DEFAULT '',
            embedding_model TEXT DEFAULT '',
            vec TEXT DEFAULT '',
            UNIQUE(document_id, chunk_id)
        );
        CREATE INDEX IF NOT EXISTS idx_rag_record_type ON rag_chunks(record_type);
        CREATE INDEX IF NOT EXISTS idx_rag_platform ON rag_chunks(platform);
        CREATE INDEX IF NOT EXISTS idx_rag_brand ON rag_chunks(brand);
        CREATE INDEX IF NOT EXISTS idx_rag_hash ON rag_chunks(content_hash);

        CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunks_fts USING fts5(
            title, brand, product_name, text,
            content='rag_chunks', content_rowid='id', tokenize='trigram'
        );
        CREATE TRIGGER IF NOT EXISTS rag_chunks_ai AFTER INSERT ON rag_chunks BEGIN
            INSERT INTO rag_chunks_fts(rowid, title, brand, product_name, text)
            VALUES (new.id, new.title, new.brand, new.product_name, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS rag_chunks_ad AFTER DELETE ON rag_chunks BEGIN
            INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, title, brand, product_name, text)
            VALUES ('delete', old.id, old.title, old.brand, old.product_name, old.text);
        END;
        CREATE TRIGGER IF NOT EXISTS rag_chunks_au AFTER UPDATE ON rag_chunks BEGIN
            INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, title, brand, product_name, text)
            VALUES ('delete', old.id, old.title, old.brand, old.product_name, old.text);
            INSERT INTO rag_chunks_fts(rowid, title, brand, product_name, text)
            VALUES (new.id, new.title, new.brand, new.product_name, new.text);
        END;
        """
    )
    conn.commit()
    conn.close()


def _first(data: dict, *keys: str, default=""):
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _clean_text(value) -> str:
    if isinstance(value, list):
        value = " ".join(str(x) for x in value if x)
    return re.sub(r"[ \t]+", " ", str(value or "")).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _infer_record_type(data: dict) -> str:
    metadata = data.get("rag_metadata") or {}
    if metadata.get("record_type"):
        return str(metadata["record_type"])
    if data.get("product_id") or (data.get("产品名称") and data.get("价格")):
        return "product"
    if data.get("平台") == "小红书" or data.get("example_id"):
        return "marketing"
    if data.get("content_id") or data.get("正文"):
        return "broad_marketing_content"
    return "marketing"


def _chunk_text(text: str, target: int = TARGET_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """按标点附近切块，并保留少量重叠上下文。"""
    text = re.sub(r"\n{3,}", "\n\n", _clean_text(text))
    if not text:
        return []
    if len(text) <= target:
        return [text]
    chunks, start = [], 0
    punctuation = "。！？!?；;\n"
    while start < len(text):
        hard_end = min(start + target, len(text))
        end = hard_end
        if hard_end < len(text):
            floor = start + max(target // 2, 1)
            boundary = max(text.rfind(p, floor, hard_end) for p in punctuation)
            if boundary >= floor:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def normalize_record(data: dict, source_file: str = "") -> dict:
    """兼容项目中的中文字段、旧英文字段以及 txt/json/jsonl 数据。"""
    metadata = data.get("rag_metadata") or {}
    source_metadata = data.get("source_metadata") or {}
    record_type = _infer_record_type(data)
    brand = _clean_text(_first(data, "brand", "品牌", "商家", "商家名称"))
    platform = _clean_text(_first(data, "platform", "平台", default=metadata.get("platform", "")))
    product_name = _clean_text(_first(data, "product_name", "产品名称"))
    category = _clean_text(_first(data, "category", "产品类别", "分类"))
    title = _clean_text(_first(data, "title", "标题", default=product_name))
    source_url = _clean_text(_first(data, "source_url", "来源链接"))
    source_domain = _clean_text(_first(
        data, "source_domain", default=metadata.get("source_domain") or source_metadata.get("domain", "")
    ))
    source_tier = _clean_text(_first(
        data, "source_tier", "来源层级", default=metadata.get("source_tier", "")
    ))
    strict_value = data.get("严格营销库准入", metadata.get("strict_marketing_eligible"))
    strict_eligible = None if strict_value is None else int(bool(strict_value))

    if record_type == "product":
        fields = [
            ("品牌", brand), ("产品", product_name or title), ("类别", category),
            ("价格", _first(data, "价格", "price")), ("规格", _first(data, "规格")),
            ("热量", _first(data, "热量")), ("成分", _first(data, "成分")),
            ("卖点", _first(data, "卖点", "selling_points")),
            ("产品信息", _first(data, "产品信息")), ("其他信息", _first(data, "其他信息")),
        ]
        content = "；".join(f"{label}：{_clean_text(value)}" for label, value in fields if _clean_text(value))
        raw_chunks = [content] if content else []
    else:
        summary = _clean_text(_first(data, "摘要", "summary"))
        body = _clean_text(_first(data, "正文", "content", "text"))
        tags = _clean_text(_first(data, "话题标签", "tags"))
        content = "\n".join(x for x in (summary, body, tags) if x)
        if not content:
            provided = data.get("chunks") or []
            content = "\n".join(_clean_text(c.get("text")) for c in provided if isinstance(c, dict))
        raw_chunks = _chunk_text(content)

    identifier = _first(data, "product_id", "content_id", "example_id", "document_id")
    content_hash = _clean_text(metadata.get("content_hash")) or _sha256(content)
    document_id = _clean_text(identifier) or content_hash[:24]
    prefix_parts = []
    if platform:
        prefix_parts.append(f"平台：{platform}")
    if brand:
        prefix_parts.append(f"品牌：{brand}")
    if product_name:
        prefix_parts.append(f"产品：{product_name}")
    if category:
        prefix_parts.append(f"类别：{category}")
    if title and title != product_name:
        prefix_parts.append(f"标题：{title}")
    prefix = "；".join(prefix_parts)

    chunks = []
    for index, raw in enumerate(raw_chunks):
        raw = _clean_text(raw)
        text = f"{prefix}\n{raw}" if prefix and prefix not in raw else raw
        if len(text) >= MIN_CHUNK_CHARS:
            chunks.append({"chunk_id": index, "text": text})
    return {
        "document_id": document_id, "record_type": record_type, "platform": platform,
        "brand": brand, "product_name": product_name, "category": category, "title": title,
        "source_url": source_url, "source_domain": source_domain, "source_tier": source_tier,
        "strict_eligible": strict_eligible, "content_hash": content_hash,
        "source_file": source_file, "chunks": chunks,
    }


def _embedding_enabled() -> bool:
    return bool(EMBED_API_KEY and EMBED_MODEL)


def _embed_many(texts: list[str]) -> list[list[float]]:
    if not texts or not _embedding_enabled():
        return []
    client = OpenAI(api_key=EMBED_API_KEY, base_url=EMBED_BASE_URL)
    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=texts,
        dimensions=EMBED_DIMENSIONS,
        encoding_format="float",
    )
    return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


@lru_cache(maxsize=128)
def _embed_query(text: str) -> tuple[float, ...]:
    vectors = _embed_many([text])
    return tuple(vectors[0]) if vectors else tuple()


def ingest_records(records: Iterable[dict], progress=lambda i, n: None, append: bool = False, batch_size: int = 16) -> dict:
    """规范化、去重、可选批量向量化并写入 SQLite。"""
    init_db()
    raw_records = list(records)
    documents = [normalize_record(item, item.get("_source_file", "")) for item in raw_records]
    stats = {"records": len(documents), "chunks": 0, "embedded": 0, "embedding_failed": 0,
             "duplicates": 0, "embedding_enabled": _embedding_enabled()}
    conn = _connect()
    if not append:
        conn.execute("DELETE FROM rag_chunks")
        conn.commit()

    pending, seen = [], set()
    for doc_index, doc in enumerate(documents):
        for chunk in doc["chunks"]:
            key = (doc["document_id"], int(chunk["chunk_id"]))
            if key in seen:
                stats["duplicates"] += 1
                continue
            seen.add(key)
            pending.append((doc, chunk))
        progress(doc_index + 1, len(documents))

    for offset in range(0, len(pending), batch_size):
        batch = pending[offset: offset + batch_size]
        vectors: list[list[float] | None] = [None] * len(batch)
        if _embedding_enabled():
            try:
                embedded = _embed_many([chunk["text"] for _, chunk in batch])
                if len(embedded) != len(batch):
                    raise RuntimeError(f"Embedding 返回 {len(embedded)} 条，预期 {len(batch)} 条")
                vectors = embedded
                stats["embedded"] += len(embedded)
            except Exception as exc:
                stats["embedding_failed"] += len(batch)
                logger.exception("Embedding 批次失败，保留关键词索引: %s", exc)

        for (doc, chunk), vector in zip(batch, vectors):
            existed = conn.execute(
                "SELECT 1 FROM rag_chunks WHERE document_id=? AND chunk_id=?",
                (doc["document_id"], int(chunk["chunk_id"])),
            ).fetchone()
            if existed:
                stats["duplicates"] += 1
            conn.execute(
                """INSERT INTO rag_chunks (
                    document_id, chunk_id, record_type, platform, brand, product_name, category,
                    title, text, source_url, source_domain, source_tier, strict_eligible,
                    content_hash, embedding_model, vec
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(document_id, chunk_id) DO UPDATE SET
                    record_type=excluded.record_type, platform=excluded.platform, brand=excluded.brand,
                    product_name=excluded.product_name, category=excluded.category, title=excluded.title,
                    text=excluded.text, source_url=excluded.source_url, source_domain=excluded.source_domain,
                    source_tier=excluded.source_tier, strict_eligible=excluded.strict_eligible,
                    content_hash=excluded.content_hash, embedding_model=excluded.embedding_model, vec=excluded.vec
                """,
                (doc["document_id"], int(chunk["chunk_id"]), doc["record_type"], doc["platform"],
                 doc["brand"], doc["product_name"], doc["category"], doc["title"], chunk["text"],
                 doc["source_url"], doc["source_domain"], doc["source_tier"], doc["strict_eligible"],
                 doc["content_hash"], EMBED_MODEL if vector else "",
                 json.dumps(vector, separators=(",", ":")) if vector else ""),
            )
            stats["chunks"] += 1
        conn.commit()

    conn.execute("INSERT INTO rag_chunks_fts(rag_chunks_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    _embed_query.cache_clear()
    return stats


def ingest_marketing(jsonl_path: str, progress=lambda i, n: None, append: bool = False) -> dict:
    records = []
    with open(jsonl_path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                item["_source_file"] = str(jsonl_path)
                records.append(item)
    return ingest_records(records, progress=progress, append=append)


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def _char_ngrams(text: str, n: int) -> set[str]:
    normalized = _normalize_for_match(text)
    if len(normalized) <= n:
        return {normalized} if normalized else set()
    return {normalized[i:i + n] for i in range(len(normalized) - n + 1)}


def _lexical_score(query: str, text: str) -> float:
    q2, d2 = _char_ngrams(query, 2), _char_ngrams(text, 2)
    q3, d3 = _char_ngrams(query, 3), _char_ngrams(text, 3)
    score2 = len(q2 & d2) / max(len(q2), 1)
    score3 = len(q3 & d3) / max(len(q3), 1)
    nq, nd = _normalize_for_match(query), _normalize_for_match(text)
    exact = 1.0 if nq and nq in nd else 0.0
    return min(1.0, 0.45 * score2 + 0.45 * score3 + 0.10 * exact)


def _cosine(a: tuple[float, ...], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _fts_query(query: str) -> str:
    terms = re.findall(r"[0-9A-Za-z\u4e00-\u9fff]{3,}", query)
    return " OR ".join(f'"{term[:24]}"' for term in terms[:10])


def _fetch_fts_ranks(conn: sqlite3.Connection, query: str) -> dict[int, float]:
    expression = _fts_query(query)
    if not expression:
        return {}
    try:
        rows = conn.execute(
            """SELECT rowid FROM rag_chunks_fts
               WHERE rag_chunks_fts MATCH ?
               ORDER BY bm25(rag_chunks_fts, 1.4, 1.1, 1.3, 1.0)
               LIMIT 200""",
            (expression,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    total = max(len(rows), 1)
    return {int(row[0]): 1.0 - index / total for index, row in enumerate(rows)}


def search(query: str, top_k: int = 5, record_types: tuple[str, ...] | None = None,
           platform: str | None = None, strict_only: bool = False, min_score: float = 0.06,
           max_per_brand: int | None = 2, use_vector: bool = True) -> list[dict]:
    """混合检索，并按 document 去重、按品牌控制多样性。"""
    init_db()
    conn = _connect()
    clauses, params = [], []
    if record_types:
        clauses.append("record_type IN (%s)" % ",".join("?" for _ in record_types))
        params.extend(record_types)
    if platform:
        clauses.append("platform = ?")
        params.append(platform)
    if strict_only:
        clauses.append("strict_eligible = 1")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(f"SELECT * FROM rag_chunks{where}", params).fetchall()
    fts_ranks = _fetch_fts_ranks(conn, query)
    conn.close()

    qvec: tuple[float, ...] = tuple()
    if use_vector and _embedding_enabled() and any(row["vec"] for row in rows):
        try:
            qvec = _embed_query(query)
        except Exception as exc:
            logger.exception("查询 Embedding 失败，降级为关键词检索: %s", exc)

    scored, normalized_query = [], _normalize_for_match(query)
    for row in rows:
        combined = " ".join(str(row[key] or "") for key in ("brand", "product_name", "category", "title", "text"))
        lexical = _lexical_score(query, combined)
        fts = fts_ranks.get(int(row["id"]), 0.0)
        metadata_score = 0.0
        for key in ("product_name", "brand", "category"):
            value = _normalize_for_match(str(row[key] or ""))
            if value and value in normalized_query:
                metadata_score = min(1.0, metadata_score + 0.45)
        if row["product_name"]:
            metadata_score = max(metadata_score, _lexical_score(query, row["product_name"]))
        quality = 0.6 if row["strict_eligible"] == 1 else 0.0
        if row["source_tier"] in ("official", "primary"):
            quality += 0.4
        elif row["source_tier"] == "supplemental":
            quality += 0.15
        quality = min(1.0, quality)
        vector_score = 0.0
        if qvec and row["vec"]:
            try:
                vector_score = max(0.0, _cosine(qvec, json.loads(row["vec"])))
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        if qvec and row["record_type"] == "product":
            # 产品检索优先精确名称和关键词，语义向量用于补充近义召回。
            final = 0.30 * vector_score + 0.30 * lexical + 0.20 * fts + 0.15 * metadata_score + 0.05 * quality
        elif qvec:
            final = 0.50 * vector_score + 0.24 * lexical + 0.14 * fts + 0.07 * metadata_score + 0.05 * quality
        else:
            final = 0.58 * lexical + 0.27 * fts + 0.10 * metadata_score + 0.05 * quality
        if final >= min_score:
            scored.append((final, lexical, fts, vector_score, row))
    scored.sort(key=lambda item: item[0], reverse=True)

    results, seen_documents, brand_counts = [], set(), {}
    for final, lexical, fts, vector_score, row in scored:
        document_id, brand = row["document_id"], row["brand"] or ""
        if document_id in seen_documents or (
            max_per_brand is not None and brand and brand_counts.get(brand, 0) >= max_per_brand
        ):
            continue
        seen_documents.add(document_id)
        if brand:
            brand_counts[brand] = brand_counts.get(brand, 0) + 1
        results.append({
            "score": round(final, 4), "lexical_score": round(lexical, 4),
            "fts_score": round(fts, 4), "vector_score": round(vector_score, 4),
            "document_id": document_id, "record_type": row["record_type"],
            "platform": row["platform"], "brand": brand, "product_name": row["product_name"],
            "category": row["category"], "title": row["title"], "text": row["text"][:900],
            "source_url": row["source_url"], "source_tier": row["source_tier"],
            "strict_eligible": None if row["strict_eligible"] is None else bool(row["strict_eligible"]),
        })
        if len(results) >= top_k:
            break
    return results


MARKETING_TYPES = ("marketing", "broad_marketing_content")

PRODUCT_QUERY_ALIASES = (
    ("橙子味的美式", "橙C美式"),
    ("橙子美式", "橙C美式"),
    ("零热量冷咖啡", "冷萃冰咖啡 0 kcal"),
    ("零热量", "0 kcal"),
    ("冰沙", "星冰乐"),
    ("经典伯牙", "伯牙绝弦"),
    ("红豆抹茶", "一抹相思"),
    ("桂花咖啡", "金桂拿铁"),
    ("252卡", "252 kcal"),
    ("十九元", "¥19 19元"),
)


def _expand_product_query(query: str) -> str:
    expansions = [target for source, target in PRODUCT_QUERY_ALIASES if source.lower() in query.lower()]
    return " ".join([query, *expansions]) if expansions else query


def _normalize_product_name(value: str) -> str:
    value = re.sub(r"[（(][^）)]*[）)]", "", value or "")
    return _normalize_for_match(value.replace("原创", "").replace("首创", ""))


def search_marketing(query: str, top_k: int = 3, platform: str | None = None) -> list[dict]:
    """先按平台召回，不足时用宽口径案例补齐。"""
    primary = search(query, top_k=top_k, record_types=MARKETING_TYPES, platform=platform, min_score=0.05) if platform else []
    if len(primary) >= top_k:
        return primary
    fallback = search(query, top_k=top_k * 2, record_types=MARKETING_TYPES, min_score=0.05)
    seen = {item["document_id"] for item in primary}
    for item in fallback:
        if item["document_id"] not in seen:
            primary.append(item)
            seen.add(item["document_id"])
        if len(primary) >= top_k:
            break
    return primary


def search_products(query: str, top_k: int = 5, use_vector: bool = True) -> list[dict]:
    expanded_query = _expand_product_query(query)
    candidates = search(
        expanded_query,
        top_k=max(30, top_k * 6),
        record_types=("product",),
        min_score=0.04,
        max_per_brand=None,
        use_vector=use_vector,
    )
    # 查询明确包含品牌时，将其他品牌候选排除，避免同名产品串品牌。
    mentioned_brands = {
        item["brand"] for item in candidates
        if item.get("brand") and item["brand"].lower() in query.lower()
    }
    if mentioned_brands:
        branded = [item for item in candidates if item.get("brand") in mentioned_brands]
        if branded:
            candidates = branded
    return candidates[:top_k]


def resolve_product_context(product_name: str) -> dict | None:
    """安全解析唯一产品；同名跨品牌或低置信度时不自动注入。"""
    name = (product_name or "").strip()
    if len(name) < 2:
        return None
    candidates = search_products(name, top_k=12, use_vector=False)
    normalized_name = _normalize_product_name(name)
    exact = [
        item for item in candidates
        if _normalize_product_name(item.get("product_name", "")) == normalized_name
    ]
    if exact:
        brands = {item.get("brand", "") for item in exact}
        mentioned = [item for item in exact if item.get("brand") and item["brand"] in name]
        if mentioned:
            return mentioned[0]
        if len(brands) == 1:
            return exact[0]
        return None
    if candidates and candidates[0].get("score", 0.0) >= 0.45:
        return candidates[0]
    return None


def search_for_platforms(query: str, platforms: Iterable[str], top_k: int = 3) -> dict[str, list[dict]]:
    return {platform: search_marketing(query, top_k=top_k, platform=platform) for platform in platforms}


def index_stats() -> dict:
    init_db()
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    by_type = {row[0]: row[1] for row in conn.execute("SELECT record_type, COUNT(*) FROM rag_chunks GROUP BY record_type")}
    by_platform = {row[0] or "未标注": row[1] for row in conn.execute("SELECT platform, COUNT(*) FROM rag_chunks GROUP BY platform")}
    embedded = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE length(vec)>0").fetchone()[0]
    conn.close()
    return {"total_chunks": total, "embedded_chunks": embedded, "keyword_only_chunks": total - embedded,
            "embedding_enabled": _embedding_enabled(), "by_type": by_type, "by_platform": by_platform}
