"""文案服务连通性诊断脚本。

用法：
    cd backend
    # 先在 .env 里填好 WORD_API_KEY，然后运行：
    python scripts/diagnose_copy.py

脚本会读取 .env 的 QWEN_BASE_URL / WORD_API_KEY / COPY_MODEL，
直接对 OpenAI 兼容接口发起一次最小请求，并打印：
  - 实际请求的完整 URL（确认 /v1 是否拼对）
  - HTTP 状态码
  - 平台返回的原始响应体（包含错误信息）
  - OpenAI SDK 抛出的异常类型与详情

这样不用启动整个后端，就能定位文案服务调用失败的真正原因。
"""
import json
import sys
from pathlib import Path

# 让脚本能 import backend/app/config.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import QWEN_BASE_URL, WORD_API_KEY, COPY_MODEL, USE_MOCK  # noqa: E402

print("=" * 60)
print("文案服务连通性诊断")
print("=" * 60)
print(f"QWEN_BASE_URL = {QWEN_BASE_URL!r}")
print(f"WORD_API_KEY  = {'(空)' if not WORD_API_KEY else WORD_API_KEY[:6] + '...' + WORD_API_KEY[-4:]}")
print(f"COPY_MODEL    = {COPY_MODEL!r}")
print(f"USE_MOCK      = {USE_MOCK}")
print()

if not WORD_API_KEY:
    print("[X] WORD_API_KEY 为空。后端会走 mock 演示模式，不会报‘文案服务调用失败’。")
    print("    如果你确实看到过该报错，说明当时 key 非空；请把 key 重新填进 backend/.env 再跑本脚本。")
    sys.exit(1)

# 基础 URL 拼接检查：openai-python 会在 base_url 后追加 /chat/completions，
# 多数 OpenAI 兼容平台要求路径为 /v1/chat/completions。
expected_path = "/v1/chat/completions"
actual_path = QWEN_BASE_URL.rstrip("/") + "/chat/completions"
print(f"SDK 实际请求路径 = {actual_path}")
# DeepSeek / OpenAI 等官方接口路径直接是 /chat/completions，不需要 /v1；
# 只有第三方中转站通常才要求 /v1/chat/completions。
_needs_v1_check = not any(h in QWEN_BASE_URL for h in ("api.deepseek.com", "api.openai.com"))
if "/v1" not in QWEN_BASE_URL and _needs_v1_check:
    print(f"[!] 提示：base_url 中没有 /v1。很多中转平台要求路径为 ...{expected_path}，")
    print("    若下面报 404，多半是 base_url 漏写了 /v1。")
print()

try:
    from openai import OpenAI
except ImportError:
    print("[X] 未安装 openai 库，请在 backend 目录运行：pip install openai")
    sys.exit(1)

client = OpenAI(api_key=WORD_API_KEY, base_url=QWEN_BASE_URL)

print("发起最小请求：")
try:
    resp = client.chat.completions.create(
        model=COPY_MODEL,
        messages=[{"role": "user", "content": "回复‘ok’两个字"}],
        max_tokens=16,
        temperature=0,
    )
    print("  [OK] 调用成功")
    print(f"  模型返回: {resp.choices[0].message.content!r}")
    print()
    print("结论：文案服务链路正常。若前端仍报‘文案服务调用失败’，")
    print("     请重启后端并查看后端日志（已加 exc_info 会打印真实异常）。")
except Exception as exc:
    print(f"  [FAIL] 调用失败：{type(exc).__name__}: {exc}")
    print()
    # 尽量挖出 HTTP 状态码和平台返回的原始错误体
    info = getattr(exc, "response", None)
    if info is not None:
        status = getattr(info, "status_code", None)
        print(f"  HTTP 状态码: {status}")
        try:
            body = info.json()
            print(f"  平台返回体: {json.dumps(body, ensure_ascii=False)}")
        except Exception:
            text = getattr(info, "text", "")
            print(f"  平台返回文本: {text[:500]}")
    else:
        print("  （无 HTTP 响应，通常是连接/超时/DNS 问题）")
    print()
    print("常见原因对照：")
    print("  401 → key 无效或已失效")
    print("  404 → base_url 漏了 /v1，或模型名在该平台不存在")
    print("  400 → 模型名拼写错误（deepseek-v4-pro 这类不存在的 ID）")
    print("  402/429 → 余额不足或被限流")
    sys.exit(2)
