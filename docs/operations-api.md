# 经营数据、活动模拟与复盘接口

本模块复用现有 FastAPI、SQLAlchemy、品牌工作空间和 Agent 审批记录，不修改前端页面或 Agent 调度协议。金额入库及 API 输出统一使用人民币整数分，日期区间统一为 `[start, end)`。

## 数据闭环

```text
团队 products.csv
  → 商品目录预览/确认
团队 costs.csv
  → 成本预览/确认
历史 orders.csv
  → 订单预览/确认/幂等去重
  → 统一经营汇总、趋势、商品排名
  → 看板 API 与 Agent get_sales_summary 共用计算器

Agent 已批准策略版本
  → 固化活动版本并执行负贡献校验
  → 四场景模拟回传 CSV
  → 回传 CSV 预览/确认
  → 历史基线 / 活动预期 / 实际回传复盘
```

团队数据目录 `合成数据+人工答案+商品图片+csv+json/` 已作为对账来源。`expected_answers.json` 只用于测试核验，业务代码不会读取或硬编码答案。

## 数据库表

| 表 | 作用 | 关键隔离/去重字段 |
|---|---|---|
| `ops_import_batches` | 导入预览、确认状态和错误记录 | `workspace_id + brand_id + content_hash` |
| `ops_skus` | 经营 SKU 与名称、规格映射；不保存产品价格或卖点 | `workspace_id + brand_id + sku_id` |
| `ops_costs` | 按生效日期保存单位成本分项 | `workspace_id + brand_id + sku_id + effective_date` |
| `ops_orders` | 订单级经营事实 | `workspace_id + brand_id + order_id + line_id` |
| `ops_campaigns` | 已批准的不可变活动版本 | `workspace_id + task_id + strategy_id + strategy_version` |
| `ops_simulations` | 随机种子、场景、费用和模拟订单 | `id=simulation_run_id` |

所有经营表均保存 `brand_id`、工作空间、来源和 `synthetic`。查询前先验证品牌归属，并在 SQL 中同时限定工作空间与品牌。

## 1. CSV 预览与确认

### 预览

```http
POST /api/operations/imports/preview
Content-Type: multipart/form-data
```

表单字段：

- `brand_id`：现有品牌 ID；
- `data_type`：`products`、`costs` 或 `orders`；
- `source`：数据来源名称；
- `synthetic`：合成数据传 `true`；
- `file`：UTF-8 CSV。

团队中文表头和元金额会在预览中转换为内部英文结构及整数分。空金额保持 `null`，不会填零。

```json
{
  "import_id": "...",
  "status": "preview",
  "valid_count": 1158,
  "error_count": 0,
  "errors": [],
  "synthetic": true,
  "data_type": "orders",
  "preview": []
}
```

### 确认

```http
POST /api/operations/imports/{import_id}/confirm
```

```json
{
  "status": "confirmed",
  "success_count": 1158,
  "duplicate_count": 0,
  "error_count": 0
}
```

重复预览相同文件会复用原 `import_id`；再次确认时 `success_count=0`、记录计入 `duplicate_count`，汇总不会翻倍。

## 2. 五类经营能力

### 经营指标汇总

```http
GET /api/operations/brands/{brand_id}/summary?start=2026-10-12&end=2026-11-09
```

返回订单数、销量、GMV、营业收入、变动成本、商品贡献、贡献率、金额单位、合成标识和缺失字段计数。

### 时间趋势

```http
GET /api/operations/brands/{brand_id}/trends?start=2026-10-12&end=2026-11-09&granularity=day
```

`granularity` 支持 `day`、`week`、`month`。

### 商品经营分析

```http
GET /api/operations/brands/{brand_id}/products?start=2026-10-12&end=2026-11-09
```

返回商品销量、收入、成本、贡献排名以及前后等长半期的 `stable/declining/increasing` 标签。下降告警只提示进一步核查，不自动归因。

### 看板统一数据源

```http
GET /api/operations/brands/{brand_id}/dashboard?start=2026-10-12&end=2026-11-09&granularity=day
```

一次返回 `summary`、`trends` 和 `products`。看板不应再次计算金额。Agent 的 `get_sales_summary` 在存在订单数据时也使用本模块的订单聚合结果；没有订单数据时继续使用旧经营汇总，保持兼容。

### 活动收益测算

```http
POST /api/operations/campaigns/estimate
```

```json
{
  "list_price_minor": 1800,
  "variable_cost_minor": 650,
  "sales_quantity": 40,
  "promotion_pairs": 10,
  "marketing_spend_minor": 10000,
  "baseline_contribution_minor": 23000,
  "offer": {"type": "second_cup_discount", "pay_bps": 5000}
}
```

关键返回：

```json
{
  "revenue_minor": 63000,
  "variable_cost_minor": 26000,
  "product_contribution_minor": 37000,
  "contribution_after_marketing_minor": 27000,
  "incremental_vs_baseline_minor": 4000
}
```

## 3. 高成本风险校验

```http
POST /api/operations/campaigns/risk-check
```

```json
{
  "list_price_minor": 1800,
  "variable_cost_minor": 1500,
  "offer": {"type": "second_cup_discount", "pay_bps": 5000},
  "policy": {
    "block_negative_unit_contribution": true,
    "min_pair_contribution_minor": 0
  }
}
```

返回 `pair_revenue_minor=2700`、`pair_cost_minor=3000`、`pair_contribution_minor=-300`、`blocked=true` 及具体原因。

## 4. 批准活动与模拟回传

先从 Agent 已批准策略固化活动：

```http
POST /api/operations/campaigns/from-approved-strategy
```

