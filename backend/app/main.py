import os
import base64
import logging
import re
from fastapi import FastAPI, File, Form, UploadFile, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

from .pipeline import run_pipeline
from .providers import revise, image, copywriting, vision
from .config import USE_MOCK, USE_IMAGE_MOCK, APP_ACCESS_KEY, ADMIN_RESET_KEY
from . import db, rag, quota
from .v2 import create_router

app_logger = logging.getLogger("app")
app_logger.setLevel(logging.INFO)
if not app_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    app_logger.addHandler(handler)
app_logger.propagate = False

app = FastAPI(title="AI 营销素材生成工具")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _visitor_id(x_forwarded_for: str = Header(None), x_visitor_id: str = Header(None)) -> str:
    """识别访客：优先用前端传来的 X-Visitor-Id，否则用 IP。"""
    if x_visitor_id:
        return x_visitor_id
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return "unknown"


def require_quota(visitor: str = Depends(_visitor_id)):
    """额度校验依赖：生成接口统一调用。"""
    result = quota.check_quota(visitor)
    if not result["allowed"]:
        raise HTTPException(status_code=429, detail=result["reason"])
    return visitor


class GenerateRequest(BaseModel):
    product_name: str
    selling_points: str
    price: str = ""
    poster_url: str = ""


class AccessRequest(BaseModel):
    key: str = ""


class AdminResetRequest(BaseModel):
    admin_key: str = ""


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mock": USE_MOCK,
        "image_mock": USE_IMAGE_MOCK,
        "need_key": bool(APP_ACCESS_KEY),
    }


@app.post("/api/admin/reset_quota")
def reset_quota(req: AdminResetRequest):
    """管理员重置额度：需要正确的管理密钥。"""
    if not ADMIN_RESET_KEY:
        raise HTTPException(status_code=403, detail="未配置管理密钥")
    if req.admin_key != ADMIN_RESET_KEY:
        raise HTTPException(status_code=403, detail="管理密钥错误")
    quota.reset_all()
    return {"ok": True, "message": "额度已重置"}


@app.post("/api/verify_key")
def verify_key(req: AccessRequest):
    """校验访问密码。返回剩余额度信息。"""
    if not APP_ACCESS_KEY:
        return {"ok": True}
    if req.key.strip() == APP_ACCESS_KEY:
        return {"ok": True}
    return {"ok": False, "reason": "密码错误"}


@app.get("/api/quota")
def get_quota(visitor: str = Depends(_visitor_id)):
    """查看当前额度状态。"""
    return quota.check_quota(visitor)


@app.get("/api/lookup")
def lookup(name: str):
    """按产品名检索知识库，返回价格+卖点（供一键填入）。"""
    product = db.lookup_product(name)
    return {"found": product is not None, "product": product}


@app.get("/api/search")
def search(q: str):
    """产品联想：合并传统 SQLite 与本地产品 RAG，不触发远程 Embedding。"""
    sql_results = [dict(item, source="products_db", score=1.0) for item in db.search_products(q)]
    rag_results = []
    if len(q.strip()) >= 2:
        try:
            rag_hits = rag.search_products(q, top_k=12, use_vector=False)
            strong_hits = [hit for hit in rag_hits if hit.get("score", 0.0) >= 0.18]
            rag_results = [
                _product_hit_to_suggestion(hit)
                for hit in (strong_hits or rag_hits[:5])
            ]
        except Exception:
            rag_results = []

    merged = []
    seen = set()
    for item in sql_results + rag_results:
        key = ((item.get("brand") or "").strip(), (item.get("name") or "").strip())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return {"results": merged[:8], "rag_used": bool(rag_results)}


def _product_hit_to_suggestion(hit: dict) -> dict:
    """把产品 RAG 的结构化文本转换成前端现有候选格式。"""
    text = hit.get("text", "")
    fields = {
        label.strip(): value.strip()
        for label, value in re.findall(r"(?:^|[；\n])([^：；\n]+)：([^；\n]*)", text)
    }
    facts = []
    for label in ("卖点", "成分", "规格", "热量"):
        value = fields.get(label, "")
        if value:
            facts.append(f"{label}{value}")
    if not facts and fields.get("产品信息"):
        facts.append(fields["产品信息"])
    return {
        "brand": hit.get("brand", ""),
        "name": hit.get("product_name") or hit.get("title", ""),
        "selling_points": "、".join(facts),
        "price": fields.get("价格", ""),
        "category": hit.get("category", ""),
        "source": "product_rag",
        "score": hit.get("score", 0.0),
        "document_id": hit.get("document_id", ""),
    }


