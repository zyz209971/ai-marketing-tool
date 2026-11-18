# 模型密钥与代码提交

代码和模型密钥分开管理。前端只调用自己的后端；后端进程读取密钥并调用模型。密钥不进入网页、聊天记录、数据库或 Git。

## 配置位置

优先级：进程环境变量 > `-EnvFile` / `APP_ENV_FILE` 指定文件 > `backend/.env.local` > `backend/.env`。

兼容仓库原有配置，不必为 Agent 重复填写：

```dotenv
WORD_API_KEY=
QWEN_BASE_URL=https://你的服务地址/v1
COPY_MODEL=支持工具调用的模型名称
```

旧变量 `QWEN_API_KEY` 也支持，`WORD_API_KEY` 非空时优先。`QWEN_BASE_URL` 是历史变量名，可用于其他 OpenAI 兼容服务。URL、Key、模型必须属于同一可用服务。

如 Agent 确实需要不同服务，才填写可选的 `AGENT_API_KEY/AGENT_BASE_URL/AGENT_MODEL`；否则留空。文案继续使用原文字服务。不要仅更换一个 Key 而忘记匹配 URL 和模型。

## OpenRouter 本地配置

现有 OpenAI SDK 调用可以直接使用 OpenRouter，不需要替换 Agent 编排框架。在 `backend/.env.local` 填写：

```dotenv
QWEN_BASE_URL=https://openrouter.ai/api/v1
WORD_API_KEY=
COPY_MODEL=z-ai/glm-5.3-flash
AGENT_API_KEY=
AGENT_BASE_URL=
AGENT_MODEL=
USE_MOCK=false
```

仅在私有文件中填入 OpenRouter Key；三个 `AGENT_*` 留空，让 Agent 与文案服务共用配置。OpenRouter 必须使用带供应商前缀的完整模型 ID，不能写“glm 5.3 flash”。2026-11-16 核对公开模型目录，`z-ai/glm-5.3-flash` 支持 `tools` 和 `tool_choice`；已用本地 Key 验证真实文件提取与对话补齐。其他账号的权限及额度仍需分别验证。

工具规范：使用现有 OpenAI SDK 的 Chat Completions，将 `tools[].function.parameters` 设置为 JSON Schema，并通过命名 `tool_choice` 指定工具。先调用 `extract_brief` 提取需求，明确约束平台枚举、金额整数分、日期和优惠结构；随后调用 `decide_marketing_action` 选择下一步，其 `patch` 必须为空。模型返回值再经 Pydantic 与业务规则校验，格式错误最多修复一次。没有放宽已有确认门禁，也没有自动修改 OpenRouter Guardrails。

此配置切换文本服务。海报视觉解析仍共用文本服务的地址和密钥，其 `VISION_MODEL` 也必须另选 OpenRouter 支持图片输入的完整模型 ID；原有 `qwen3-vl-plus` 不能直接照搬。图片生成和 Embedding 继续使用各自配置，不会因填入文本 Key 自动启用。此轮未修改这些功能的配置。

修改后先执行 `./start-agent.ps1 -Check`；填入 Key 后停止原后端进程，再执行 `./start-agent.ps1 -Live`。未填 Key 时检查会显示“离线演示”，不代表已经连接 OpenRouter。不要同时启动两个进程使用同一运行数据目录。

参考：[OpenRouter 接入](https://openrouter.ai/docs/quickstart)、[模型目录](https://openrouter.ai/api/v1/models)。

## 本地测试

新建 `backend/.env.local` 填入自己的配置；也可以直接引用已有文件，不复制密钥：

```powershell
./start-agent.ps1 -EnvFile 'D:/private/marketing.env' -Check
./start-agent.ps1 -EnvFile 'D:/private/marketing.env'
```

已配置到默认位置时直接运行：

```powershell
./start-agent.ps1 -Check
./start-agent.ps1
```

默认自动检测：配置了 Key 且未设置 `USE_MOCK=true` 时使用模型；未配置时明确显示离线演示。`-Live` 强制模型模式，缺 Key 会停止启动；`-Offline` 强制离线。修改配置后重启服务生效。

`-Check` 只显示是否配置、模型名、服务域名和加载来源，不输出 Key，也不发起付费请求。显示已配置不代表已验证网络权限和 Tool Calling，需要真实请求验收。

本地网址：<http://127.0.0.1:8021/agent.html>。密钥可用不会自动把模拟经营数据变成真实数据。

## 推送到团队仓库

提交代码、依赖文件、空密钥的 `backend/.env.example` 和文档。不要提交 `.env`、`.env.local`、数据库、日志及虚拟环境，它们已经被 `.gitignore` 排除。

暂存要提交的文件后可运行：

```powershell
./.venv/Scripts/python.exe backend/scripts/check_repo_safety.py
git diff --cached --stat
```

检查脚本只识别常见泄漏模式，不会显示密钥，不能替代提交差异审查。

确认功能和提交差异后，可以按团队流程提交当前分支：

```powershell
git add README.md backend frontend docs start-agent.ps1
./.venv/Scripts/python.exe backend/scripts/check_repo_safety.py
git diff --cached --stat
git commit -m "Add conversational marketing agent"
git push -u origin feat/marketing-agent
```

以上命令供你后续执行，本次没有替你推送。当前分支包含共享品牌工作空间的合并，PR 应说明这一基线关系。

团队拉取代码后继续使用其已有的后端环境变量或 `.env` 文件即可。推送代码本身不会把你本机的密钥传给队友或服务器，也不会自动让 GitHub Secrets 出现在程序中。若用 GitHub Actions 部署，需要工作流将相应 Secret 显式注入部署环境；这些 Secret 无法通过读取代码库获取明文。

2026-11-15 检查远端当前五个分支：只发现 `.env.example`，模型 Key 字段均为空，没有找到已提交的实际 `.env`。未把任何实际密钥写入本次代码。

当前 Agent API 仍仅允许本机访问。复用配置解决的是模型调用问题；公网部署的用户认证和数据隔离仍需单独完成。
