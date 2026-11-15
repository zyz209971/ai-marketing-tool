import os
import base64
import asyncio
from fastapi import FastAPI, File, Form, UploadFile, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

from .pipeline import run_pipeline
from .providers import revise, image, copywriting, vision, shop_analysis, activity_plan, keeper_memory
from .config import USE_MOCK, APP_ACCESS_KEY, ADMIN_RESET_KEY
from . import db, rag, quota

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


class ShopAnalysisRequest(BaseModel):
    """经营分析请求：产品明细列表（可空，空则用示例数据）。"""
    products: list[dict] = []


class ActivityPlanRequest(BaseModel):
    """活动策划请求。"""
    goal: str
    product_name: str = ""
    product_cost: float = 4.5
    product_price: float = 12.0


class ShopkeeperRequest(BaseModel):
    """营销店长主 Agent 请求：商家一句话需求，路由到对应子 Agent。

    - products: 商家拖入表格解析出的产品明细（可选，喂给经营分析）
    - ref_image: 参考海报图片的 base64（可选，用于海报反推）
    """
    message: str
    products: list[dict] = []
    ref_image: str = ""


class KeeperPosterRequest(BaseModel):
    """按定稿活动方案画海报。"""
    plan_name: str
    plan_desc: str = ""
    product_name: str = ""
    price: str = ""


@app.get("/api/health")
def health():
    return {"status": "ok", "mock": USE_MOCK, "need_key": bool(APP_ACCESS_KEY)}


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
    quota.consume(visitor)
    return {"copywriting": copies, "references": references}


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
    quota.consume(visitor)
    return {"parsed_prompt": parsed, "final_prompt": prompt, "image": img}


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


@app.post("/api/shop_analysis")
def shop_analysis_api(req: ShopAnalysisRequest):
    """经营分析 Agent：热销/滞销 + 归因 + 对策。"""
    products = req.products if req.products else shop_analysis.SAMPLE_PRODUCTS
    result = shop_analysis.analyze_products(products)
    result["is_sample"] = not req.products
    return result


@app.post("/api/activity_plan")
def activity_plan_api(req: ActivityPlanRequest):
    """活动策划 Agent：策划方案 + 测算回本。"""
    return activity_plan.plan_activity(
        goal=req.goal,
        product_name=req.product_name,
        product_cost=req.product_cost,
        product_price=req.product_price,
    )


@app.post("/api/shopkeeper")
def shopkeeper_route(req: ShopkeeperRequest):
    """营销店长主 Agent：根据商家一句话需求，路由到对应子 Agent。

    简单的关键词路由（确定性代码，不走 LLM）：
    - 提到「活动/促销/回本/清库存/拉新」→ 活动策划
    - 提到「分析/滞销/热销/卖得/诊断」→ 经营分析
    - 提到「文案」→ 文案（占位）
    - 提到「海报/图片」→ 海报（占位）
    """
    msg = req.message.strip()
    if not msg:
        return {"agent": "unknown", "reply": "请告诉我你想做什么，例如：帮我看看哪些产品滞销，或帮我策划一个清库存活动。"}

    activity_kw = ["活动", "促销", "回本", "清库存", "拉新", "冲销量", "满减", "买一送一", "折扣", "定价"]
    analysis_kw = ["分析", "滞销", "热销", "卖得", "诊断", "经营", "生意", "卖不动", "库存"]
    copy_kw = ["文案", "种草", "朋友圈", "推文"]
    poster_kw = ["海报", "图片", "图"]

    if any(k in msg for k in activity_kw):
        return {"agent": "activity_plan", "reply": "好的，我来帮你策划活动并测算回本。", "goal": msg}
    if any(k in msg for k in analysis_kw):
        return {"agent": "shop_analysis", "reply": "好的，我来帮你分析店内经营情况。"}
    if any(k in msg for k in copy_kw):
        return {"agent": "copywriting", "reply": "文案生成能力开发中，敬请期待。"}
    if any(k in msg for k in poster_kw):
        return {"agent": "image", "reply": "海报生成能力开发中，敬请期待。"}
    return {"agent": "unknown", "reply": "我还没理解你的需求。可以试试：'帮我看看哪些产品滞销' 或 '帮我策划一个清库存活动'。"}


