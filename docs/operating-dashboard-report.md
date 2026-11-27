# 经营看板实现报告

日期：2026-11-24  
分支：`feat/operating-dashboard`  
数据：`合成数据+人工答案+商品图片+csv+json/`（合成演示数据，非真实经营结果）

## 1. 本轮做了什么

在不改动 Agent 两期经营汇总链路的前提下，新增了**订单级经营看板**：

- 从 `products.csv`、`orders.csv`、`costs.csv`、`campaign_feedback/orders.csv` 和 `demo_context.json` 导入订单级事实。
- 所有金额在导入时从元转换为整数分；订单日期、商品、活动、成本生效日期保留原始口径。
- 新增 `/api/analytics/*` 只读聚合接口，订单、图表、商品明细共用同一套筛选和聚合。
- 新增 `#/analytics` 页面：日期/商品筛选、KPI、双折线、杯数柱状图、商品排名、商品下钻、活动实际结果、数据质量卡。
- 前端没有引入构建链或图表库，使用原生 SVG。

## 2. 已实现的需求

| 需求 | 状态 | 实现口径 |
|---|---|---|
| 日期 + 商品筛选 | 已实现 | `start`/`end` 为包含式日期；商品按 SKU |
| 净收入 | 已实现 | 毛收入 − 优惠 − 退款 |
| 交付杯数 | 已实现 | 商品数量求和；退款前交付仍计入 |
| 订单数 | 已实现 | 按订单号去重；商品级按包含该 SKU 的订单去重 |
| 贡献 | 已实现 | 净收入 − 变动成本；缺成本返回未知 |
| 优惠、退款 | 已实现 | 汇总订单行的优惠总额、退款总额 |
| 收入与贡献趋势 | 已实现 | 按日双折线；缺成本时贡献断线 |
| 交付杯数趋势 | 已实现 | 按日柱状；区分有销量/零销量/数据缺失 |
| 商品经营排名 | 已实现 | 可切换杯数、净收入、贡献；支持商品下钻 |
| 活动实际结果 | 已实现 | 活动期全部该 SKU 订单；实际宣传费；扣费后贡献 |
| 活动最低贡献参考线 | 已实现（活动整体） | 活动整体平均每杯贡献 + `minimum_unit_contribution_fen` 参考线 |
| 数据截至/完整性 | 已实现（已知区间） | 数据集期间内缺失日期；缺成本商品；数据版本和导入时间 |
| 加载/错误/空数据/移动端 | 已实现基础版 | 加载、错误、未导入提示；响应式栅格；未逐项做真机截图验收 |

### 关键口径

```text
毛收入       = Σ(商品数量 × 当时单杯原价)
优惠         = Σ优惠总额
退款         = Σ退款总额
净收入       = 毛收入 − 优惠 − 退款
杯数         = Σ商品数量
订单数       = COUNT(DISTINCT 订单号)
单杯成本     = 原料成本 + 包材成本 + 其他变动成本
变动成本     = Σ(商品数量 × 下单日期适用的成本)
贡献         = 净收入 − 变动成本
```

- 成本按“成本生效日期 ≤ 订单日期”的最近一条匹配。
- 缺成本时贡献为 `null`，不按 0 汇总；页面显示“成本未知”。
- 退款前交付的杯数仍计入杯数和成本；退款只减少净收入。
- 历史价格使用订单行里的“当时单杯原价”，不使用 `products.csv` 的当前售价。

## 3. 数据导入

```bash
# 仓库根目录
python backend/scripts/import_analytics.py
# 或指定自定义运行目录
python backend/scripts/import_analytics.py --runtime .local-data/agent
```

导入结果写入运行目录的 `analytics.db`，该文件是本地生成物，已被 `*.db` 忽略，不进入 Git。重复导入会替换同一看板快照，因此汇总保持幂等。

## 4. API

- `GET /api/analytics/config`
- `GET /api/analytics/summary?start=&end=&sku=`
- `GET /api/analytics/trend?start=&end=&sku=`
- `GET /api/analytics/products?start=&end=&sku=&sort=cups|revenue|contribution`
- `GET /api/analytics/products/{product_id}?start=&end=`
- `GET /api/analytics/campaigns?start=&end=&sku=`
- `GET /api/analytics/quality?start=&end=`

这些接口只读，不触发生成模型；`/api/analytics/` 已加入登录模式的白名单。

## 5. 测试结果

### 自动测试

- 后端新增 `backend/tests/test_analytics.py`：**8 项通过**。
  - 重复导入幂等；
  - 汇总、商品筛选、贡献缺成本；
  - 零销量/缺数据/新品未上架；
  - 商品排名与筛选；
  - 活动实际结果、扣费后贡献、基线未配置；
  - 数据质量、空区间、非法筛选。
- 后端新增 `backend/tests/test_analytics_dataset.py`：**4 项通过**。
  - 历史 28 天汇总与 `expected_answers.json` 的 `history_28d` 完全一致；
  - 活动回传 7 天与 `feedback_7d` 完全一致；
  - 两个活动的实际结果、宣传费、扣费后贡献、参与杯数与人工答案一致；
  - P001 商品 28 天汇总一致；P004 已知零销量日返回 `zero`。
