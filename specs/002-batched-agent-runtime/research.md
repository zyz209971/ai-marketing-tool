# 决策与来源
Codex request_user_input questions[]启发批次协议；事实输入另支持文本。https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/request_user_input_spec.rs
LangGraph interrupt及Command，恢复重执行所在节点，等待节点隔离副作用。https://docs.langchain.com/oss/python/langgraph/interrupts
SDD以本增量spec→plan→tasks→tests→code→validation组织；001保留为上一轮历史，不覆盖其验收结果。
