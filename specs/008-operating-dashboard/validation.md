# 经营看板验证记录

日期：2026-11-24  
分支：`feat/operating-dashboard`  
数据集：`brandpilot-luckin-operations-synthetic-v2`（合成数据）

## 自动测试

后端按 AGENTS.md 要求分模块独立进程运行：

| 模块 | 结果 |
|---|---|
| `test_analytics.py` | 8 通过 |
| `test_analytics_dataset.py` | 4 通过 |
| `test_deployment_config.py` | 7 通过 |
| `test_environment.py` | 5 通过 |
| `test_handoff_recovery.py` | 6 通过 |
| `test_knowledge.py` | 17 通过 |
| `test_marketing_agent.py` | 65 通过 |
| `test_marketing_case.py` | 2 通过 |
| `test_offline_paths.py` | 24 通过 |
| `test_task_paths.py` | 14 通过 |
| `test_workbench.py` | 3 通过 |
| **合计** | **155 通过** |

前端：

```text
node --test frontend/tests/*.test.mjs
37 通过
```

其他：

- `python -m compileall -q backend/app backend/scripts` 通过。
- `node --check frontend/src/analytics.js`、`analytics-model.js`、`workbench.js`、`router.js` 通过。
- 仅有现有 Starlette/anyio 弃用警告。

## 与人工答案对账

`test_analytics_dataset.py` 直接读取 `expected_answers.json`，验证：

- 历史 28 天 `order_count / line_count / cups / gross / discount / refund / net_revenue / variable_cost / contribution` 全部一致。
- 活动回传 7 天同一组指标全部一致。
- `BP-C20261019`：实际订单数、杯数、净收入、贡献、实际宣传费、扣费后贡献、参与杯数一致。
- `BP-C20261109`：同上，并验证参与杯数 76。
- P001 商品 28 天汇总一致。
- P004 在 2026-10-27 返回 `state=zero`，不是 `missing`。

## 本地页面检查

专用服务：`http://127.0.0.1:8023/#/analytics`，使用 `.local-data/agent/analytics.db`。

| 检查 | 实际观察 |
|---|---|
| 页面加载 | 无控制台错误；导航出现“经营看板” |
| 默认 35 天 KPI | 净收入 `¥36119.50`、杯数 `1,932`、订单 `1,177`、贡献 `¥19716.10` |
| 筛选 P001（10-12 至 11-08） | 净收入 `¥10366.00`、杯数 `533`、订单 `407`、贡献 `¥6048.70` |
| 商品排名 | 筛选前 5 款商品；筛选 P001 后只保留 1 款，避免与 KPI 不一致 |
| 商品下钻 | 可打开“生椰拿铁 · 商品明细”，包含指标和日趋势 |
| 活动图 | 活动整体平均每杯贡献柱状图 + 最低贡献参考线可显示 |
| 数据质量 | 显示数据版本、导入时间、日期覆盖、缺成本商品；本轮数据完整 |
| 入口副作用 | 清空本地任务提示后直接打开 `#/analytics`，服务端没有新建对话请求 |

截图未提交：浏览器窗口截图受当前桌面可见性限制，未取得可保存的视觉截图；以上为 DOM/API/控制台检查记录。页面代码、SVG 图表和响应式样式已落地，但未做真机移动端截图验收。

## 未验证项

- 真实模型、真实 Embedding、真实 PostgreSQL 未验证。
- 真实经营数据导入、工作区隔离、生产部署未验证。
- 第二杯参与两杯平均、活动基线/增量、收益敏感性曲线未实现，详见 `docs/operating-dashboard-report.md`。
- 数据完整性只覆盖数据集已知期间；没有营业日历，无法判断未知区间的全天零销量与缺失。
