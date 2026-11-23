# Interface Contract

POST /api/agent/conversations 新增可选 sku_id。旧 {brand_id,demo} 请求行为不变。带sku_id必须指定可访问品牌并验证商品在用；不能关联其他品牌、归档或不存在SKU。返回的state.brief.sku_id表示实际绑定，catalog提供展示资料。workbench:compose沿用brandId/skuId/text，不新增多商品能力。
