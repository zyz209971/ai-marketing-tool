import {request} from './services/api.js';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const factLabel=(path,preview)=>{const p=path.split('.'),labels={name:'名称',intro:'品牌介绍',position:'定位',style:'表达风格',preference:'品牌偏好',spec:'规格',price:'价格',selling:'卖点',category:'分类'};return (p[0]==='brand'?'品牌':preview.product_candidates[Number(p[1])]?.name||'商品')+' · '+(labels[p.at(-1)]||'资料');};
const post=(url,body)=>request(url,{method:'POST',body:JSON.stringify(body)});
let hooks;
const path=()=>'/api/agent/conversations/'+hooks.getTask().id;

export function attachmentCards(task){
 return (task.attachments||[]).map(a=>{
  if(a.status==='confirmed')return `<details class="card"><summary>已确认 · ${esc(a.payload.filename)}</summary><p class="note">已作为正式资料保存；原文件在品牌管理中查看。</p></details>`;
  if(a.status==='cancelled')return '';
  if(task.state.suspended_attachment_id===a.id)return `<section class="card"><p>已暂存 · ${esc(a.payload.filename)}</p><p class="note">这份资料尚未确认，不会用于当前分析。</p><button data-resume-attachment>继续补充这份资料</button></section>`;
  let body='';
  if(a.kind==='business'){
   const names=task.catalog||{};
   body=`<p>${esc(a.payload.scope)}</p><div class="table-scroll"><table><thead><tr><th>商品</th><th>上期 / 本期杯数</th><th>单杯成本 / 最低贡献（分）</th></tr></thead><tbody>${a.payload.rows.map(r=>`<tr><td>${esc(names[r.product_id]?.name||r.product_id)}</td><td>${r.previous_qty??'未知'} / ${r.current_qty??'未知'}</td><td>${r.variable_cost_minor??'未知'} / ${r.min_contribution_minor??'未知'}</td></tr>`).join('')}</tbody></table></div><p class="note">${esc(a.payload.rows[0].previous_start)} 至 ${esc(a.payload.rows[0].previous_end)}；${esc(a.payload.rows[0].current_start)} 至 ${esc(a.payload.rows[0].current_end)}。结束日期不含当天。</p>`;
  }else{
   const p=a.payload.preview,b=p.brand_candidate||{};
   body=`<details><summary>查看提取依据</summary><div class="prose">${esc(p.source_text||p.chunks.map(x=>x.content).join('\n'))}</div></details><div class="brand-fields"><label>品牌名称<input name="name" value="${esc(b.name)}"></label><label>品牌介绍<textarea name="intro">${esc(b.intro)}</textarea></label><label>定位<input name="position" value="${esc(b.position)}"></label><label>表达风格<input name="style" value="${esc(b.style)}"></label></div><p class="note">可以直接在聊天中补充缺失信息，不必重新填写资料。确认前请核对品牌与商品事实。</p>`;
   body+=(p.product_candidates||[]).map(v=>{
    const matches=Object.entries(task.catalog||{}).filter(([,x])=>x.name===v.name&&(!v.spec||x.spec===v.spec));
    const id=v.id||(matches.length===1?matches[0][0]:'');
    return `<fieldset class="product-draft" data-product-id="${esc(id)}"><legend>${id?'更新现有商品':'新增商品'}</legend><label>名称<input name="name" value="${esc(v.name)}"></label><label>规格<input name="spec" value="${esc(v.spec)}"></label><label>单价（元，可后补）<input name="price" value="${esc(v.price)}"></label><label>可核实卖点<textarea name="selling">${esc(v.selling)}</textarea></label></fieldset>`;
   }).join('');
   body+=p.structured_extraction===false?`<label>待入库正文（可修改）<textarea class="reviewed-notes">${esc(p.source_text)}</textarea></label>`:'<p class="note">确认后使用上方核对的品牌与商品事实进行检索；原始附件留存供追溯。</p>';
  }
  body+=(a.payload.conflicts||[]).length?'<div class="risk"><p>以下资料与已有版本不同，请逐项核对。修改卡片后先保存，再接受更新。</p>'+a.payload.conflicts.map(c=>`<label class="conflict-choice"><input type="checkbox" data-conflict="${esc(c.id)}">接受 ${esc(({price:'价格',spec:'规格',selling:'卖点',name:'名称',intro:'品牌介绍',style:'风格',position:'定位',category:'分类'})[c.field]||c.field)}：${esc(c.before)} → ${esc(c.after||'清空')}</label>`).join('')+'</div>':'';
  if(a.payload.provenance?.length)body+='<details><summary>字段来源与修改记录</summary>'+a.payload.provenance.map(p=>`<p class="note">${esc(factLabel(p.field,a.payload.preview))}：${esc(p.value)} · ${esc(p.basis==='user_supplement'?'用户补充':p.basis==='user_edited'?'用户编辑':p.basis==='file_exact_text'?'文件原文':'整理或沿用，待核对')} · ${esc(p.filename)}${p.quote?' · “'+esc(p.quote)+'”':''}</p>`).join('')+'</details>';
  const gaps=a.payload.missing_fields||[];
  return `<section class="card attachment-card" data-attachment="${esc(a.id)}"><h2>${gaps.length?'正在补充资料':'待确认资料'} · ${esc(a.payload.filename)}</h2>${gaps.length?`<p class="risk">还缺 ${gaps.length} 项：${gaps.map(g=>esc(g.label)).join('、')}。请在聊天中回答，我会继续整理。</p>`:''}<details ${gaps.length?'':'open'}><summary>查看已整理的资料</summary>${body}</details>${a.kind==='knowledge'?`<button data-save-attachment="${esc(a.id)}">保存编辑并检查缺项</button>`:''}<button class="primary" data-confirm-attachment="${esc(a.id)}" data-incomplete="${gaps.length?'true':'false'}" ${gaps.length?'disabled':''}>核对无误，确认使用</button><button data-cancel-attachment="${esc(a.id)}">暂不使用这份资料</button></section>`;
 }).join('');
}

