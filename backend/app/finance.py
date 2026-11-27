"""测算引擎（口径校准版）：茶饮单杯毛利 / 净利 / 贡献 / 回本周期 / 保本营业额。

本版校准了原「补给赞奶茶店测算表」的口径错误，核心原则：

【口径铁律】
1. 毛利（Gross Profit）= 收入 − 变动成本
   变动成本只含：食材、包材、（外卖）平台扣点。
   这些是「多卖一杯就多花一杯」的成本。

2. 净利（Net Profit）= 毛利 − 固定/期间成本
   固定成本含：人力、能耗、管理费（按收入比例分摊）、月租金。
   这些是「卖不卖都要花」的成本，绝不能混进单杯毛利。

3. 贡献（Contribution）≈ 毛利口径，用于「营销投入前/后」的活动测算。
   活动贡献（营销投入前）= 活动净销售收入 − 可归属变动成本
   活动贡献（营销投入后）= 活动贡献（前）− 活动营销投入

4. 单位贡献非正、分母为零 → 返回 needs_data / 无有效结果，
   绝不输出负保本量、无穷或把 600÷200 硬当 ROI。

【数值规则】
- 金额一律用「分」（整数）存储与计算，用 Decimal 避免浮点误差。
- 比例用百分比整数（如 10 表示 10%），内部 /100 使用 Decimal。

【三态返回】
- ok          ：计算完整
- needs_data  ：缺少必要数据（如无成本），返回已算部分 + missing_fields
- failed      ：输入非法（如空时间窗、负销量），不返回数值结论
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

CENT = Decimal("0.01")  # 分 → 元


def yuan(x) -> Decimal:
    """把「元」字符串/数字转成 Decimal。"""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def fen_to_yuan(fen: int) -> str:
    """把「分」整数转成带两位小数的「元」字符串（用于展示）。"""
    return str(Decimal(fen) / Decimal("100"))


def _pct(p: Decimal) -> Decimal:
    """百分比整数 → 比例 Decimal。如 10 → 0.10。"""
    return p / Decimal("100")


@dataclass
class CostRatio:
    """按收入比例分摊的「期间/固定」成本项（百分比整数）。"""
    platform: int = 10          # 平台扣点 %（仅外卖，属变动成本，但单独记便于拆分）
    labor: int = 15             # 人力成本 %
    energy: int = 3             # 能耗 %
    logistics: int = 0          # 物流成本 %
    depreciation: int = 0       # 折旧摊销 %
    management: int = 2         # 管理费 %


@dataclass
class SkuInput:
    """单款 SKU 的基础参数（商家填写，金额单位：元）。"""
    name: str = ""
    online_price: float = 18.0          # 外卖价格
    offline_price: float = 16.0         # 线下价格
    self_marketing_ratio: float = 0.18  # 自营销比例（外卖让利/补贴占比）
    online_volume: float = 0.0          # 外卖月销量（杯）
    offline_volume: float = 0.0         # 线下月销量（杯）
    ingredient_cost: float = 0.0        # 食材成本（每杯）
    packing_cost: float = 0.0           # 包材成本（每杯）
    ratios: CostRatio = field(default_factory=CostRatio)


@dataclass
class StoreInput:
    """店铺级固定成本与投入（金额单位：元）。"""
    monthly_rent: float = 15000.0       # 月租金
    renovation_cost: float = 150000.0   # 装修总成本
    equipment_cost: float = 80000.0     # 设备总成本
    annual_rent: float = 180000.0       # 年度租金
    other_monthly_fixed: float = 0.0    # 其他月固定成本（可选）


def _round_money(d: Decimal) -> Decimal:
    """金额四舍五入到分。"""
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def calc_sku(s: SkuInput) -> dict:
    """计算单杯（SKU）的毛利与净利。

    返回单杯口径：
    - 外卖/线下实际收入
    - 外卖/线下毛利（收入 − 变动成本）
    - 外卖/线下净利（毛利 − 分摊固定成本）
    """
    try:
        op = yuan(s.online_price)
        fp = yuan(s.offline_price)
        ing = yuan(s.ingredient_cost)
        pk = yuan(s.packing_cost)
        smr = yuan(s.self_marketing_ratio)
    except InvalidOperation:
        return _failed("价格或成本不是合法数字")

    if op < 0 or fp < 0 or ing < 0 or pk < 0:
        return _failed("价格/成本不能为负")

    # 外卖实际收入（扣除自营销让利）
    online_real = op * (Decimal("1") - smr)

    # 变动成本
    platform_fee = online_real * _pct(yuan(s.ratios.platform))  # 平台扣点（外卖）
    online_var_cost = ing + pk + platform_fee
    offline_var_cost = ing + pk

    # 毛利（收入 − 变动成本）
    online_gross = online_real - online_var_cost
    offline_gross = fp - offline_var_cost

    # 固定/期间成本（按收入比例分摊，毛利之后才扣）
    online_fixed = online_real * (
        _pct(yuan(s.ratios.labor)) + _pct(yuan(s.ratios.energy))
        + _pct(yuan(s.ratios.logistics)) + _pct(yuan(s.ratios.depreciation))
        + _pct(yuan(s.ratios.management))
    )
    offline_fixed = fp * (
        _pct(yuan(s.ratios.labor)) + _pct(yuan(s.ratios.energy))
        + _pct(yuan(s.ratios.logistics)) + _pct(yuan(s.ratios.depreciation))
        + _pct(yuan(s.ratios.management))
    )

    online_net = online_gross - online_fixed
    offline_net = offline_gross - offline_fixed

    def margin(profit, revenue) -> Decimal:
        if revenue == 0:
            return Decimal("0")
        return _round_money(profit / revenue * Decimal("100"))

    return {
        "status": "ok",
        "name": s.name,
        "online_real_income": _round_money(online_real),
        "offline_real_income": _round_money(fp),
        "online_gross": _round_money(online_gross),
        "offline_gross": _round_money(offline_gross),
        "online_gross_margin": margin(online_gross, online_real),
        "offline_gross_margin": margin(offline_gross, fp),
        "online_net": _round_money(online_net),
        "offline_net": _round_money(offline_net),
        "online_net_margin": margin(online_net, online_real),
        "offline_net_margin": margin(offline_net, fp),
    }


def calc_store(sku_list: list[SkuInput], store: StoreInput) -> dict:
    """店铺级汇总：收入 / 变动成本 / 毛利 / 净利 / 回本 / 保本。"""
    if not sku_list:
        return _failed("sku 列表为空")

    total_online_income = Decimal("0")
    total_offline_income = Decimal("0")
    total_ingredient = Decimal("0")
    total_packing = Decimal("0")
    total_platform = Decimal("0")
    total_online_gross = Decimal("0")
    total_offline_gross = Decimal("0")

    per_sku = []
    for s in sku_list:
        d = calc_sku(s)
        per_sku.append(d)
        if d["status"] != "ok":
            continue

        online_income = yuan(s.online_price) * (Decimal("1") - yuan(s.self_marketing_ratio)) * yuan(s.online_volume)
        offline_income = yuan(s.offline_price) * yuan(s.offline_volume)

        total_online_income += online_income
        total_offline_income += offline_income
        total_ingredient += yuan(s.ingredient_cost) * (yuan(s.online_volume) + yuan(s.offline_volume))
        total_packing += yuan(s.packing_cost) * (yuan(s.online_volume) + yuan(s.offline_volume))
        total_platform += online_income * _pct(yuan(s.ratios.platform))
        total_online_gross += d["online_gross"] * yuan(s.online_volume)
        total_offline_gross += d["offline_gross"] * yuan(s.offline_volume)

    total_revenue = total_online_income + total_offline_income
    total_gross = total_online_gross + total_offline_gross

    if total_revenue <= 0:
        return _failed("总收入为零或负")

    # 期间成本（按收入比例分摊的固定成本） + 月租金
    total_labor = total_revenue * _pct(yuan(sku_list[0].ratios.labor))
    total_energy = total_revenue * _pct(yuan(sku_list[0].ratios.energy))
    total_logistics = total_revenue * _pct(yuan(sku_list[0].ratios.logistics))
    total_depreciation = total_revenue * _pct(yuan(sku_list[0].ratios.depreciation))
    total_management = total_revenue * _pct(yuan(sku_list[0].ratios.management))
    total_period = total_labor + total_energy + total_logistics + total_depreciation + total_management

    monthly_fixed = yuan(store.monthly_rent) + yuan(store.other_monthly_fixed)

    monthly_net = total_gross - total_period - monthly_fixed

    combined_gross_margin = _round_money(total_gross / total_revenue * Decimal("100"))
    combined_net_margin = _round_money(monthly_net / total_revenue * Decimal("100"))

    total_invest = yuan(store.renovation_cost) + yuan(store.equipment_cost) + yuan(store.annual_rent)

    # 回本周期（月）
    payback_months = None
    payback_status = "ok"
    if monthly_net <= 0:
        payback_status = "needs_data"
        payback_months = None  # 净利非正，回本无有效结果
    else:
        payback_months = _round_money(total_invest / monthly_net)

    # 保本营业额 = 月固定成本 / 综合毛利率
    # 注意：combined_gross_margin 已是百分数（如 71.67 表示 71.67%），
    # 需先 /100 转成比例再作除数。
    breakeven_revenue = None
    breakeven_status = "ok"
    if combined_gross_margin <= 0:
        breakeven_status = "needs_data"
        breakeven_revenue = None
    else:
        breakeven_revenue = _round_money(monthly_fixed / (combined_gross_margin / Decimal("100")))

    return {
        "status": "ok" if (payback_status == "ok" and breakeven_status == "ok") else "needs_data",
        "missing_fields": (
            []
            if (payback_status == "ok" and breakeven_status == "ok")
            else [f for f, st in [("回本周期（净利非正）", payback_status), ("保本营业额（毛利率非正）", breakeven_status)] if st != "ok"]
        ),
        "total_online_income": _round_money(total_online_income),
        "total_offline_income": _round_money(total_offline_income),
        "total_revenue": _round_money(total_revenue),
        "total_ingredient": _round_money(total_ingredient),
        "total_packing": _round_money(total_packing),
        "total_platform": _round_money(total_platform),
        "total_labor": _round_money(total_labor),
        "total_energy": _round_money(total_energy),
        "total_management": _round_money(total_management),
        "total_period_cost": _round_money(total_period),
        "monthly_fixed": _round_money(monthly_fixed),
        "total_gross": _round_money(total_gross),
        "online_gross": _round_money(total_online_gross),
        "offline_gross": _round_money(total_offline_gross),
        "monthly_net": _round_money(monthly_net),
        "combined_gross_margin": combined_gross_margin,
        "combined_net_margin": combined_net_margin,
        "total_invest": _round_money(total_invest),
        "payback_months": payback_months,
        "breakeven_revenue": breakeven_revenue,
        "per_sku": per_sku,
    }


def calc_activity(activity: dict) -> dict:
    """测算一个活动方案：营销投入前/后贡献 + 是否回本。

    activity 字段（金额单位：元）：
    - name: 活动名
    - target_sku: 目标产品（SkuInput）
    - discount: 折扣让利比例（如 0.5 表示第二杯半价等效让利）
    - expected_volume: 预计活动期间销量（杯）
    - budget: 活动营销投入（物料/投放，单位元）
    - online_ratio: 外卖占比（0-1）
    """
    sku = activity.get("target_sku")
    if sku is None:
        return _failed("缺少目标产品")

    try:
        discount = yuan(activity.get("discount", 0.5))
        expected_volume = yuan(activity.get("expected_volume", 0))
        budget = yuan(activity.get("budget", 0.0))
        online_ratio = yuan(activity.get("online_ratio", 0.4))
    except InvalidOperation:
        return _failed("活动参数不是合法数字")

    if expected_volume <= 0:
        return _failed("活动销量必须为正")

    online_vol = expected_volume * online_ratio
    offline_vol = expected_volume * (Decimal("1") - online_ratio)

    # 打折后价格
    online_price = yuan(sku.online_price) * (Decimal("1") - discount)
    offline_price = yuan(sku.offline_price) * (Decimal("1") - discount)

    act_sku = SkuInput(
        name=sku.name,
        online_price=float(online_price),
        offline_price=float(offline_price),
        self_marketing_ratio=sku.self_marketing_ratio,
        online_volume=float(online_vol),
        offline_volume=float(offline_vol),
        ingredient_cost=sku.ingredient_cost,
        packing_cost=sku.packing_cost,
        ratios=sku.ratios,
    )

    d = calc_sku(act_sku)
    if d["status"] != "ok":
        return d

    # 单杯毛利（活动口径，含外卖平台扣点，不含固定成本分摊——贡献口径）
    unit_gross = d["online_gross"] * online_ratio + d["offline_gross"] * (Decimal("1") - online_ratio)
    total_gross = unit_gross * expected_volume

    # 营销投入前贡献 = 总毛利（此时不含营销投入）
    contribution_before = total_gross
    # 营销投入后贡献 = 营销投入前贡献 − 营销投入
    contribution_after = contribution_before - budget

    # 回本所需销量（杯）：让贡献刚好覆盖营销投入
    breakeven_volume = None
    if unit_gross <= 0:
        # 单位贡献非正 → 无有效结果
        breakeven_volume = None
        breakeven_status = "needs_data"
    else:
        breakeven_volume = _round_money(budget / unit_gross)
        breakeven_status = "ok"

    return {
        "status": "ok" if breakeven_status == "ok" else "needs_data",
        "missing_fields": [] if breakeven_status == "ok" else ["单位贡献非正，无法计算回本销量"],
        "name": activity.get("name", ""),
        "expected_volume": float(expected_volume),
        "budget": _round_money(budget),
        "unit_gross": _round_money(unit_gross),
        "contribution_before": _round_money(contribution_before),
        "contribution_after": _round_money(contribution_after),
        "break_even_volume": breakeven_volume,
        "profitable": contribution_after > 0,
    }


def _failed(reason: str) -> dict:
    return {"status": "failed", "reason": reason}


# =====================================================================
# 对齐官方口径的完整指标层（v0.2）
# 新增：销售行模型 + 8 条指标（销量/净销售收入/单位贡献/活动贡献/增量ROI/ROAS/保本）
# 详见 docs/指标字典.md
# =====================================================================

@dataclass
class SalesLine:
    """订单商品行（对齐 RFC §2 sales 对象）。金额单位：元（内部转 Decimal）。"""
    order_id: str = ""
    line_id: int = 0
    sold_at: str = ""                    # ISO 时间，带时区
    product_id: str = ""
    quantity: int = 0                    # 下单数量
    refund_quantity: int = 0             # 退款数量
    gross_amount: float = 0.0            # 折扣前金额
    merchant_discount: float = 0.0       # 商户承担折扣
    refund_amount: float = 0.0           # 退款金额
    is_upstream_net: bool = False        # 上游是否已给净额（True 则不重复扣）
    sales_channel: str = "offline"       # online / offline
    import_batch_id: str = ""            # 导入批次


def _to_decimal(v) -> Decimal:
    try:
        return yuan(v)
    except (InvalidOperation, ValueError):
        raise ValueError(f"不是合法数字: {v}")


def calc_volume(lines: list[SalesLine]) -> dict:
    """指标 1：销量（退款数量处理后的净量）。

    规则：退款有数量时，净销量 = 下单数量 − 退款数量；
          退款只有金额无数量时，只能报下单量，净销量标 needs_data。
    """
    if not lines:
        return _failed("销售行为空")

    total_ordered = Decimal("0")
    total_refund_qty = Decimal("0")
    missing_refund_qty = False

    for ln in lines:
        total_ordered += Decimal(str(ln.quantity))
        total_refund_qty += Decimal(str(ln.refund_quantity))
        if ln.refund_amount > 0 and ln.refund_quantity == 0:
            missing_refund_qty = True

    net_volume = total_ordered - total_refund_qty
    return {
        "status": "needs_data" if missing_refund_qty else "ok",
        "missing_fields": (["退款数量缺失，净销量不准确"] if missing_refund_qty else []),
        "ordered_volume": int(total_ordered),
        "refund_volume": int(total_refund_qty),
        "net_volume": int(net_volume),
        "assumptions": (["部分退款仅金额未给数量，净销量为估算"] if missing_refund_qty else ["退款数量已完整提供，净销量准确"]),
    }


def calc_net_sales(lines: list[SalesLine]) -> dict:
    """指标 2：净销售收入（扣折扣与退款，上游已是净额则不重复扣）。

    规则：is_upstream_net=True → 直接加 net（上游已是净额，不重复扣）；
          否则 净 = 折扣前金额 − 商户折扣 − 退款金额。
    """
    if not lines:
        return _failed("销售行为空")

    total_net = Decimal("0")
    unknown_net = False
    for ln in lines:
        gross = _to_decimal(ln.gross_amount)
        disc = _to_decimal(ln.merchant_discount)
        refund = _to_decimal(ln.refund_amount)
        if ln.is_upstream_net:
            # 上游已是净额：用 gross_amount 视为净额（约定），不再扣
            total_net += gross
        else:
            total_net += gross - disc - refund
        # 若折扣与退款都给了，但无法确认是否已含在 gross 里 → 标注口径未确认
        if (disc > 0 or refund > 0) and ln.is_upstream_net:
            unknown_net = True

    return {
        "status": "needs_data" if unknown_net else "ok",
        "missing_fields": (["上游净额与折扣/退款同时存在，口径需确认"] if unknown_net else []),
        "net_sales": _round_money(total_net),
        "assumptions": ["平台补贴与税费口径另确认"],
    }


def calc_unit_contribution(unit_net_income, unit_var_cost, platform_variable_fee=0.0) -> dict:
    """指标 3：单位贡献 = 单位净收入 − 单位变动成本 − 未计入成本的平台变动费用。

    - unit_net_income: 单位净收入（元）
    - unit_var_cost: 单位变动成本（食材+包材，元）
    - platform_variable_fee: 未计入成本的平台变动费用（元，单独传）
    """
    net = _to_decimal(unit_net_income)
    var = _to_decimal(unit_var_cost)
    fee = _to_decimal(platform_variable_fee)
    contribution = net - var - fee
    return {
        "status": "ok",
        "unit_net_income": _round_money(net),
        "unit_variable_cost": _round_money(var),
        "platform_variable_fee": _round_money(fee),
        "unit_contribution": _round_money(contribution),
        "assumptions": ["固定成本（人力/租金）不计入单位贡献"],
    }


def calc_activity_contribution(net_sales, attributable_var_cost, marketing_input=None) -> dict:
    """指标 4/5：活动贡献（营销投入前/后）。

    - net_sales: 活动净销售收入
    - attributable_var_cost: 可归属变动成本
    - marketing_input: 营销投入（None 则只算投入前）
    规则：折扣已体现在净收入中，不再重复扣减。
    """
    ns = _to_decimal(net_sales)
    vc = _to_decimal(attributable_var_cost)
    before = ns - vc
    result = {
        "status": "ok",
        "contribution_before": _round_money(before),
        "assumptions": ["折扣已体现在净收入中，不再重复扣减"],
    }
    if marketing_input is not None:
        mi = _to_decimal(marketing_input)
        result["contribution_after"] = _round_money(before - mi)
        result["marketing_input"] = _round_money(mi)
        result["assumptions"].append("固定成本若未计入需注明")
    return result


def calc_incremental_roi(incremental_contribution_before, incremental_marketing_input, baseline_reliable=False) -> dict:
    """指标 6：增量营销 ROI（候选口径）。

    公式：(增量贡献〔扣营销投入前〕− 新增营销投入) ÷ 新增营销投入
    规则：基线不可靠时，不作为已验证事实；无基线 → needs_data，不产出确定 ROI。
    """
    inc = _to_decimal(incremental_contribution_before)
    mi = _to_decimal(incremental_marketing_input)

    if mi == 0:
        return {"status": "needs_data", "missing_fields": ["新增营销投入为 0，无法计算 ROI"], "roi": None}

    if not baseline_reliable:
        return {
            "status": "needs_data",
            "missing_fields": ["无可靠的无活动基线，增量贡献不可作为已验证事实"],
            "roi": None,
            "note": "基线不可靠时不得作为已验证事实",
        }

    roi = (inc - mi) / mi
    return {"status": "ok", "roi": _round_money(roi), "assumptions": ["基线可靠，增量贡献可信"]}


def calc_roas(attributable_ad_sales, ad_spend) -> dict:
    """指标 7：ROAS = 可归因广告销售收入 ÷ 广告投入。

    规则：与 ROI 分开命名；缺归因数据时不计算。
    """
    sales = _to_decimal(attributable_ad_sales)
    spend = _to_decimal(ad_spend)
    if spend == 0:
        return {"status": "needs_data", "missing_fields": ["广告投入为 0，无法计算 ROAS"], "roas": None}
    roas = sales / spend
    return {"status": "ok", "roas": _round_money(roas), "assumptions": ["归因数据可靠"]}


def calc_breakeven(fixed_cost, unit_contribution=None, gross_margin_pct=None, capacity=None) -> dict:
    """指标 8：保本分析。

    - 保本量 = 固定成本 ÷ 单位贡献（需单位贡献为正）
    - 保本营业额 = 固定成本 ÷ 毛利率（需毛利率为正）
    - 分母为零或贡献非正 → 无有效结果，不输出无穷或负保本量。
    - capacity: 产能上限（可选），用于标注假设。
    """
    fixed = _to_decimal(fixed_cost)
    result = {"status": "ok", "missing_fields": [], "assumptions": []}

    # 保本量（按单位贡献）
    if unit_contribution is not None:
        uc = _to_decimal(unit_contribution)
        if uc <= 0:
            result["status"] = "needs_data"
            result["missing_fields"].append("单位贡献非正，无法计算保本量")
            result["break_even_volume"] = None
            result["assumptions"].append("单位贡献非正，保本量无有效结果")
        else:
            result["break_even_volume"] = _round_money(fixed / uc)
            result["assumptions"].append("单位贡献为正")

    # 保本营业额（按毛利率）
    if gross_margin_pct is not None:
        gm = _to_decimal(gross_margin_pct)
        if gm <= 0:
            result["status"] = "needs_data"
            result["missing_fields"].append("毛利率非正，无法计算保本营业额")
            result["break_even_revenue"] = None
        else:
            result["break_even_revenue"] = _round_money(fixed / (gm / Decimal("100")))

    if capacity is not None:
        result["assumptions"].append(f"产能上限 {capacity}")
    else:
        result["assumptions"].append("产能无上限")

    if not result["assumptions"]:
        result["assumptions"].append("未提供贡献/毛利率，无法计算保本点")
    return result
