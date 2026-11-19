# 数据模型
Brief.task_kind: brand_setup/content/unit_economics/campaign；content_scope: product/brand。
theme/constraints: 本次活动文本；promotion_pairs: 可享优惠的两杯组数或null；assess_minimum: true/false（false须用户明确选择）。
agent_tasks.state.demo_mode: 新会话false，显式演示true；旧会话按旧逻辑兼容。
kb_products.spec TEXT DEFAULT ''；price_confirmed_at TEXT DEFAULT ''，旧空值显示未记录。
kb_fact_events: id/brand_id/version_id/payload/created；payload含task_id、changes（before/after）、conflicts、provenance、manual_edits、supplements及用户确认状态，与事实入库同事务保存。
AttachmentConfirm.accepted_conflicts: 冲突ID列表。不能由用户伪造sources或跳过版本检查。
kb_works.payload: 兼容旧work结构，增加agent_origin{task_id,artifact_id,strategy_id,version,source_refs,stale}。服务器归档、旧编辑入口只读。