@app.get("/api/product_search")
def product_search(q: str, top_k: int = 5):
    """显式语义产品搜索：调用查询 Embedding，适合别名和自然语言描述。"""
    hits = rag.search_products(q, top_k=max(1, min(top_k, 20)), use_vector=True)
    return {
        "query": q,
        "results": [_product_hit_to_suggestion(hit) for hit in hits],
        "semantic": True,
    }


@app.get("/api/rag_search")
def rag_search(q: str, top_k: int = 3, platform: str = "", kind: str = "marketing"):
    """语义检索营销案例库（RAG），返回最相关的爆款/营销案例片段。"""
    if kind == "product":
        results = rag.search_products(q, top_k=top_k)
    else:
        results = rag.search_marketing(q, top_k=top_k, platform=platform or None)
    return {"query": q, "platform": platform, "kind": kind, "results": results}


@app.get("/api/rag_stats")
def rag_stats():
    """查看 RAG 索引规模、数据类型和 Embedding 启用状态。"""
    return rag.index_stats()


@app.post("/api/generate")
async def generate(
    product_name: str = Form(...),
    selling_points: str = Form(...),
    price: str = Form(""),
    poster_url: str = Form(""),
    poster: UploadFile = File(None),
    visitor: str = Depends(require_quota),
):
    poster_bytes = None
    if poster is not None:
        poster_bytes = await poster.read()

    result = run_pipeline(
        product_name=product_name,
        selling_points=selling_points,
        price=price,
        poster_bytes=poster_bytes,
        poster_url=poster_url or None,
    )
    # 生成成功后，把产品沉淀进知识库（供下次检索/补全）
    try:
        db.upsert_product(name=product_name, selling_points=selling_points, price=price)
    except Exception:
        pass
    quota.consume(visitor)
    return result


@app.post("/api/copywriting")
async def copywriting_only(
    product_name: str = Form(...),
    selling_points: str = Form(...),
    price: str = Form(""),
    visitor: str = Depends(require_quota),
):
    """只生成文案（不触发生图，速度快）。RAG 检索营销案例作为参照。"""
    product_context = rag.resolve_product_context(product_name)
    references = {}
    try:
        query = f"产品：{product_name}；卖点：{selling_points}；价格：{price}；任务：新品营销文案"
        references = rag.search_for_platforms(query, copywriting.PLATFORMS.keys(), top_k=3)
    except Exception:
        references = {}
    copies = copywriting.generate_copy(
        product_name,
        selling_points,
        price,
        references,
        product_context=product_context,
    )
    # 沉淀产品到知识库
    try:
        db.upsert_product(name=product_name, selling_points=selling_points, price=price)
    except Exception:
        pass
    quota.consume(visitor)
    return {
        "copywriting": copies,
        "references": references,
        "product_context": product_context,
    }


@app.post("/api/image")
async def image_only(
    product_name: str = Form(...),
    selling_points: str = Form(...),
    price: str = Form(""),
    poster_url: str = Form(""),
    poster: UploadFile = File(None),
    visitor: str = Depends(require_quota),
):
    """只生图（不生成文案）。返回图片 + 提示词，供后续多轮改图使用。"""
    product_context = rag.resolve_product_context(product_name)
    poster_bytes = None
    if poster is not None:
        poster_bytes = await poster.read()

    if poster_bytes or poster_url:
        parsed = vision.parse_poster(poster_bytes, poster_url or None)
    else:
        parsed = vision._mock_parse()

    prompt = image.build_prompt(parsed, product_name, selling_points, price, product_context)
    img = image.generate_image(prompt)
    try:
        db.upsert_product(name=product_name, selling_points=selling_points, price=price)
    except Exception:
        pass
    quota.consume(visitor)
    return {
        "parsed_prompt": parsed,
        "final_prompt": prompt,
        "image": img,
        "product_context": product_context,
    }


class ReviseRequest(BaseModel):
    original_prompt: str
    feedback: str


@app.post("/api/revise")
async def revise_image(req: ReviseRequest, visitor: str = Depends(require_quota)):
    """多轮改图：根据上一版提示词 + 用户修改意见，生成新提示词并重新出图。"""
    new_prompt = revise.revise_prompt(req.original_prompt, req.feedback)
    img = image.generate_image(new_prompt)
    quota.consume(visitor)
    return {"new_prompt": new_prompt, "image": img}


# v2 使用新增接口，旧 API 继续保留。
app.include_router(create_router(search, _product_hit_to_suggestion, require_quota))

# 托管合并版前端静态文件。
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    # 托管环境通过 PORT 环境变量注入端口，绑定 0.0.0.0
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
