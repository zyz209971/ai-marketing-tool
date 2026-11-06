# 合并版 v2 接口

2026-11-03。以下路由已在本次代码合并中添加，尚待用户在自己的环境中运行联调。
所有 v2 请求均为 JSON，同源部署不需要单独设置域名。现有旧路由继续保留。

## 公共约定

- `X-Visitor-Id`：复用旧页面的浏览器 `visitor_id`，与旧接口共享额度。
- 配置访问密码时，先调用 `POST /api/verify_key`，再在 v2 请求的 `X-Access-Key` 中带上应用访问密码。
  这里传的是应用访问密码，不是模型 API Key。应用访问密码只保存在当前标签页的 sessionStorage。
- 返回同步结果，不需要 `/api/v2/tasks/...` 轮询端点。
- 错误使用 HTTP 403/422/429/502 和 `{"detail":"中文说明"}`；参数校验的 detail 可能是数组。
- 多产品的一次文案请求成功后计一次额度；真实图片和改图各计一次；图片失败和图片占位演示不扣次数。
  这沿用现有按请求计次的方式，不等于实际厂商 token/图片账单。文案演示仍按现有规则计次。

## POST /api/v2/copywriting

```json
{
  "brand":{"id":"浏览器本地ID","name":"示例品牌","description":"品牌介绍","positioning":"日常下午茶","style":"自然"},
  "products":[{"id":"本地产品ID","name":"曲奇","price":"28元","selling_points":["原味","便于分享"]}],
  "platforms":["xiaohongshu","douyin","wechat_official_account"],
  "marketing_goal":"new_product",
  "generation_mode":"text_only",
  "product_strategy":"separate",
  "theme":"",
  "promotion_rules":"",
  "activity_time":"",
  "additional_selling_points":"",
  "style_requirements":"自然"
}
```

marketing_goal 为 new_product/promotion/brand_awareness/holiday。
新品、促销必须有产品；促销还需要优惠规则和活动时间；品牌曝光、节日活动需要主题。
一次最多 10 个产品、3 个平台。product_strategy 为 merged/separate。
无论后续是否配图，这个端点只生成文案，避免自动触发生图。

响应：

```json
{"status":"succeeded","mock":false,"contents":[{"id":"content_xxx","platform":"xiaohongshu","product_label":"曲奇","product_ids":["本地产品ID"],"title":"标题","summary":"","body":"正文","hashtags":["分享"],"mock":false,"references":[]}]}
```

平台映射：xiaohongshu=小红书，douyin=抖音，wechat_official_account=公众号。
公众号单独生成标题、摘要和完整文章，不沿用旧接口的 200 字限制。
每个平台复用当前 `rag.search_for_platforms`，产品事实复用唯一产品解析并额外核对品牌，
无法匹配或品牌不同的事实不注入。SQL 产品资料在生成成功后按品牌保存。
`references` 返回来源文档 ID、标题和平台；真实全文仅用于后端生成。

## POST /api/v2/images

```json
{
  "campaign":{"brand":{"name":"示例品牌","description":"品牌介绍"},"products":[{"id":"p","name":"曲奇","price":null,"selling_points":["原味"]}],"platforms":["xiaohongshu"],"marketing_goal":"new_product","reference_poster":"data:image/png;base64,..."},
  "content":{"id":"c","platform":"xiaohongshu","title":"标题","body":"正文","product_label":"曲奇","product_ids":["p"]},
  "purpose":"post_image"
}
```

campaign 与文案请求相同，额外接受 reference_poster；无参考图时传空串或省略。
仅支持 PNG/JPEG/WebP data URL，解码后最大 4MB；调用现有视觉解析后，再使用当前生图 provider。
product_ids 限定本张图对应的产品，避免多产品分别生成时串商品。
purpose 为 post_image/article_cover。

```json
{"status":"succeeded","image":{"url":"https://图片地址","mock":false},"final_prompt":"最终提示词","parsed_prompt":{},"mock":false}
```

image 也可以返回 `{"format":"png","base64":"...","mock":false}`。
兼容现有 SVG Base64 占位图并标注演示；现有 provider 若返回 error，v2 转为 502，不把失败占位图当作真实成功。
前端失败时保留已有文案、图片和提示词。

## POST /api/v2/images/revise

请求 `{"original_prompt":"当前图片提示词","feedback":"背景改成绿色"}`。
复用现有提示词修改和图片生成 provider，响应格式与 images 相同，final_prompt 为最新提示词。
这是基于上一版提示词重新生图，保持旧功能的实现方式，不是对原图像素的局部编辑。

## POST /api/v2/copywriting/rewrite

请求字段：platform/title/body/summary/hashtags/instruction，可附 id。
只修改文案，不重新生成图片。响应 `{"status":"succeeded","content":单个文案对象,"mock":false}`。

## POST /api/v2/products/search

请求 `{"client_brand_id":"浏览器品牌ID","query":"曲奇","limit":10,"semantic":false}`。
默认复用当前 `/api/search` 的 SQL + 本地 RAG；semantic=true 时复用当前语义产品检索。
响应 `{"products":[{"id":"来源ID","name":"曲奇","brand":"品牌","price":"28元","selling_points":["原味"],"source":"product_rag"}],"semantic":false}`。
client_brand_id 仅用于标记本地工作空间，不是服务器权限过滤条件，结果需人工核对归属后加入本地产品库。

## 保留的旧端点

`/api/health`、`/api/verify_key`、`/api/quota`、`/api/search`、`/api/product_search`、
`/api/generate`、`/api/copywriting`、`/api/image`、`/api/revise`、`/api/rag_search`、`/api/rag_stats` 等原有路由保持原处理方式。
旧页面和 `/legacy/` 挂载已清理，原 API 继续保留。旧接口的访问控制实现没有在此次迁移中重构；
新增 v2 校验应用访问密码不等于新增用户登录或团队权限系统。
