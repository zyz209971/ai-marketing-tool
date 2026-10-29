import os
from dotenv import load_dotenv

load_dotenv()

# 阿里云百炼 MaaS 专属端点（OpenAI 兼容协议）
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "https://ws-ehnylndpm63oobsm.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)
# 千问 API key（OpenAI 兼容接口通用）
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")

# 生图模型（通义万相 3.0 Pro）
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "qwen-image-3.0-pro")

# 文案生成模型（DeepSeek，如已配置）
COPY_MODEL = os.getenv("COPY_MODEL", "deepseek-chat")

# 反向解析模型（多模态视觉）
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-max")

# 是否强制 mock
USE_MOCK = os.getenv("USE_MOCK", "").lower() == "true" or not QWEN_API_KEY

# 线上访问密码（为空则不启用密码校验）
APP_ACCESS_KEY = os.getenv("APP_ACCESS_KEY", "")

# 管理员重置密钥（用于重置额度）
ADMIN_RESET_KEY = os.getenv("ADMIN_RESET_KEY", "")

# 额度限制：每人最多次数 / 总共最多次数
QUOTA_PER_USER = int(os.getenv("QUOTA_PER_USER", "7"))
QUOTA_TOTAL = int(os.getenv("QUOTA_TOTAL", "50"))


def has_api_key() -> bool:
    return bool(QWEN_API_KEY)
