"""Shared contracts: money is integer CNY cents; date ranges are [start, end)."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Offer(Contract):
    type: Literal['second_cup_discount', 'percentage', 'none'] = 'second_cup_discount'
    pay_bps: int = Field(default=5000, ge=0, le=10000, strict=True)
    same_sku: Literal[True] = True
    same_order: Literal[True] = True
    repeat_per_pair: Literal[True] = True
    stackable: Literal[False] = False

    @model_validator(mode='before')
    @classmethod
    def price_default(cls, value):
        # Original-price sales cannot inherit the second-cup discount default.
        if isinstance(value,dict) and value.get('type')=='none' and 'pay_bps' not in value:
            return {**value,'pay_bps':10000}
        return value

    @model_validator(mode='after')
    def original_price(self):
        if self.type=='none' and self.pay_bps!=10000:
            raise ValueError('原价方案必须支付原价的100%。')
        return self


class Brief(Contract):
    task_kind: Literal['brand_setup','content','unit_economics','campaign'] = 'campaign'
    content_scope: Literal['product','brand'] = 'product'
    theme: str = Field(default='', max_length=1000)
    constraints: str = Field(default='', max_length=2000)
    promotion_pairs: int | None = Field(default=None, ge=0, le=50000, strict=True)
    assess_minimum: bool = True
    brand_id: str | None = Field(default=None, max_length=100)
    sku_id: str | None = Field(default=None, max_length=100)
    platform: Literal['xiaohongshu', 'douyin', 'wechat_official_account'] | None = None
    goal: str = Field(default='提升活动贡献收益', max_length=500)
    start_date: date | None = None
    end_date: date | None = None
    budget_minor: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    spend_minor: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    scenario_qty: int | None = Field(default=None, ge=1, le=100000, strict=True)
    roi_mode: Literal['scenario', 'unit_only'] = 'scenario'
    offer: Offer | None = None
    style: str = Field(default='自然、简洁，不夸大功效', max_length=1000)
    audience: str = Field(default='', max_length=500)
    variable_cost_override_minor: int | None = Field(default=None, ge=0, le=100000, strict=True)
    min_contribution_override_minor: int | None = Field(default=None, ge=0, le=100000, strict=True)

    @model_validator(mode='after')
    def dates_valid(self):
        if self.promotion_pairs is not None and self.scenario_qty is not None and 2*self.promotion_pairs>self.scenario_qty:
            raise ValueError('优惠两杯组数乘以2不能超过活动总杯数。')
        if self.start_date and self.end_date:
            days = (self.end_date - self.start_date).days
            if not 1 <= days <= 31:
                raise ValueError('活动区间含开始、不含结束，长度须为 1—31 天。')
        return self


class Decision(Contract):
    intent: Literal['plan', 'revise', 'question', 'knowledge'] = 'plan'
    patch: dict = Field(default_factory=dict)
    action: Literal['ask', 'tool', 'propose', 'revise', 'answer', 'knowledge']
    tool: Literal['get_sales_summary', 'get_business_constraints', 'evaluate_promotion'] | None = None
    reply: str = Field(default='', max_length=2000)
    revision_scope: Literal['title', 'body', 'all'] = 'body'


class StrategyExplanation(Contract):
    rationale: str = Field(min_length=1, max_length=1200)
    risks: list[str] = Field(default_factory=list, max_length=6)


class OfferProposal(Contract):
    offer: Offer
    rationale: str = Field(min_length=1, max_length=600)


class OfferProposals(Contract):
    candidates: list[OfferProposal] = Field(min_length=2, max_length=3)


class MessageInput(Contract):
    request_id: str = Field(min_length=8, max_length=100)
    text: str = Field(default='', max_length=5000)
    patch: dict = Field(default_factory=dict)
    expected_revision: int = Field(ge=0)


class CreateConversation(Contract):
    brand_id: str | None = Field(default=None, max_length=100)
    sku_id: str | None = Field(default=None, min_length=1, max_length=100)
    demo: bool = False


class InputChoice(Contract):
    id: str
    label: str
    patch: dict = Field(default_factory=dict)


class InputRequest(Contract):
    id: str
    task_id: str
    fields: list[str]
    question: str
    reason: str
    choices: list[InputChoice] = Field(default_factory=list)
    allow_free_text: bool = True
    attachment_id: str | None = None
    questions: list[dict] = Field(default_factory=list, max_length=3)


class AnswerInput(Contract):
    request_id: str = Field(min_length=8, max_length=100)
    expected_revision: int = Field(ge=0)
    question_id: str
    choice_id: str | None = None
    text: str = Field(default='', max_length=5000)
    answers: dict[str, dict] = Field(default_factory=dict, max_length=3)


class RememberStyleInput(Contract):
    expected_revision: int = Field(ge=0)


class AttachmentConfirm(Contract):
    expected_revision: int = Field(ge=0)
    knowledge: dict | None = None
    accepted_conflicts: list[str] = Field(default_factory=list,max_length=500)


class ConfirmInput(Contract):
    request_id: str = Field(min_length=8, max_length=100)
    strategy_id: str
    strategy_version: int = Field(ge=1)
    expected_revision: int = Field(ge=0)


class MissingField(Contract):
    path: str
    reason: str
    blocks: list[str]


class ToolResult(Contract):
    schema_version: Literal['1.0'] = '1.0'
    request_id: str
    tool: str
    status: Literal['ok', 'needs_data', 'error']
    data_kind: Literal['synthetic', 'user_provided'] = 'synthetic'
    snapshot_id: str
    data_version: str = 'milk-tea-demo-v1'
    method_version: str = 'promotion-v2-explicit-pairs'
    as_of: str = '2026-11-15'
    result: dict
    missing_fields: list[MissingField] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    error: dict | None = None


class SalesRequest(Contract):
    store_id: Literal['demo-store'] = 'demo-store'
    brand_id: str | None = None
    sku_id: str | None = None


class ConstraintsRequest(Contract):
    store_id: Literal['demo-store'] = 'demo-store'
    brand_id: str | None = None
    sku_id: str


class EvaluationRequest(Contract):
    store_id: Literal['demo-store'] = 'demo-store'
    brief: Brief


class SalesMetric(Contract):
    sku_id: str
    name: str
    previous_qty: int | None
    current_qty: int | None
    change_ratio: float | None
    current_revenue_minor: int | None
    daily_baseline_qty: float | None


class SalesData(Contract):
    previous_period: list[str]
    current_period: list[str]
    metrics: list[SalesMetric]


class ConstraintsData(Contract):
    sku_id: str
    list_price_minor: int | None
    variable_cost_minor: int | None
    min_contribution_minor: int | None
    daily_capacity: int | None
    fee_bps: Literal[0] = 0
    currency: Literal['CNY'] = 'CNY'


class CandidateOffer(Contract):
    pay_bps: int
    feasible: bool
    average_contribution_minor: float
    incremental_contribution_minor: int | None = None


class EvaluationData(Contract):
    feasible: bool | None
    violations: list[str]
    pair_revenue_minor: int | None = None
    pair_contribution_minor: int | None = None
    average_contribution_minor: float | None = None
    scenario_qty: int | None = None
    scenario_revenue_minor: int | None = None
    scenario_contribution_minor: int | None = None
    baseline_qty: int | None = None
    baseline_contribution_minor: int | None = None
    incremental_contribution_minor: int | None = None
    incremental_roi: float | None = None
    roi_reason: str | None = None
    min_average_price_minor: int | None = None
    min_offer_pay_bps: int | None = None
    candidates: list[CandidateOffer] = Field(default_factory=list)
    currency: Literal['CNY'] = 'CNY'


RESULT_TYPES = {'get_sales_summary': SalesData, 'get_business_constraints': ConstraintsData,
                'evaluate_promotion': EvaluationData}


def validate_tool(result: dict) -> dict:
    value = ToolResult.model_validate(result)
    RESULT_TYPES[value.tool].model_validate(value.result)
    return value.model_dump(mode='json')
