# 技术计划
沿用原生 ES modules 与 FastAPI。新增 workbench.js/router.js/workbench.css/icons.js，统一 index.html，agent.html 兼容跳转。
Agent 控制器导出初始化/打开/新建/预填方法，通过事件同步状态；限制 busy 操作范围到聊天区；后台轮询与路由解耦。
现有管理模块通过 managementRoot 适配挂载，保留现有品牌文件、商品与旧作品逻辑；样式在管理容器内隔离。禁止iframe拼接和两个页面自动启动互相覆盖。
Hash 路由保存视图及任务；当前任务、管理品牌、临时草稿分别持有。后端对话摘要加入brand_id/brand_name/task_kind/active_run，支持过滤分页，按工作空间授权。
先写路由及列表契约验收，再实现框架与控制器，最后做浏览器流程/视觉检查与文档。只本地运行，不推送、不发布。
