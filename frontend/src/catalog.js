// Shared filtering and paging for the library and campaign picker.
export const normalize = value=>String(value||'').normalize('NFKC').trim().toLocaleLowerCase('zh-CN');
export const completeProduct = p=>!!(p.name?.trim()&&p.selling?.trim()&&p.price?.trim()&&p.image_document_id);
export function filterCatalog(rows,{query='',category='',image='',completeness='',status='active',sort='updated'}={}) {
  const words=normalize(query).split(/\s+/).filter(Boolean);
  const filtered=rows.filter(p=>
    (status==='all'||(status==='archived'?!!p.archived:!p.archived))&&
    (!category||p.category===category)&&(!image||(image==='present'?!!p.image_document_id:!p.image_document_id))&&
    (!completeness||(completeness==='complete'?completeProduct(p):!completeProduct(p)))&&
    words.every(w=>normalize(p.name+' '+(p.category||'')+' '+(p.selling||'')).includes(w)));
  return filtered.sort((a,b)=>sort==='name'?a.name.localeCompare(b.name,'zh-CN'):Number(b.updated||0)-Number(a.updated||0)||a.name.localeCompare(b.name,'zh-CN'));
}
export function pageOf(rows,page=1,size=20){const pages=Math.max(1,Math.ceil(rows.length/size));page=Math.min(pages,Math.max(1,Number(page)||1));return {rows:rows.slice((page-1)*size,page*size),page,pages,total:rows.length};}
export function toggleSelected(ids,id,checked,limit=10){const next=new Set(ids);if(checked)next.add(id);else next.delete(id);return next.size>limit?{ids:[...ids],overflow:true}:{ids:[...next],overflow:false};}
