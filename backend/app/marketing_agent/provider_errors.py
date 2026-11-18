"""Actionable provider errors without exposing raw requests, keys, or source documents."""
def public_message(exc):
    body = getattr(exc, 'body', {})
    error = body.get('error', body) if isinstance(body, dict) else {}
    message = str(error.get('message', '')).lower() if isinstance(error, dict) else ''
    status = getattr(exc, 'status_code', None)
    if 'guardrail' in message and ('blocked' in message or 'restrictions' in message):
        return '模型服务的工作空间规则禁止使用当前模型。请在 OpenRouter 的 Guardrails 中检查该 Key 的模型权限，或配置一个已允许且支持工具调用的模型。资料已保留。'
    if status in (401, 403):
        return '模型服务拒绝访问，请检查后端密钥及模型权限。资料已保留。'
    if status == 402:
        return '模型服务额度不足，请检查账户余额或 Key 的额度限制。资料已保留。'
    if status == 404:
        return '模型服务没有可用路由，请检查模型 ID、服务地址及账户路由限制。资料已保留。'
    if status == 429:
        return '模型服务暂时限流，请稍后重试。资料已保留。'
    return '模型服务调用失败，请检查服务配置或稍后重试。资料已保留。'
