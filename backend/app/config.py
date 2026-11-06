import os
from pathlib import Path

from dotenv import load_dotenv

# 始终从 backend/.env 加载，避免启动目录或终端残留变量影响配置。
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

# 阿里云百炼 MaaS 专属端点（OpenAI 兼容协议）
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://ws-ehnylndpm63oobsm.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)
# 文字 / 视觉 / Embedding API key。
# QWEN_API_KEY 作为旧配置名保留，现有 provider 无需同时修改。
WORD_API_KEY = os.getenv("WORD_API_KEY") or os.getenv("QWEN_API_KEY", "")
QWEN_API_KEY = WORD_API_KEY

# 生图服务可以使用独立的地址和 key；未配置地址时沿用文字接口地址。
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or QWEN_BASE_URL
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")

# Embedding 使用独立配置。未配置时 RAG 自动使用中文 FTS5 / n-gram，
# 不会错误地拿只支持聊天的 WORD_API_KEY 调用 embeddings 接口。
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL") or QWEN_BASE_URL
EMBED_API_KEY = os.getenv("EMBED_API_KEY") or os.getenv("EMBEDDING_API_KEY", "")
EMBED_MODEL = os.getenv("EMBED_MODEL", "")
EMBED_DIMENSIONS = int(os.getenv("EMBED_DIMENSIONS", "1024"))

# 生图模型（可通过 IMAGE_MODEL 切换为图片服务实际支持的模型 ID）
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "qwen-image-3.0-pro")

# 文案生成模型（DeepSeek，如已配置）
COPY_MODEL = os.getenv("COPY_MODEL", "deepseek-chat")

# 文案多平台/多产品并发生成配置。
# 并发默认 3，与平台数量一致；多产品分别生成时可适当调大，但不要超过平台限流。
def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


COPY_CONCURRENCY = _env_int("COPY_CONCURRENCY", 3, 1, 8)
COPY_MAX_RETRIES = _env_int("COPY_MAX_RETRIES", 1, 0, 3)
try:
    COPY_TIMEOUT = max(1.0, float(os.getenv("COPY_TIMEOUT", "120")))
except (TypeError, ValueError):
    COPY_TIMEOUT = 120.0

# 反向解析模型（多模态视觉）
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-max")

# 是否强制 mock。文字和图片分别判断，避免只有其中一个 key 时相互影响。
FORCE_MOCK = os.getenv("USE_MOCK", "").lower() == "true"
USE_MOCK = FORCE_MOCK or not WORD_API_KEY
USE_IMAGE_MOCK = FORCE_MOCK or not IMAGE_API_KEY

# 线上访问密码（为空则不启用密码校验）
APP_ACCESS_KEY = os.getenv("APP_ACCESS_KEY", "")

# 管理员重置密钥（用于重置额度）
ADMIN_RESET_KEY = os.getenv("ADMIN_RESET_KEY", "")

# 额度限制：每人最多次数 / 总共最多次数
QUOTA_PER_USER = int(os.getenv("QUOTA_PER_USER", "7"))
QUOTA_TOTAL = int(os.getenv("QUOTA_TOTAL", "50"))


def has_api_key() -> bool:
    return bool(WORD_API_KEY)


def has_image_api_key() -> bool:
    return bool(IMAGE_API_KEY)
