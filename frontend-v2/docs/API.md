# 新版三类模型服务接口草案（2026-11-03）

本稿替代之前的 /api/campaigns/generate 草案，尚未在小组现有后端实现。不能只切换 real 就认为现有后端已兼容。旧后端 /api/copywriting、/api/image 等保留；建议后端新增 v2 路由适配模型，不破坏旧前端。

## 职责
- 前端 → 文案生成/改写业务接口 → 后端文案模型。
- 前端 → 图片任务接口 → 后端生图模型。
- 前端 → 产品检索接口 → 后端检索与 embedding 模型/向量库。
- embedding 不直接暴露为网页接口；不向浏览器返回向量或模型密钥。
- 团队提到的 qwen-image 3.0、wan 3.0 仅为候选描述，未核验其官方模型 ID/可用性。具体供应商、模型 ID、维度和端点由后端确认。视频不属于本次启用功能。

## 请求约定
所有 v2 POST 使用 JSON。Base URL 为后端域名，不包含 /api。路径统一在 src/services/api.js 的 endpoints 管理。

### POST /api/v2/copywriting
请求见 toRequest 和 types.ts：brand、products、platforms、marketing_goal、product_strategy 等。固定 generation_mode=text_only，附加 retrieval={enabled:true,strategy:"hybrid",top_k:5}。检索应由后端内部执行；无命中仍允许生成。后端可返回 references/retrieval_status 供后续展示，当前 UI 不渲染引用。

同步响应：
```json
{"status":"succeeded","contents":[{"id":"content_001","platform":"xiaohongshu","product_label":"示例商品","title":"示例标题","body":"示例正文","hashtags":["新品分享"]},{"id":"content_002","platform":"wechat_official_account","title":"示例文章标题","summary":"示例摘要","body":"文章全文，段落以换行分隔","hashtags":[]}]}
```
标题正文不能为空；小红书保留标题，公众号返回摘要和完整文章。多产品分别生成时返回产品×平台的 content。品牌/产品目前为本地资料，客户端 ID 不是数据库 ID；以完整商品信息作为本次输入，不能误用本地 ID 查服务器主键。

### POST /api/v2/images
请求：{campaign:完整创作请求,content:{id,platform,title,body,product_label},purpose:"post_image"或"article_cover"}。
响应：{"status":"succeeded","image":{"url":"https://后端图片地址"}}。
图文模式先显示文案，用户另行点击生成图片，失败独立展示并允许重试；不会清除文案。每个平台内容独立请求。图片端点应返回可访问 HTTPS 地址，签名过期及素材权限由后端管理。前端不调用任何模型厂商 API。

### POST /api/v2/copywriting/rewrite
请求：{platform,title,body,summary,hashtags,instruction}。
响应：{"status":"succeeded","content":上述单个文案对象}。
只改文案，不重新生成图片；用户保存后进入本地版本历史。

### GET /api/v2/tasks/{task_id}
文案、图片、改写均可异步返回 {"task_id":"...","status":"pending"}。轮询同结构 pending/processing/succeeded/failed，成功结果字段与上述一致，失败 error 为中文字符串。前端轮询最多 60 次、间隔 1.5 秒；每次请求超时 30 秒。后端需要幂等策略，当前重试可能重新创建任务。

### POST /api/v2/products/search
请求：{"client_brand_id":"本地品牌标识","query":"下午茶","limit":10}。
响应：{"products":[{"id":"服务器产品ID","name":"示例商品","price":null,"selling_points":["草莓风味"]}]}。
当前无后端品牌同步，因此 client_brand_id 仅为来源标记，不是权限凭证，也不能当服务器品牌过滤器；后端先在授权可见的产品库内检索。未来加入登录和品牌同步后，需改为服务器 brand_id，并严格校验归属。返回候选可加入当前本地产品库后人工核对。

## 后端环境变量建议（不是前端配置）
TEXT_MODEL、IMAGE_MODEL、EMBEDDING_MODEL 分开；如供应商兼容端点不同，再分别设置 TEXT_BASE_URL、IMAGE_BASE_URL、EMBEDDING_BASE_URL 和对应服务密钥。视频未来增加 VIDEO_MODEL，但当前不调用。密钥用后端环境配置，禁止提交 GitHub。
更换 embedding 模型或维度时应重建/迁移向量索引，不能直接混用旧向量。是否共用千问账号密钥由后端决定。

## 当前保留的边界
品牌 CRUD、文件解析、产品管理、历史/偏好同步仍为本地存储。图像输入上传、图像编辑、视频生成、真实检索质量和模型输出质量尚未实现或实测。API Key、身份认证、额度、权限由后端提供方案后接入。现有仓库的访问密码/额度流程尚未迁移；不能把本前端视为生产鉴权完成。
