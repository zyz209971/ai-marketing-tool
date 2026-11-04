"""新增 v2 接口；旧接口、RAG 索引和模型配置继续使用原实现。"""
import base64
import binascii
import logging
import re
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from . import db, quota, rag
from .config import APP_ACCESS_KEY, USE_MOCK
from .providers import campaign, image, revise, vision

logger = logging.getLogger(__name__)
Platform = Literal["xiaohongshu", "douyin", "wechat_official_account"]


class Brand(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    positioning: str = ""
    style: str = ""


class Product(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=200)
    price: str | None = None
    selling_points: list[str] = Field(min_length=1, max_length=50)


class Campaign(BaseModel):
    brand: Brand
    marketing_goal: Literal["new_product", "promotion", "brand_awareness", "holiday"]
    products: list[Product] = Field(default_factory=list, max_length=10)
    platforms: list[Platform] = Field(min_length=1, max_length=3)
    generation_mode: Literal["text_only", "text_and_image", "image_only"] = "text_only"
    product_strategy: Literal["merged", "separate"] = "merged"
    theme: str = ""
    promotion_rules: str = ""
    activity_time: str = ""
    additional_selling_points: str = ""
    style_requirements: str = ""
    reference_poster: str = Field(default="", max_length=5600000)

    @model_validator(mode="after")
    def validate_goal(self):
        if self.marketing_goal in ("new_product", "promotion") and not self.products:
            raise ValueError("新品推广和促销需要选择产品")
        if self.marketing_goal == "promotion" and not (self.promotion_rules.strip() and self.activity_time.strip()):
            raise ValueError("促销需要优惠规则和活动时间")
        if self.marketing_goal in ("brand_awareness", "holiday") and not self.theme.strip():
            raise ValueError("品牌曝光和节日活动需要主题")
        if len({p.id for p in self.products}) != len(self.products):
            raise ValueError("产品标识不能重复")
        return self


class Content(BaseModel):
    id: str = ""
    platform: Platform
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    summary: str = ""
    hashtags: list[str] = Field(default_factory=list)
    product_label: str = ""
    product_ids: list[str] = Field(default_factory=list)


class ImageRequest(BaseModel):
    campaign: Campaign
    content: Content
    purpose: Literal["post_image", "article_cover"] = "post_image"


class RewriteRequest(Content):
    instruction: str = Field(min_length=1, max_length=5000)


class ReviseImageRequest(BaseModel):
    original_prompt: str = Field(min_length=1, max_length=20000)
    feedback: str = Field(min_length=1, max_length=5000)


class SearchRequest(BaseModel):
    client_brand_id: str = ""
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=10, ge=1, le=20)
    semantic: bool = False


def require_access(x_access_key: str = Header(default="")):
    if APP_ACCESS_KEY and not secrets.compare_digest(x_access_key.encode(), APP_ACCESS_KEY.encode()):
        raise HTTPException(status_code=403, detail="请先输入正确的访问密码。")


def _image_response(img, prompt, parsed=None):
    if img.get("error"):
        # 旧图片 provider 失败时会带占位图；v2 必须明确报错，不能当作真实成功。
        logger.warning("图片服务返回失败")
        raise HTTPException(status_code=502, detail="图片服务生成失败，请检查后端生图配置或稍后重试。")
    if not (img.get("url") or img.get("base64")):
        raise HTTPException(status_code=502, detail="图片服务未返回图片。")
    return {"status": "succeeded", "image": img, "final_prompt": prompt,
            "parsed_prompt": parsed or {}, "mock": bool(img.get("mock"))}


