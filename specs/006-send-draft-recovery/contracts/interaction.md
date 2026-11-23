# Interface Contract

新增 GET /api/agent/conversations/{task_id}/submissions/{request_id}：先授权任务，返回 {found:false} 或 {found:true,run_id,status}，不暴露原请求内容。未知/越权任务按现有404行为处理，不能跨工作区查询。现有POST消息/回答响应、request_id去重及hash语义不变；相同key必须使用原operation与完整payload（含expected_revision）。本次不承诺外部供应商只计费一次。