@app.post("/api/keeper_chat")
async def keeper_chat(req: ShopkeeperRequest):
    """对话式营销店长：并行调度经营分析 + 活动策划两个 Agent。

    返回结构：
    - reply: 店长的开场回复
    - agents: 本次实际调度的 Agent 列表
    - analysis: 经营分析结果（若有）
    - activity: 活动策划结果（若有）
    """
    msg = req.message.strip()
    if not msg:
        return {"reply": "请告诉我你想做什么，例如：帮我看看哪些产品滞销，或帮我策划一个清库存活动。", "agents": []}

    activity_kw = ["活动", "促销", "回本", "清库存", "拉新", "冲销量", "满减", "买一送一", "折扣", "定价", "策划"]
    analysis_kw = ["分析", "滞销", "热销", "卖得", "诊断", "经营", "生意", "卖不动", "库存", "哪些", "什么"]
    poster_kw = ["海报", "图片", "图", "参考", "风格"]

    need_activity = any(k in msg for k in activity_kw)
    need_analysis = any(k in msg for k in analysis_kw)
    # 拖了参考图，或提到海报/参考 → 触发海报反推
    need_poster = bool(req.ref_image) or any(k in msg for k in poster_kw)
    # 拖了表格 → 强制走经营分析（用商家真实数据）
    if req.products:
        need_analysis = True

    # 未命中任何任务关键词：先当「追问」处理——基于上一轮上下文用 LLM 回答
    if not need_analysis and not need_activity and not need_poster:
        follow = keeper_memory.answer_followup(msg)
        if follow.get("reply"):
            return {
                "reply": follow["reply"],
                "plan": ["· 结合刚才的方案和数据分析你的追问"],
                "agents": [],
                "is_followup": True,
            }
        return {"reply": "我还没理解你的需求。可以试试：'帮我看看哪些产品滞销' 或 '帮我策划一个清库存活动'。", "agents": []}

    # 默认：如果只提了活动，也顺带跑经营分析（找出滞销品作为活动对象）；如果只提分析，只跑分析
    agents = []
    tasks = {}

    # 经营分析的数据源：优先用商家上传的表格，否则用示例数据
    analysis_products = req.products if req.products else shop_analysis.SAMPLE_PRODUCTS

    async def _run_analysis():
        return shop_analysis.analyze_products(analysis_products)

    async def _run_activity():
        return activity_plan.plan_activity(goal=msg)

    async def _run_poster():
        # 参考海报反推：解析参考图 → 生成新海报
        try:
            img_bytes = base64.b64decode(req.ref_image) if req.ref_image else None
        except Exception:
            img_bytes = None
        parsed = vision.parse_poster(img_bytes, None)
        prompt = image.build_prompt(parsed, product_name="招牌珍珠奶茶", selling_points="校园爆款奶茶", price="12元")
        img = image.generate_image(prompt)
        return {"parsed": parsed, "prompt": prompt, "image": img}

    if need_analysis:
        agents.append("shop_analysis")
        tasks["shop_analysis"] = asyncio.create_task(_run_analysis())

    if need_activity:
        agents.append("activity_plan")
        tasks["activity_plan"] = asyncio.create_task(_run_activity())

    if need_poster:
        agents.append("poster")
        tasks["poster"] = asyncio.create_task(_run_poster())

    # 如果都没触发，给个引导
    if not agents:
        return {"reply": "我还没理解你的需求。可以试试：'帮我看看哪些产品滞销' 或 '帮我策划一个清库存活动'。", "agents": []}

    # 并行等待所有 Agent 完成
    results = {}
    for name, task in tasks.items():
        try:
            results[name] = await task
        except Exception as e:
            results[name] = {"error": str(e)}

    # 店长的「思考链路」：描述怎么拆解任务、派给谁并行
    plan = []
    if "shop_analysis" in agents:
        src = "你上传的表格" if req.products else "店内"
        plan.append(f"· 让「经营分析 Agent」用{src}数据盘点热销/滞销，定位问题品")
    if "activity_plan" in agents:
        plan.append("· 让「活动策划 Agent」出方案并测算回本")
    if "poster" in agents:
        plan.append("· 让「海报生成 Agent」反推参考图风格，生成新海报")
    if len(agents) > 1:
        plan.insert(0, f"你的需求要 {len(agents)} 个 Agent 同时协作，我让它们并行开工：")
    else:
        plan.insert(0, "我拆解了一下你的需求：")

    if len(agents) > 1:
        reply = "这几个任务我并行派下去了，都在同步推进，马上给你结果。"
    else:
        reply = "好的，我已经安排下去了，稍等。"
        if "shop_analysis" in agents:
            reply = "好的，我让经营分析 Agent 帮你盘点哪些好卖、哪些滞销，稍等。"
        elif "activity_plan" in agents:
            reply = "好的，我让活动策划 Agent 帮你出方案并测算回本，稍等。"
        elif "poster" in agents:
            reply = "好的，我让海报 Agent 分析你的参考图并生成新海报，稍等。"
        elif "activity_plan" in agents:
            reply = "好的，我让活动策划 Agent 帮你出方案并测算回本，稍等。"

    # 保存本轮上下文，供下一轮追问使用（对话记忆）
    keeper_memory.save_context(msg, agents, results.get("shop_analysis"), results.get("activity_plan"))

    return {
        "reply": reply,
        "plan": plan,
        "agents": agents,
        "analysis": results.get("shop_analysis"),
        "activity": results.get("activity_plan"),
        "poster": results.get("poster"),
    }


@app.post("/api/keeper_poster")
def keeper_poster(req: KeeperPosterRequest):
    """按定稿活动方案画海报：复用现有生图能力。"""
    selling_points = req.plan_desc or req.plan_name
    prompt = image.build_prompt(
        parsed={},  # 用默认模板
        product_name=req.product_name or "招牌珍珠奶茶",
        selling_points=f"{req.plan_name}：{selling_points}",
        price=req.price or "",
    )
    img = image.generate_image(prompt)
    return {"prompt": prompt, "image": img, "plan_name": req.plan_name}


# 托管前端静态文件
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    # 托管环境通过 PORT 环境变量注入端口，绑定 0.0.0.0
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