def create_router(legacy_search, hit_to_suggestion, quota_dependency):
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(require_access)])

    @router.post("/copywriting")
    def generate_copy(req: Campaign, visitor: str = Depends(quota_dependency)):
        try:
            contents = campaign.generate(req.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        except Exception as exc:
            # 把真实异常（401/404/模型不存在/连接超时等）写进日志，方便排查。
            logger.warning("新版文案服务调用失败：%s", exc, exc_info=True)
            raise HTTPException(status_code=502, detail="文案服务调用失败，请检查后端文字模型配置或稍后重试。") from None
        for product in req.products:
            try:
                db.upsert_product(product.name, "、".join(product.selling_points), product.price or "", brand=req.brand.name)
            except Exception:
                logger.warning("本次产品资料未能沉淀到数据库")
        quota.consume(visitor)
        return {"status": "succeeded", "contents": contents, "mock": USE_MOCK}

    @router.post("/copywriting/rewrite")
    def rewrite_copy(req: RewriteRequest, visitor: str = Depends(quota_dependency)):
        if not req.instruction.strip():
            raise HTTPException(status_code=422, detail="修改意见不能为空。")
        try:
            content = campaign.rewrite(req.model_dump(exclude={"instruction"}), req.instruction)
        except Exception as exc:
            logger.warning("新版文案改写失败：%s", exc, exc_info=True)
            raise HTTPException(status_code=502, detail="文案改写失败，请检查文字模型配置或稍后重试。") from None
        quota.consume(visitor)
        return {"status": "succeeded", "content": content, "mock": USE_MOCK}

    @router.post("/products/search")
    def search_products(req: SearchRequest):
        if not req.query.strip():
            raise HTTPException(status_code=422, detail="搜索内容不能为空。")
        # 默认调用当前 SQL + 本地 RAG 搜索；语义检索由用户明确勾选才调用 embedding。
        if req.semantic:
            hits = rag.search_products(req.query, top_k=req.limit, use_vector=True)
            rows = [hit_to_suggestion(hit) for hit in hits]
        else:
            rows = legacy_search(req.query)["results"]
        products = []
        for index, row in enumerate(rows[:req.limit]):
            points = row.get("selling_points") or ""
            products.append({**row, "id": str(row.get("document_id") or f"search_{index}"),
                             "selling_points": re.split(r"[、，,]", points) if isinstance(points, str) and points else points if isinstance(points, list) else []})
        return {"products": products, "semantic": req.semantic}

    @router.post("/images")
    def generate_image(req: ImageRequest, visitor: str = Depends(quota_dependency)):
        selected = req.campaign.products
        if req.content.product_ids:
            selected = [p for p in selected if p.id in req.content.product_ids]
            if not selected:
                raise HTTPException(status_code=422, detail="配图对应的产品不在本次创作中。")
        elif req.campaign.product_strategy == "separate":
            selected = [p for p in selected if p.name == req.content.product_label]
            if not selected and req.campaign.products:
                raise HTTPException(status_code=422, detail="请重新生成文案后再为单款产品配图。")
        reference = req.campaign.reference_poster
        parsed = {"scene": "简洁背景", "composition": "主体清晰，适合社交平台展示", "style": req.campaign.style_requirements or "自然简洁",
                  "lighting": "柔和自然光", "color": "协调配色", "text_zone": "预留标题位置"}
        if reference:
            if not re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+", reference):
                raise HTTPException(status_code=422, detail="参考海报仅支持 PNG、JPEG、WebP。")
            try:
                raw = base64.b64decode(reference.split(",", 1)[1], validate=True)
            except (ValueError, binascii.Error):
                raise HTTPException(status_code=422, detail="参考海报格式不正确。") from None
            if len(raw) > 4 * 1024 * 1024:
                raise HTTPException(status_code=422, detail="参考海报不能超过 4MB。")
            parsed = vision.parse_poster(None, reference)
        name = "、".join(p.name for p in selected) or req.campaign.brand.name
        points = "；".join(p.name + "：" + "、".join(p.selling_points) + ("，价格：" + p.price if p.price else "") for p in selected)
        context = campaign.product_context(selected[0].model_dump(), req.campaign.brand.name) if len(selected) == 1 else None
        prompt = image.build_prompt(parsed, name, points or req.campaign.brand.description, "", context)
        prompt += "；本次品牌：" + req.campaign.brand.name + "；营销目的：" + campaign.GOALS[req.campaign.marketing_goal]
        for label, value in [("主题", req.campaign.theme), ("优惠规则", req.campaign.promotion_rules), ("活动时间", req.campaign.activity_time),
                             ("补充卖点", req.campaign.additional_selling_points), ("风格要求", req.campaign.style_requirements)]:
            if value:
                prompt += "；" + label + "：" + value
        prompt += "；配图用途：" + ("公众号文章封面" if req.purpose == "article_cover" else "社交平台配图")
        prompt += "；内容主题：" + req.content.title + "；文案参考（不需要把全文绘入图片）：" + req.content.body[:1000]
        response = _image_response(image.generate_image(prompt), prompt, parsed)
        if not response["mock"]:
            quota.consume(visitor)
        return response

    @router.post("/images/revise")
    def revise_image(req: ReviseImageRequest, visitor: str = Depends(quota_dependency)):
        prompt = revise.revise_prompt(req.original_prompt, req.feedback)
        response = _image_response(image.generate_image(prompt), prompt)
        if not response["mock"]:
            quota.consume(visitor)
        return response

    return router
