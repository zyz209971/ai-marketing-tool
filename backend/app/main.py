import os
import base64
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

from .pipeline import run_pipeline
from .providers import revise, image, copywriting, vision
from .config import USE_MOCK
from . import db, rag

app = FastAPI(title="AI 营销素材生成工具")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    product_name: str
    selling_points: str
    price: str = ""
    poster_url: str = ""


@app.get("/api/health")
def health():
    return {"status": "ok", "mock": USE_MOCK}


@app.get("/api/lookup")
def lookup(name: str):
    """按产品名检索知识库，返回价格+卖点（供一键填入）。"""
    product = db.lookup_product(name)
    return {"found": product is not None, "product": product}


@app.get("/api/search")
def search(q: str):
    """模糊搜索产品，返回候选列表（供输入联想）。"""
    results = db.search_products(q)
    return {"results": results}


@app.get("/api/rag_search")
def rag_search(q: str, top_k: int = 3):
    """语义检索营销案例库（RAG），返回最相关的爆款/营销案例片段。"""
    results = rag.search_marketing(q, top_k=top_k)
    return {"query": q, "results": results}


@app.post("/api/generate")
async def generate(
    product_name: str = Form(...),
    selling_points: str = Form(...),
    price: str = Form(""),
    poster_url: str = Form(""),
    poster: UploadFile = File(None),
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
    return result


@app.post("/api/copywriting")
async def copywriting_only(
    product_name: str = Form(...),
    selling_points: str = Form(...),
    price: str = Form(""),
):
    """只生成文案（不触发生图，速度快）。RAG 检索营销案例作为参照。"""
    references = []
    try:
        hits = rag.search_marketing(f"{product_name} {selling_points}", top_k=3)
        references = [h["text"] for h in hits]
    except Exception:
        references = []
    copies = copywriting.generate_copy(product_name, selling_points, price, references)
    # 沉淀产品到知识库
    try:
        db.upsert_product(name=product_name, selling_points=selling_points, price=price)
    except Exception:
        pass
    return {"copywriting": copies, "references": references}


@app.post("/api/image")
async def image_only(
    product_name: str = Form(...),
    selling_points: str = Form(...),
    price: str = Form(""),
    poster_url: str = Form(""),
    poster: UploadFile = File(None),
):
    """只生图（不生成文案）。返回图片 + 提示词，供后续多轮改图使用。"""
    poster_bytes = None
    if poster is not None:
        poster_bytes = await poster.read()

    if poster_bytes or poster_url:
        parsed = vision.parse_poster(poster_bytes, poster_url or None)
    else:
        parsed = vision._mock_parse()

    prompt = image.build_prompt(parsed, product_name, selling_points, price)
    img = image.generate_image(prompt)
    try:
        db.upsert_product(name=product_name, selling_points=selling_points, price=price)
    except Exception:
        pass
    return {"parsed_prompt": parsed, "final_prompt": prompt, "image": img}


class ReviseRequest(BaseModel):
    original_prompt: str
    feedback: str


@app.post("/api/revise")
async def revise_image(req: ReviseRequest):
    """多轮改图：根据上一版提示词 + 用户修改意见，生成新提示词并重新出图。"""
    new_prompt = revise.revise_prompt(req.original_prompt, req.feedback)
    img = image.generate_image(new_prompt)
    return {"new_prompt": new_prompt, "image": img}


# 托管前端静态文件
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    # 托管环境通过 PORT 环境变量注入端口，绑定 0.0.0.0
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
