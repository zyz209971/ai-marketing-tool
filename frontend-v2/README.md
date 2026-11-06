# 前端设计 · 灵感引擎 V2

本目录是新增的前端设计与 API 对接草案，供小组评审及后端衔接。默认使用 Mock，尚未接通真实模型；不替换现有 frontend/，不修改 backend/，不改变线上部署。

接口以 docs/API.md 的三服务 v2 契约为准，旧文档中其他接口描述已被该契约替代。图片需在结果页单独点击生成；产品库已有检索入口。

## 工程说明

# 灵感引擎前端工程

基于已确认的 2026-11-03 暖色新版，保留品牌资料、产品库、营销创作、结果修改、版本保存和历史作品。使用原生 JavaScript ES Modules 与 CSS，无第三方运行依赖；未强行迁移 Next.js，以保持当前确认的 UI。Node.js 20 或以上可运行。TypeScript 类型仅作后端协作契约，运行代码为 JavaScript。

## 本地使用
在本目录打开终端：

    npm run dev

访问 http://localhost:5173 。默认使用 Mock。无需 npm install（当前没有外部依赖）。

    npm test
    npm run build
    npm run preview

构建产物在 dist/。开发预览直接读取 src/config.js；.env 只在 build 时生效，切换真实模式后用 build + preview 验证。

## 推送到小组 GitHub
将本文件夹内容合并到小组仓库的前端目录，避免覆盖已有代码或工作流。若前端位于仓库根目录，可直接使用提供的 .github/workflows/pages.yml；若放在 frontend/，需将工作流运行目录改为 frontend，并把上传路径改为 frontend/dist。工作流文件本身必须位于仓库根目录的 .github/workflows 下。
在 GitHub Settings → Pages 中选择 GitHub Actions；推送 main 或手动运行工作流。若团队使用其他主分支，修改 branches。这里没有替你创建仓库或推送。
Pages 是静态前端托管，不能执行 Python/Agent/模型服务。真实 API 必须独立部署为 HTTPS，并允许 Pages 域名的 CORS。相对资源路径支持仓库子路径，无前端路由刷新 404 问题。

## 接入后端
默认 APP_API_MODE=mock。在本地复制 .env.example 为 .env，设 APP_API_MODE=real 和 APP_API_BASE_URL=https://团队后端域名，再重新构建。GitHub Actions 则在 Repository Variables 设置同名变量。
所有前端变量都会公开，禁止填写模型密钥、数据库密码或长期凭证。密钥和模型选择均由后端配置。API 契约见 docs/API.md。

## 目录
- src/app.js：页面、表单与浏览器资料/历史存储。
- src/styles.css：暖色布局。
- src/services/api.js：统一生成、改写、产品检索 API、超时与任务轮询。
- src/services/mock.js：集中模板数据服务。
- src/services/types.ts：接口类型草案。
- scripts：无外部依赖的静态构建与本地预览。
- tests：请求映射与结果适配测试。

## 边界
品牌/产品资料、上传图片、偏好与作品版本仍使用 localStorage，尚未同步后端；品牌附件只保存文件名。产品知识库检索已预留调用函数，尚未接入界面检索控件。配图由后端 image_url 返回，支持查看/另存；本地 SVG 下载仍是排版示意。真实图像模型与检索模型由后端选定，前端不直接调用。自动发布未接入。
尚未实现用户身份认证、团队共享存储、上传接口、请求去重/幂等、真实服务端端到端测试；切换平台前需保存编辑。浏览器本地内容非协作数据库。上线真实业务前需与后端对齐这些事项。

## 验证记录（2026-11-03）
JavaScript 语法检查通过；3 项自动测试通过；静态构建通过。尚未验证 GitHub Actions 实际部署或完成浏览器视觉/点击回归。原确认版与本工程分别保存。

## 2026-11-03 三类模型服务调整（以本节和 docs/API.md 为准）
接口改为 /api/v2/copywriting、/api/v2/images、/api/v2/products/search；改写 /api/v2/copywriting/rewrite，异步状态 /api/v2/tasks/{id}。现有后端需要实现该草案，尚不能直接连接旧版路由。
图文模式先出文案，再单独点击生成图片，独立失败/重试；产品库增加知识库检索入口。embedding、文案、生图模型 ID 与所有厂商密钥在后端配置，前端无需也不应知道。视频未启用。
本工程建议上传到 frontend-v2/ 保留 frontend/；Pages 工作流只在需要时启用，并按目录调整 frontend-v2 的工作目录和上传路径。真实服务尚未联调，当前以 Mock 演示为默认。
本轮语法检查、4 项测试（含网络请求替身的文案成功/图片失败隔离）和构建通过；未进行真实模型、真实后端或浏览器视觉验收。图片生成不自动触发，减少无意消耗。

