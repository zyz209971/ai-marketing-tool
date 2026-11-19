# 数据与界面状态
不迁移业务数据库。conversations列表扩展brand_id、brand_name、task_kind、active_run；查询brand_id/q/limit/offset。
工作台状态：view、managementBrandId、activeTaskId、task、busy、workspace、conversationPage；task.brief.brand_id始终由服务器决定。
未发送聊天内容留在常驻聊天视图，不因管理页面切换而销毁。问题选择继续sessionStorage，任务继续后端与LangGraph。
数据指南把品牌/商品事实、经营实际汇总、活动假设、写作参考、运行产物分开；经营工具仍以产品ID和整数分对接。
