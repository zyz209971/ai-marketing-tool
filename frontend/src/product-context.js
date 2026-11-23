// Both library entry points use the same selection rules.
export function productContext(ids, products, brandId) {
  if (ids.length > 1) throw Error('当前一次围绕一款商品创作，请保留一款商品后再开始。');
  if (!ids.length) return {brandId};
  const p=products.find(p=>p.id===ids[0]&&p.brand===brandId&&!p.archived);
  if (!p) throw Error('所选商品已失效，请重新选择当前品牌下仍在使用的商品。');
  return {brandId,skuId:p.id,text:'帮我为'+p.name+(p.spec?'（'+p.spec+'）':'')+'写一篇商品介绍文案'};
}