- 后端原有 9 个测试模块：**143 项通过**。
- 后端合计：**155 项通过**（按模块独立进程运行）。
- 前端：**37 项通过**（原有 32 项 + 经营看板纯逻辑 5 项）。
- Python 编译检查、前端 `node --check` 通过。

测试命令：

```bash
cd backend
for f in tests/test_*.py; do python -m pytest "$f" -q || break; done
cd ..
node --test frontend/tests/*.test.mjs
```

### 本地页面检查

使用 `http://127.0.0.1:8023/#/analytics` 打开页面：

- 页面加载后无控制台错误；
- 默认 35 天：净收入 `¥36119.50`、杯数 `1,932`、订单 `1,177`、贡献 `¥19716.10`；
- 筛选 `2026-10-12` 至 `2026-11-08`、商品 P001：净收入 `¥10366.00`、杯数 `533`、订单 `407`、贡献 `¥6048.70`；
- 商品排名、商品下钻、活动实际结果、最低贡献参考线均能渲染；
- 已检查筛选后商品排名只保留所选商品，避免指标与明细不一致。

未做：真实模型、真实 PostgreSQL、线上部署、逐项移动端真机截图。

## 6. 不能做或只做了一部分的需求

| 需求 | 状态 | 为什么不能完整做 / 缺哪些数据 |
|---|---|---|
| 第二杯“参与两杯平均” | 部分 | `orders.csv` 只有整行优惠总额和数量，没有逐杯折扣分摊、参与组数或配对明细；`demo_context.json` 有活动规则，但不足以精确拆出“参与两杯”的平均贡献。当前活动图只显示“活动整体平均每杯贡献”，并明确标注。 |
| 活动基线、增量贡献、增量 ROI | 未实现 | 活动元数据没有基线区间和基线口径；`expected_answers.json` 里的基线是验收答案，不是可运行的业务数据。P004 的人工答案还使用“上周同一星期几”作基线，P002 使用前一周期，规则并不统一，不能从三张表自动推断。 |
| 活动扣宣传费后贡献 | 已实现 | `demo_context.json` 有 `actual_marketing_spend_fen`；按活动实际贡献减实际宣传费计算。 |
| 收益敏感性曲线 | 未实现 | 需要情景杯数、优惠规则、参与组数/参与假设、宣传费、基线选择等输入。现有 Agent 的 `evaluate_promotion` 可算单点，但看板还没有情景输入契约和扫描接口。 |
| 商品明细带入 Agent 策划 | 未实现 | 当前看板商品编号（P001…）来自合成数据集，没有关联到工作区品牌商品；`CreateConversation` 也只支持 `brand_id / sku_id / demo`，没有分析日期和数据版本字段。直接带过去会被品牌商品校验拒绝。 |
| 数据完整性（全天零销量 vs 数据缺失） | 部分 | 在数据集已知期间内可比较预期日期与订单日期，并区分“门店当天有其他订单但该 SKU 无订单”（零销量）和“整天无订单”（缺失）。但没有营业日历/门店开关店数据，无法判断未知区间内的全天零单是真实零销量还是导入缺失。 |
| 数据版本、导入时间 | 已实现（看板自身） | `demo_context.json` 提供 `dataset_version`；导入时记录 `imported_at`。但订单/成本 CSV 本身没有版本列，重新导入依赖整个快照替换。 |
| 点击转化、复购、小时热力图 | 未实现 | 数据没有顾客 ID、小时时间、转化事件、订单状态历史；这些不是图表问题，是数据源缺失。 |
| 多租户/生产真实数据 | 未实现 | 本轮是单店合成数据、全局只读；没有按工作区隔离的导入、授权和真实数据接入。 |

## 7. 增改文件

### 新增

- `backend/app/analytics.py`
- `backend/scripts/import_analytics.py`
- `backend/tests/test_analytics.py`
- `backend/tests/test_analytics_dataset.py`
- `frontend/src/analytics.js`
- `frontend/src/analytics-model.js`
- `frontend/src/analytics.css`
- `frontend/tests/analytics.test.mjs`
- `specs/008-operating-dashboard/spec.md`
- `specs/008-operating-dashboard/validation.md`
- `docs/operating-dashboard-report.md`

### 修改

- `backend/app/main.py`：挂载 analytics 路由与启动钩子。
- `backend/app/auth.py`：登录模式允许 `/api/analytics/`。
- `frontend/index.html`：新增看板容器和样式入口。
- `frontend/src/workbench.js`：新增“经营看板”导航与路由加载。
- `frontend/src/agent.js`：允许在非聊天页面初始化时不自动新建对话，避免打开看板产生空任务。
- `frontend/src/router.js`：新增 `analytics` 视图。
- `frontend/tests/router.test.mjs`：补充 analytics 路由断言。
- `README.md`：补充看板入口、导入命令和报告链接。

### 本地生成物（不提交）

- `.local-data/agent/analytics.db`
- 其他运行目录下的 `analytics.db`
- 所有临时测试数据库

## 8. 运行方式

```bash
# 1. 导入订单级看板数据
python backend/scripts/import_analytics.py

# 2. 启动本地服务
python backend/scripts/run_agent_local.py

# 3. 打开
http://127.0.0.1:8021/#/analytics
```

如果页面提示“经营数据尚未导入”，先执行第 1 步；如果导入后仍提示，请确认 `--runtime` 与服务启动时使用的运行目录一致。
