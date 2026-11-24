"""FastAPI contracts for operating imports, metrics, simulations and reviews."""
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import Field

from . import operations
from .operations import CampaignCreate, RiskCheck, SimulationRequest, StrictModel
from .v2 import require_access
from .marketing_agent.contracts import Offer


router = APIRouter(prefix="/api/operations", tags=["operations"], dependencies=[Depends(require_access)])


class ActivityEstimate(StrictModel):
    list_price_minor: int = Field(ge=0, le=10000000)
    variable_cost_minor: int = Field(ge=0, le=10000000)
    sales_quantity: int = Field(ge=0, le=100000)
    promotion_pairs: int | None = Field(default=None, ge=0, le=50000)
    marketing_spend_minor: int = Field(default=0, ge=0, le=10000000)
    baseline_contribution_minor: int | None = None
    offer: Offer


def _dates(start: date | None, end: date | None) -> None:
    if start and end and end <= start:
        raise HTTPException(422, "结束日期必须晚于开始日期，区间含开始、不含结束。")


@router.post("/imports/preview", status_code=201)
async def import_preview(
    brand_id: str = Form(...),
    data_type: str = Form("orders"),
    source: str = Form("user_upload"),
    synthetic: bool = Form(False),
    file: UploadFile = File(...),
):
    raw = await file.read(10*1024*1024+1)
    if len(raw) > 10*1024*1024:
        raise HTTPException(413, "单个经营 CSV 最大 10MB。")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(422, "经营数据仅支持 UTF-8 CSV。")
    try:
        return operations.preview_import(raw, brand_id, file.filename or "upload.csv", source, synthetic, data_type)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/imports/{import_id}/confirm")
def import_confirm(import_id: str):
    try:
        return operations.confirm_import(import_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/brands/{brand_id}/summary")
def operating_summary(brand_id: str, start: date | None = None, end: date | None = None):
    _dates(start, end)
    return operations.summary(brand_id, start, end)


@router.get("/brands/{brand_id}/trends")
def operating_trends(brand_id: str, start: date | None = None, end: date | None = None,
                     granularity: str = Query("day", pattern="^(day|week|month)$")):
    _dates(start, end)
    return operations.trends(brand_id, start, end, granularity)


@router.get("/brands/{brand_id}/products")
def operating_products(brand_id: str, start: date | None = None, end: date | None = None):
    _dates(start, end)
    return operations.product_analysis(brand_id, start, end)


@router.get("/brands/{brand_id}/dashboard")
def dashboard_source(brand_id: str, start: date | None = None, end: date | None = None,
                     granularity: str = Query("day", pattern="^(day|week|month)$")):
    _dates(start, end)
    return {"summary": operations.summary(brand_id, start, end),
            "trends": operations.trends(brand_id, start, end, granularity),
            "products": operations.product_analysis(brand_id, start, end)}


@router.post("/campaigns/estimate")
def estimate(request: ActivityEstimate):
    try:
        metrics = operations.activity_metrics(request.list_price_minor, request.variable_cost_minor,
                                              request.sales_quantity, request.offer,
                                              request.promotion_pairs, request.marketing_spend_minor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    metrics["incremental_vs_baseline_minor"] = (
        metrics["contribution_after_marketing_minor"]-request.baseline_contribution_minor
        if request.baseline_contribution_minor is not None else None)
    metrics["assumption"] = "活动测算是输入情景，不是需求预测或因果结论。"
    return metrics


@router.post("/campaigns/risk-check")
def risk_check(request: RiskCheck):
    return operations.check_risk(request)


@router.post("/campaigns/from-approved-strategy", status_code=201)
def campaign_from_approval(request: CampaignCreate):
    return operations.create_campaign(request)


@router.post("/campaigns/{campaign_id}/simulate", status_code=201)
def simulate(campaign_id: str, request: SimulationRequest):
    return operations.simulate(campaign_id, request)


@router.get("/simulations/{run_id}/orders.csv")
def download_simulation(run_id: str):
    content = operations.simulation_csv(run_id)
    return Response(content=content.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="simulation-{run_id}.csv"'})


@router.get("/campaigns/{campaign_id}/review")
def campaign_review(campaign_id: str):
    return operations.review(campaign_id)