```json
{
  "task_id": "...",
  "strategy_id": "...",
  "strategy_version": 1,
  "campaign_id": "BP-C20261109",
  "baseline_start": "2026-11-02",
  "baseline_end": "2026-11-04"
}
```

接口核对任务工作空间、审批记录、当前策略版本及依赖摘要。未批准、已失效或优惠参数变化均返回 `409`。

模拟接口：

```http
POST /api/operations/campaigns/{campaign_id}/simulate
```

```json
{
  "scenario": "underperforming",
  "seed": 20261109,
  "actual_qty": 24,
  "promotion_pairs": 12,
  "marketing_spend_minor": 10000
}
```

场景值：

- `stable`：销量基本稳定；
- `declining_sales`：日销量按下降权重分配；
- `high_cost`：模拟高成本订单；
- `underperforming`：默认按预期销量的 60% 回传。

返回包含 `simulation_run_id`、`synthetic=true`、来源、种子、活动版本及 CSV 下载地址。相同输入和种子生成相同业务分布。

命令行生成：

```powershell
.\.venv\Scripts\python.exe backend\scripts\generate_operation_scenario.py `
  BP-C20261109 --scenario underperforming --seed 20261109 `
  --actual-qty 24 --promotion-pairs 12 --marketing-spend-minor 10000 `
  --output .local-data\feedback.csv
```

## 5. 活动复盘

模拟 CSV 仍须走预览和确认，确认后调用：

```http
GET /api/operations/campaigns/{campaign_id}/review
```

返回 `baseline`、`expected`、`actual`、实际与预期差异、相对基线增量、目标状态及结构化结论。两天验收结果为：

| 指标（分） | 基线 | 预期 | 实际 |
|---|---:|---:|---:|
| 销量 | 20 | 40 | 24 |
| 收入 | 36000 | 63000 | 32400 |
| 成本 | 13000 | 26000 | 15600 |
| 商品贡献 | 23000 | 37000 | 16800 |
| 宣传费 | 0 | 10000 | 10000 |
| 扣费后贡献 | 23000 | 27000 | 6800 |
| 相对基线增量 | 0 | 4000 | -16200 |

结构化结论为 `volume_up_contribution_down`；接口同时返回 `causal_claim=false`，避免将简单前后比较表述为因果效果。

## 6. 导入团队数据

先在页面创建品牌，取得品牌 ID，然后运行：

```powershell
.\.venv\Scripts\python.exe backend\scripts\import_operations_dataset.py `
  ".\合成数据+人工答案+商品图片+csv+json" --brand-id <品牌ID>
```

脚本按 `products → costs → 历史 orders → campaign_feedback orders` 顺序调用与 API 相同的预览/确认逻辑。重复执行安全，不会重复统计。

## 7. 看板联调案例

项目可重复生成 6 套独立案例，默认输出位置为：

```text
.local-data/dashboard-fixtures/
```

| 案例 | 订单明细 | 看板用途 |
|---|---:|---|
| `stable` | 175 | 35 天跨月稳定趋势、商品排名、无告警状态 |
| `declining_sales` | 175 | P002 连续下降和销量告警 |
| `high_cost` | 175 | P002 第二杯半价且单位成本 15 元，商品贡献为负 |
| `underperforming` | 175 | P002 活动期销量下降和贡献变化 |
| `missing_values` | 2 | 未知实付金额、`null` 结果及缺失字段提示 |
| `empty` | 0 | 新品牌无订单时的空状态 |

四个核心案例均使用团队提供的 5 个 SKU，覆盖 2026-09-28 至 2026-11-02，能够验证日、周、月聚合和跨月展示。商品价格从 `产品知识库.csv` 读取，SKU 映射和成本从经营源目录读取。每个生成目录只包含 `orders.csv`、`manifest.json` 和独立计算的 `expected_dashboard.json`，不复制产品或成本源文件。

重新生成：

```powershell
.\.venv\Scripts\python.exe backend\scripts\generate_dashboard_fixtures.py
```

为已有品牌导入一个案例：

```powershell
.\.venv\Scripts\python.exe backend\scripts\load_dashboard_fixture.py `
  .local-data\dashboard-fixtures\stable --brand-id <品牌ID>
```

看板案例是描述性经营数据，不伪造 Agent 审批记录；正式活动回传和复盘仍必须绑定已批准活动版本。

## 联调边界

- 本模块没有修改现有前端；看板组直接读取 `/dashboard`，不要在浏览器重复计算。
- 现有 Agent 工具名称保持不变，没有新增模型可自由调用的工具名。
- GitHub 中历史活动数据没有 Agent 审批版本，只作为描述性历史事实导入；新模拟回传必须绑定当前批准版本。
- 商品图片仍由现有品牌资料/素材模块维护，经营模块不复制文件。
- 当前为单门店、自提口径；不支持平台佣金分摊、跨店归因或严格因果评估。

## 本地运行与验证

```powershell
# 启动现有单一 FastAPI 进程（不要另起第二个经营服务）
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

# 经营模块测试
..\.venv\Scripts\python.exe -m pytest tests\test_operations.py -q

# 仓库规定的全量回归：后端逐文件执行，前端执行纯逻辑测试
Get-ChildItem .\tests -Filter 'test_*.py' | Sort-Object Name | ForEach-Object {
  & ..\.venv\Scripts\python.exe -m pytest $_.FullName -q
  if ($LASTEXITCODE -ne 0) { break }
}
cd ..
node --test frontend/tests/*.test.mjs
```

`test_operations.py` 对 GitHub 团队 CSV 和人工答案执行真实解析、入库与金额对账；仅“已批准 Agent 策略”前置状态由测试桩写入现有任务表，因为策略生成和人工审批属于队友模块。接口调用、数据库隔离、活动版本校验、模拟、CSV 回传导入和复盘均走真实代码路径。
