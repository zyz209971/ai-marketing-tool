# 本轮本地开发说明
入口：http://127.0.0.1:8021/agent.html

## 已完成
- 官方 Spec Kit 1.4.2 配置及 Codex skills，功能规格见 specs/001-conversational-intake/。
- 补充卡支持合法选项和自由输入；问题/任务版本、重复请求、等待状态由后端校验和保存。
- 旧 RAG 安全复制并接回生成，品牌事实与营销参考分开记录；确认后重新索引，embedding 失败仍可关键词查询。
- 长期品牌偏好读取；用户点击确认才保存长期风格，既有品牌管理支持编辑删除。

## 重要实现决策
复用现有任务状态恢复，没有加入第二套 interrupt 状态。存储仍是 .local-data/agent 内 SQLite + brand-files。
模型密钥仍为 backend/.env.local；没有变更密钥，没有提交或推送代码。

## 文档入口
- specs/001-conversational-intake/spec.md：需求与验收
- specs/001-conversational-intake/plan.md：架构与取舍
- specs/001-conversational-intake/tasks.md：任务及后置项
- specs/001-conversational-intake/validation.md：实测证据与限制

## 下一阶段
独立品牌文案路径、真实模型效果评测、用户授权隔离、PostgreSQL/备份/公网部署各自建立增量规格。当前页面仍是本地单工作区版。
