# 本地验证
从 app 启动：`./start-agent.ps1`，访问 http://127.0.0.1:8021/agent.html。
密钥沿用 backend/.env.local，不需要写入前端。未配置 embedding 时是关键词检索。

1. 上传品牌名称、商品名称、价格但缺少介绍/卖点的文件；看到补充卡，填写缺项。
2. 刷新，确认缺项和已填内容保留；补齐后确认资料。
3. 提出促销需求；选择平台或填自由回答；确认方案再生成。
4. 修改语气，仅调整文案；点击“保存为品牌长期偏好”，新任务复用。品牌管理可删除。
5. 修改优惠，必须重新测算确认，旧文案标历史。

测试（backend 工作目录）：`../.venv/Scripts/python.exe -m pytest tests/test_marketing_agent.py tests/test_environment.py -q`。
前端（frontend 工作目录）：`npm test`；浏览器脚本见 frontend/tests/agent-intake-browser.mjs。
知识恢复脚本：backend/scripts/restore_marketing_index.py --source 历史库 --target 当前运行目录/marketing.db（拒绝覆盖）。
索引重试：backend/scripts/reindex_confirmed.py --runtime .local-data/agent。
Spec Kit skills 安装在 .agents/skills；新 Codex 会话可使用 $speckit-specify / $speckit-plan / $speckit-tasks，具体看对应 SKILL.md。
