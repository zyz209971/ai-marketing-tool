# Research

Decision: 区分提交与执行状态，基于现有agent_runs凭据核对接收结果。Rationale: enqueue先查授权和幂等记录，再检查revision，可原样重试而不重复创建run。Alternatives: 所有catch都恢复并重发会重复操作；只在前端标记已发不足以核对响应丢失；改动供应商调用机制超出范围。

依据：已读取现有前端创建/发送路径、CreateConversation、store.create_task及enqueue去重顺序。没有外部资料研究或模型实验的未知依赖，未启动研究代理。