export function bindAttachmentCards(){
 document.querySelectorAll('[data-resume-attachment]').forEach(button=>button.onclick=()=>hooks.resumeAttachment());
 document.querySelectorAll('[data-cancel-attachment]').forEach(button=>button.onclick=async()=>{
  if(hooks.isBusy())return;hooks.setBusy(true);
  try{await post(path()+'/attachments/'+button.dataset.cancelAttachment+'/cancel',{expected_revision:hooks.getTask().revision});await hooks.load();}
  catch(e){hooks.fail(e);await hooks.load();}finally{hooks.setBusy(false);}
 });
 document.querySelectorAll('[data-confirm-attachment],[data-save-attachment]').forEach(button=>button.onclick=async()=>{
  if(hooks.isBusy())return;
  const saving=!!button.dataset.saveAttachment;
  const task=hooks.getTask(),item=task.attachments.find(a=>a.id===(button.dataset.saveAttachment||button.dataset.confirmAttachment)),card=button.closest('.attachment-card');
  let knowledge;
  if(item.kind==='knowledge'){
   const read=el=>Object.fromEntries([...el.querySelectorAll('input,textarea')].map(e=>[e.name,e.value.trim()]));
   const brand=read(card.querySelector('.brand-fields'));
   knowledge={brand:{...item.payload.preview.brand_candidate,...brand},products:[...card.querySelectorAll('.product-draft')].map((el,index)=>({...item.payload.preview.product_candidates[index],...read(el),id:el.dataset.productId}))};
   if(card.querySelector('.reviewed-notes'))knowledge.reviewed_text=card.querySelector('.reviewed-notes').value;
  }
  hooks.setBusy(true);
  try{await post(path()+'/attachments/'+item.id+(saving?'/save':'/confirm'),{expected_revision:task.revision,knowledge,accepted_conflicts:[...card.querySelectorAll('[data-conflict]:checked')].map(el=>el.dataset.conflict)});await hooks.load();}
  catch(e){hooks.fail(e);await hooks.load();}finally{hooks.setBusy(false);}
 });
}

export function setupWorkspace(options){
 hooks=options;
 $('chooseBrand').onclick=async()=>{
  try{const {brands}=await request('/api/knowledge/brands');$('brandSelect').innerHTML='<option value="">新品牌：通过对话和上传建档</option><option value="__demo__">模拟门店（明确使用示例数据）</option>'+brands.map(b=>`<option value="${esc(b.id)}">${esc(b.name)}</option>`).join('');$('brandSelect').value=hooks.getTask()?.state.brief.brand_id||(hooks.getTask()?.state.demo_mode?'__demo__':'');$('brandError').textContent='';$('brandDialog').showModal();}catch(e){hooks.fail(e);}
 };
 const start=async brand_id=>{const t=await post('/api/agent/conversations',{brand_id:brand_id&&brand_id!=='__demo__'?brand_id:null,demo:brand_id==='__demo__'});$('brandDialog').close();await hooks.open(t.id);};
 $('startBrand').onclick=async()=>{try{await start($('brandSelect').value);}catch(e){$('brandError').textContent=e.message;}};
 $('createBrand').onclick=async()=>{try{const b=await post('/api/knowledge/brands',{name:$('brandName').value.trim(),intro:$('brandIntro').value.trim()});await start(b.id);}catch(e){$('brandError').textContent=e.message;}};
 $('attach').onclick=()=>{$('attachmentError').textContent='';$('attachmentDialog').showModal();};
 $('uploadAttachment').onclick=async()=>{
  if(hooks.isBusy())return;
  const file=$('attachmentFile').files[0];if(!file){$('attachmentError').textContent='请先选择文件。';return;}
  hooks.setBusy(true);$('attachmentError').textContent='正在提取和整理资料，请稍候…';
  try{const form=new FormData();form.append('file',file);await request(path()+'/attachments?kind='+$('attachmentKind').value,{method:'POST',body:form,timeout:180000});$('attachmentDialog').close();$('attachmentFile').value='';await hooks.load();}
  catch(e){$('attachmentError').textContent=e.message;await hooks.load();}finally{hooks.setBusy(false);}
 };
 $('downloadBusiness').onclick=async()=>{
  try{const r=await fetch(path()+'/business-template',{headers:{'X-Access-Key':sessionStorage.getItem('marketing_access_key')||''}});if(!r.ok)throw Error('模板下载失败，请确认品牌。');const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download='business-template.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){$('attachmentError').textContent=e.message;}
 };
}
