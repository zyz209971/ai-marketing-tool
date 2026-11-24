# Feature Specification: 订单级经营看板

**Feature Branch**: `feat/operating-dashboard`
**Created**: 2026-11-24
**Status**: 已实现可落地范围；不可落地项与缺口见 `docs/operating-dashboard-report.md`。
**Input**: 使用仓库内 `合成数据+人工答案+商品图片+csv+json/` 的 `products.csv`、`orders.csv`、`costs.csv` 与活动元数据，实现净收入、杯数、订单、贡献、趋势、商品排名、活动实际结果和数据质量提示。

## 范围

### 已实现

1. 订单级数据导入，金额从元转换为整数分；重复导入替换同一快照，结果幂等。
2. 日期/商品筛选；净收入、交付杯数、订单数、贡献、优惠、退款汇总。
3. 每日净收入与贡献双折线；缺成本时贡献断线，不按 0 汇总。
4. 每日交付杯数柱状图；区分有销量、零销量、数据缺失。
5. 商品经营排名（杯数/净收入/贡献），支持商品明细下钻。
6. 活动实际结果：杯数、参与杯数、净收入、优惠、贡献、实际宣传费、扣费后贡献；活动整体平均每杯贡献与最低贡献参考线。
7. 数据质量：日期覆盖、缺失日期、缺成本商品、数据版本、导入时间。
8. 订单数按订单号去重；多商品订单不重复计数。

### 非目标 / 未实现

- 第二杯“参与两杯平均”的精确拆分：`orders.csv` 只有整行优惠总额，缺少逐杯分摊/参与组数明细。
- 活动基线、增量贡献、增量 ROI：活动元数据没有基线区间与基线口径；`expected_answers.json` 是验收答案，不作为运行数据源。
- 收益敏感性曲线：需要情景杯数、优惠规则、参与假设、宣传费等输入，当前三表无法自动生成。
- 商品明细直接带入 Agent：数据集 SKU 未关联品牌商品，且 `CreateConversation` 不支持分析日期/数据版本。
- 点击转化、复购、小时热力图：缺少顾客 ID、小时时间、转化事件。
- 多租户、真实生产数据导入、权限隔离：当前看板是单店合成演示数据，全局只读。

## 数据契约

### 输入

- `products.csv`：商品编号、商品名称、规格、当前售价、卖点、分类。
- `orders.csv`：订单号、订单日期、商品编号、商品数量、当时单杯原价、优惠总额、退款总额、活动编号。
- `costs.csv`：商品编号、成本生效日期、每杯原料成本、每杯包材成本、每杯其他变动成本。
- `demo_context.json`：数据集版本、品牌、历史/回传期间、最低单杯贡献、新品上架日期、活动元数据。
- `campaign_feedback/orders.csv`：活动回传订单，字段同 `orders.csv`；复盘期数据与历史期分开。

### 输出

- 所有金额为整数人民币分。
- `start`/`end` 为包含式日期；与 `BusinessRow` 的右开区间不同，接口文档和页面均按包含式展示。
- 贡献 = 净收入 − 变动成本；缺成本时 `contribution_fen=null`，`contribution_complete=false`。
- 订单数 = 去重订单号；商品级订单数 = 包含该商品的去重订单号。
- 退款前已交付杯数仍计入杯数和成本；退款只减少净收入。

## API

- `GET /api/analytics/config`
- `GET /api/analytics/summary?start=&end=&sku=`
- `GET /api/analytics/trend?start=&end=&sku=`
- `GET /api/analytics/products?start=&end=&sort=cups|revenue|contribution`
- `GET /api/analytics/products/{product_id}?start=&end=`
- `GET /api/analytics/campaigns?start=&end=`
- `GET /api/analytics/quality?start=&end=`

## 验收标准

- 历史 28 天汇总与 `expected_answers.json` 的 `history_28d` 一致；活动回传 7 天与 `feedback_7d` 一致。
- P001 商品 28 天汇总与 `sku_totals` 一致。
- 两个活动的实际结果、宣传费、扣费后贡献、参与杯数与人工答案一致。
- 已知零销量日（P004 / 2026-10-27）返回 `state=zero`，不是 missing。
- 缺成本商品贡献为 `null`；对应日趋势断线。
- 重复导入同一数据集后汇总不变。
- 前端页面加载无控制台错误；商品下钻和活动表可展示。
