import {normalize,completeProduct,filterCatalog,pageOf,toggleSelected} from './catalog.js';
import {generateCampaignJob as generateCampaign,rewriteContent,generateImageJob as generateImage,adaptContents,startJob,waitJob,reviseImage,searchProducts,getHealth,getQuota,verifyAccess,mode,knowledge} from './services/api.js';

const $ = s=>document.querySelector(s);
const e = s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = ()=>globalThis.crypto?.randomUUID?.()||('local_'+Date.now().toString(36)+Math.random().toString(36).slice(2));
let legacyDb;
try { legacyDb=JSON.parse(localStorage.getItem('inspiration-v2')); } catch {}
let db={brands:[],products:[],works:[]};
let current=db.brands[0]?.id,view='brand',draft={},results=[],selected=0,toastTimer;
let controller=null,serverReady=mode==='mock',retrievedProducts=[],suggestTimer,suggestController;
let referencePoster='',referenceName='',createCache=null;
let createMatches=[],createSearchTimer,createSearchController;
let studioDraftRevision=0,studioDraftBrand=null,autoSaveTimer,autoSaveChain=Promise.resolve(),draftPaused=false,productFilter='';
let brandScene='directory',brandQuery='',brandIndustryFilter='',brandCompleteFilter='',docQuery='',docCategory='',docPage=1,docRows=[],docDetails=null;
let library={query:'',category:'',image:'',completeness:'',status:'active',sort:'updated',page:1,layout:'cards'},bulkIds=new Set(),picker=null,selectedProductIds=[],addMatches=[];
let workspaceInfo=null;
const brand = ()=>db.brands.find(b=>b.id===current);
const products = ()=>db.products.filter(p=>p.brand===current&&!p.archived);

async function save() {
  try { const result=await knowledge('/workspace/sync',{method:'POST',body:db}); db.revision=result.revision; return true; }
  catch (error) { if (error.status===409) { await loadWorkspace(); say('资料已被更新，已读取最新版本，请重新修改。'); } else say('服务端保存失败：'+error.message); return false; }
}
function say(text) { $('#toast').textContent=text; $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,4500); }
function head(title,description) { $('#crumb').textContent=title; return `<div class="heading"><div><div class="eyebrow">灵感引擎 / 品牌工作空间</div><h1>${e(title)}</h1><p>${e(description)}</p></div><span class="badge">${e(brand()?.name||'尚未建立品牌')}</span></div>`; }
const input = (id,label,value='',placeholder='')=>`<label for="${id}">${e(label)}</label><input id="${id}" value="${e(value)}" placeholder="${e(placeholder)}">`;
const area = (id,label,value='')=>`<label for="${id}">${e(label)}</label><textarea id="${id}">${e(value)}</textarea>`;
function modal(html) { $('#modal').innerHTML=`<div class="backdrop"><section class="modal" role="dialog" aria-modal="true">${html}</section></div>`; }
function closeModal() { if (controller) return; $('#modal').innerHTML=''; clearTimeout(suggestTimer); suggestController?.abort(); }
function needBrand() {
  if (brand()) return false;
  $('#app').innerHTML=head('先认识你的品牌','建立品牌资料后，即可管理产品和开始创作。')+'<div class="card empty"><button class="primary" onclick="go(\'brand\')">创建品牌</button></div>';
  return true;
}
function chooseBrand() { return `<label for="brandSelect">当前品牌</label><select id="brandSelect" onchange="changeBrand(this.value)">${db.brands.map(b=>`<option value="${e(b.id)}" ${b.id===current?'selected':''}>${e(b.name)}</option>`).join('')}</select>`; }
function go(next) {
  if (controller) { say('请求正在处理中，可先取消当前请求。'); return; }
  if (view==='create'&&$('#goal')) cacheCreate();
  clearTimeout(createSearchTimer); createSearchController?.abort();
  if (view==='results'&&$('#rt')) readResult();
  if(next==='brand'&&view!=='brand')brandScene='directory';
  view=next;
  $('#nav').innerHTML=[['brand','◈　品牌资料'],['products','▦　产品库'],['create','✧　营销创作'],['history','▤　历史作品']].map(([key,label])=>`<button class="${next===key?'active':''}" onclick="go('${key}')">${label}</button>`).join('');
  ({brand:renderBrand,products:renderProducts,create:renderCreate,results:renderResults,history:renderHistory}[next])();
  renderStudioTools();
  window.scrollTo(0,0);
}
async function changeBrand(id) { if(controller)return;await autoSaveChain;const next=view; current=id;library.page=1;bulkIds.clear();docQuery='';docCategory='';docPage=1;selectedProductIds=[];studioDraftBrand=null;draftPaused=false;await primeDraft(id); if(workspaceInfo) localStorage.setItem('active-brand:'+workspaceInfo.id,id); createCache=null; referencePoster=''; referenceName=''; view=''; go(next); }
function newBrand() { current=null;createCache=null;brandScene='editor';docQuery='';docPage=1;view='brand';go('brand'); }
function renderBrandEditor() {
  const b=brand()||{};
  $('#app').innerHTML=head('让每一次表达，都像你的品牌','品牌定位、产品资料和表达偏好，将用于这一次创作。')+`<div class="row" style="margin-bottom:20px"><button onclick="brandDirectory()">← 返回品牌库</button></div>
    <div class="grid"><section class="card"><h2>品牌基本资料</h2>${input('bn','品牌名称 *',b.name)}${area('bi','品牌介绍 *',b.intro)}<div class="two">${input('bp','品牌定位',b.position)}${input('bs','表达风格',b.style)}</div>
    <p class="error" id="be"></p><div class="actions"><button class="primary" onclick="saveBrand()">保存品牌</button></div></section>
    <div><div class="hero"><span class="eyebrow">从品牌开始</span><h2>少一些重复输入，<br>多一点创作空间。</h2><p>整理品牌资料，带着已经确认的产品事实开始创作。</p></div><div class="card" style="margin-top:20px"><h3>品牌偏好记忆</h3><p>${e(b.preference||'可在作品页确认后保存品牌的表达偏好。')}</p>${b.preference?'<button onclick="clearPreference()">清除偏好</button>':''}<button onclick="go('products')">管理产品资料 →</button></div></div></div>${b.id?knowledgePanel():''}`;
  if(b.id)loadBrandDocuments();
}
async function saveBrand() {
  const name=$('#bn').value.trim(),intro=$('#bi').value.trim();
  if (!name||!intro) { $('#be').textContent='请填写品牌名称和介绍。'; return; }
  const old=brand(),b={...(old||{id:uid()}),name,intro,position:$('#bp').value,style:$('#bs').value};
  if (old) Object.assign(old,b); else db.brands.push(b);
  current=b.id; if (await save()) { say('品牌资料已保存到服务端'); go('brand'); }
}
async function demo() {
  const id=uid(); db.brands.push({id,name:'拾光烘焙（示例）',intro:'围绕日常下午茶与分享场景的烘焙品牌。',position:'日常下午茶',style:'温暖自然',files:[]});
  db.products.push({id:uid(),brand:id,name:'草莓巴斯克（示例）',price:'38 元（示例）',selling:'草莓风味、适合分享',image:''},{id:uid(),brand:id,name:'原味曲奇（示例）',price:'28 元（示例）',selling:'原味、下午茶搭配',image:''});
  current=id; createCache=null; if (await save()) { say('示例已加入，生成前请核对资料'); go('brand'); }
}
function editProduct(id='') {
  if(!id){openAddProduct();return;}
  if(id==='__new__')id='';
  const p=db.products.find(item=>item.id===id)||{};
  modal(`<h2>${id?'编辑':'添加'}产品</h2><div class="suggest-wrap">${input('pn','产品名称 *',p.name,'输入名称，检索已有产品')}<div id="suggest" class="suggest" hidden></div></div>${input('pc','产品分类',p.category)}${input('pp','价格（选填）',p.price)}${area('ps','主要卖点 *',p.selling)}<p class="note" id="lookupHint"></p><label for="pi">产品图片（存入品牌库）</label><input type="file" id="pi" accept="image/png,image/jpeg,image/webp"><p class="error" id="pe"></p><div class="actions"><button onclick="closeModal()">取消</button><button class="primary" onclick="saveProduct('${e(id)}')">保存产品</button></div>`);
  $('#pn').addEventListener('input',()=>{
    clearTimeout(suggestTimer); suggestController?.abort(); const query=$('#pn').value.trim(),host=$('#suggest');
    if (!query) { host.hidden=true; $('#lookupHint').textContent=''; return; }
    suggestTimer=setTimeout(async()=>{
      suggestController=new AbortController();
      try {
        const data=await searchProducts(current,query,false,{signal:suggestController.signal});
        if (!host.isConnected||$('#pn').value.trim()!==query) return;
        retrievedProducts=data.products||[];
        host.innerHTML=retrievedProducts.map((item,index)=>`<button type="button" onclick="fillSuggestion(${index})"><strong>${e(item.name)}</strong><small>${e(item.brand||'')} · ${e(item.price||'价格待填')}${item.source==='product_rag'?' · RAG':''}</small></button>`).join(''); host.hidden=!retrievedProducts.length;
      } catch (error) {
        if (host.isConnected&&error.name!=='AbortError') { host.hidden=true; $('#lookupHint').textContent='产品检索暂不可用：'+error.message; }
      }
    },300);
  });
}
function fillSuggestion(index) {
  const p=retrievedProducts[index]; if (!p) return;if(p.brand&&normalize(p.brand)!==normalize(brand()?.name)){say('该产品属于其他品牌，请切换品牌后维护。');return;}
  $('#pn').value=p.name; $('#pp').value=p.price||''; $('#ps').value=(p.selling_points||[]).join('、');
  $('#suggest').hidden=true; $('#lookupHint').textContent='已填入知识库资料，请核对品牌、价格和卖点后保存。';
}
async function readFile(file,maxBytes) {
  if (!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>maxBytes) throw Error(`请选择 PNG、JPEG 或 WebP 图片，最大 ${maxBytes/1024/1024}MB。`);
  return new Promise((resolve,reject)=>{ const reader=new FileReader(); reader.onload=()=>resolve(reader.result); reader.onerror=()=>reject(Error('读取图片失败。')); reader.readAsDataURL(file); });
}
async function saveProduct(id) {
  const name=$('#pn').value.trim(),selling=$('#ps').value.trim();
  if (!name||!selling) { $('#pe').textContent='请填写产品名称和主要卖点。'; return; }
  const duplicate=db.products.find(p=>p.brand===current&&normalize(p.name)===normalize(name)&&p.id!==id);if(duplicate){$('#pe').textContent='当前品牌已有同名产品，请返回搜索结果编辑该产品。';return;}
  const old=db.products.find(p=>p.id===id); let image=old?.image||'';
  try { if ($('#pi').files[0]) { const form=new FormData(); form.append('file',$('#pi').files[0]); const uploaded=await knowledge('/brands/'+encodeURIComponent(current)+'/documents?purpose=product_image',{method:'POST',body:form}); image='/api/knowledge/brands/'+encodeURIComponent(current)+'/documents/'+encodeURIComponent(uploaded.id)+'/file'; old && (old.image_document_id=uploaded.id); if (!old) var uploadedId=uploaded.id; } }
  catch (error) { $('#pe').textContent=error.message; return; }
  const p={...(old||{}),id:id||uid(),brand:current,name,category:$('#pc').value,price:$('#pp').value,selling,image,image_document_id:uploadedId||old?.image_document_id||''};
  if (old) Object.assign(old,p); else db.products.push(p);
  if (!await save()) return; closeModal(); go(view==='create'?'create':'products');
}
function importProducts() { modal(`<h2>批量导入产品</h2><p>粘贴 JSON 数组，最多 50 款，导入当前品牌。</p><small>[{"name":"产品名称","price":"38元","selling":"商品卖点"}]</small><textarea id="bulk"></textarea><p class="error" id="bulkerr"></p><div class="actions"><button onclick="closeModal()">取消</button><button class="primary" onclick="doImport()">导入</button></div>`); }
async function doImport() {
  try {
    const rows=JSON.parse($('#bulk').value);
    if (!Array.isArray(rows)||!rows.length||rows.length>50||rows.some(p=>typeof p.name!=='string'||!p.name.trim()||typeof p.selling!=='string'||!p.selling.trim()||p.price!=null&&typeof p.price!=='string')) throw Error();
    const names=rows.map(p=>normalize(p.name));if(new Set(names).size!==names.length||db.products.some(p=>p.brand===current&&names.includes(normalize(p.name)))){$('#bulkerr').textContent='导入内容或当前品牌中已有同名产品，请先检查重复项。';return;}
    db.products.push(...rows.map(p=>({id:uid(),brand:current,name:p.name,price:p.price||'',selling:p.selling,image:''})));
    if (await save()) { closeModal(); go('products'); say('产品已导入'); }
  } catch { $('#bulkerr').textContent='请检查数组格式，每款产品都需要名称和卖点。'; }
}
function openSearch() { modal(`<h2>检索产品知识库</h2><p>默认使用现有数据库与本地 RAG。语义搜索会按后端配置使用 Embedding。</p>${input('sq','产品名称或需求')}<label><input type="checkbox" id="semantic"> 使用语义搜索</label><button onclick="lookupProducts()">搜索</button><div id="searchresults"></div><div class="actions"><button onclick="closeModal()">关闭</button></div>`); }
async function lookupProducts() {
  const query=$('#sq').value.trim(); if (!query) { say('请输入搜索内容'); return; }
  const host=$('#searchresults'); host.textContent='正在检索…';
  try {
    const data=await searchProducts(current,query,$('#semantic').checked);
    if (!host.isConnected) return; retrievedProducts=data.products||[];
    host.innerHTML=retrievedProducts.map((p,index)=>`<div class="historyline"><strong>${e(p.name)}</strong><small> ${e(p.brand||'')} · ${e(p.source||'知识库')}</small><p>${e(p.price||'价格待填')} · ${e((p.selling_points||[]).join('、'))}</p><button onclick="adoptProduct(${index})">加入当前品牌</button></div>`).join('')||'<p>未找到相关产品，可手动添加。</p>';
  } catch (error) { if (host.isConnected) host.textContent=error.message; }
}
async function adoptProduct(index) {
  const p=retrievedProducts[index];if(p?.brand&&normalize(p.brand)!==normalize(brand()?.name)){say('该产品属于其他品牌，请先切换对应品牌。');return;} if (!p?.name||!p.selling_points?.length) { say('产品缺少名称或卖点，请手动补充。'); return; }
  if (products().some(x=>x.name===p.name)) { say('当前品牌已有同名产品，请在产品库中编辑。'); return; }
  db.products.push({id:uid(),serverId:p.id,brand:current,name:p.name,price:p.price||'',selling:p.selling_points.join('、'),image:''});
  if (await save()) { closeModal(); go('products'); say('已加入，请核对该产品是否属于当前品牌'); }
}
function cacheCreate() {
  createCache={brand:current,goal:$('#goal').value,ids:selectedProductIds.filter(id=>products().some(p=>p.id===id)),plats:[...document.querySelectorAll('[name=platform]:checked')].map(x=>x.value),merge:$('#merge').value,format:$('#format').value,points:$('#points').value,style:$('#style').value,rules:$('#rules')?.value||'',dates:$('#dates')?.value||'',theme:$('#theme')?.value||'',imageMode:$('#imageMode')?.value||'photo',imageCount:$('#imageCount')?.value||3};
}
function renderCreate() {
  if (needBrand()) return;
  const c=createCache?.brand===current?createCache:null;
  selectedProductIds=(c?.ids||[]).filter(id=>products().some(p=>p.id===id));
  $('#app').innerHTML=head('今天，想为品牌讲些什么？','选择产品、营销目的和平台，文案与图片可以独立生成。')+`<div class="step"><b>01　选择创作需求</b><span>02　生成内容</span><span>03　修改与保存</span></div><div class="grid"><section>
    <div class="card"><h2>01　品牌与营销目的</h2>${chooseBrand()}<label for="goal">营销目的</label><select id="goal" onchange="goalFields()">${['新品推广','促销','品牌曝光','节日活动'].map(s=>`<option ${c?.goal===s?'selected':''}>${s}</option>`).join('')}</select><div id="goalfields"></div></div>
    <div class="card"><div class="row spread"><h2>02　相关产品</h2><button class="primary" onclick="openProductPicker()">选择产品</button></div><p class="note">仅展示本次已选产品，最多 10 款。品牌曝光可不选产品。</p><div id="createProductOptions">${selectedProductCards()}</div><label for="merge">多产品生成方式</label><select id="merge"><option value="merge">合并为一份活动素材</option><option value="separate" ${c?.merge==='separate'?'selected':''}>每款产品分别生成</option></select></div>
    <div class="card"><h2>03　平台与内容形式</h2><div class="three">${['小红书','抖音','微信公众号'].map(p=>`<label class="pick"><input type="checkbox" name="platform" value="${p}" ${(c?c.plats.includes(p):p==='小红书')?'checked':''}><strong>${p}</strong></label>`).join('')}</div><label for="format">内容形式</label><select id="format">${['仅文案','图文','仅图片'].map(s=>`<option ${c?.format===s?'selected':''}>${s}</option>`).join('')}</select><label>配图方式<select id="imageMode"><option value="photo">产品实拍排版（保留原图）</option><option value="ai" ${c?.imageMode==='ai'?'selected':''}>AI 创意配图</option></select></label><label>小红书图片张数<select id="imageCount">${[1,3,6].map(n=>`<option ${Number(c?.imageCount||3)===n?'selected':''}>${n}</option>`).join('')}</select></label>${area('points','补充卖点（选填）',c?.points)}${input('style','表达偏好',c?.style??brand().preference??brand().style)}
    <label for="poster">参考海报（选填，PNG / JPEG / WebP，最大 4MB）</label><div id="drop" class="file-drop"><span id="posterName">${e(referenceName||'点击或拖拽图片到这里')}</span><input type="file" id="poster" accept="image/png,image/jpeg,image/webp"><img id="posterPreview" ${referencePoster?`src="${e(referencePoster)}"`:'hidden'} alt="参考海报预览"></div><button onclick="clearPoster()" type="button">移除参考海报</button><p class="note">参考海报会在生成图片时交给后端解析；实拍排版使用产品原图；AI 创意配图依据文字生成，可能改变产品外观。</p><p class="error" id="ce"></p><div class="actions"><button class="primary" onclick="generate()">✧ 开始创作 →</button></div></div></section>
    <div><div class="hero"><span class="eyebrow">品牌灵感板</span><h2>${e(brand().name)}</h2><p>${e(brand().intro)}</p><span class="badge">${e(brand().position||'待补充定位')}</span></div><div class="card" style="margin-top:20px"><h3>本次会带上什么？</h3><p>品牌介绍与定位<br>产品价格、卖点与知识库事实<br>营销目的、活动信息与表达偏好</p><div class="tip">图文模式先生成文案，再由你点击生成图片。仅图片模式直接生成所选平台的第一张图片，其余图片按需生成。</div><small>资料和历史作品保存在服务端；自动发布尚未接入。</small></div></div></div>`;
  goalFields(c);
  createMatches=[];

  $('#poster').addEventListener('change',event=>setPoster(event.target.files[0]));
  const drop=$('#drop'); drop.addEventListener('dragover',event=>{ event.preventDefault(); drop.classList.add('drag'); });
  drop.addEventListener('dragleave',()=>drop.classList.remove('drag'));
  drop.addEventListener('drop',event=>{ event.preventDefault(); drop.classList.remove('drag'); setPoster(event.dataTransfer.files[0]); });
}
function goalFields(cache=null) {
  const goal=$('#goal').value,c=cache&&typeof cache==='object'?cache:{};
  $('#goalfields').innerHTML=goal==='促销'?input('rules','优惠规则 *',c.rules)+input('dates','活动时间 *',c.dates):goal==='品牌曝光'?input('theme','传播主题 *',c.theme):goal==='节日活动'?input('theme','节日主题 *',c.theme)+input('rules','优惠规则（选填）',c.rules)+input('dates','活动时间（选填）',c.dates):'';
}
async function setPoster(file) {
  if (!file) return;
  try { referencePoster=await readFile(file,4*1024*1024); referenceName=file.name; if ($('#posterPreview')) { $('#posterPreview').src=referencePoster; $('#posterPreview').hidden=false; $('#posterName').textContent=file.name; } }
  catch (error) { say(error.message); }
}
function clearPoster() { referencePoster=''; referenceName=''; $('#poster').value=''; $('#posterPreview').removeAttribute('src'); $('#posterPreview').hidden=true; $('#posterName').textContent='点击或拖拽图片到这里'; }
function ready() { if (!serverReady) { say('请先连接后端并完成访问密码校验。'); return false; } return true; }
function cancelJob() { controller?.abort(); say('已取消等待；后端已开始的模型任务可能仍会执行。'); }
async function generate() {
  if (!ready()||controller) return;
  cacheCreate(); const c=createCache,ps=c.ids.map(id=>db.products.find(p=>p.id===id)).filter(Boolean);
  if (!c.plats.length||ps.length>10||['新品推广','促销'].includes(c.goal)&&!ps.length||c.goal==='促销'&&(!c.rules.trim()||!c.dates.trim())||['品牌曝光','节日活动'].includes(c.goal)&&!c.theme.trim()) { $('#ce').textContent='请选择平台和不超过 10 款产品，并补齐当前营销目的所需的信息。'; return; }
  c.imageMode=$('#imageMode')?.value||c.imageMode||'photo';c.imageCount=$('#imageCount')?.value||c.imageCount||3;
  draft={...c,brand:structuredClone(brand()),ps:structuredClone(ps),referencePoster,referenceName};
  if (c.format==='仅图片') {
    const groups=c.merge==='separate'&&ps.length?ps.map(p=>[p]):[ps];
    results=groups.flatMap(group=>c.plats.map(platform=>({id:uid(),platform,subject:group.map(p=>p.name).join('、')||c.theme||brand().name,productIds:group.map(p=>p.id),
      title:group.map(p=>p.name).join('、')||c.theme||brand().name,body:group.map(p=>p.selling).join('；')||brand().intro,summary:'',tags:'',versions:[],imageVersions:[],saved:false,imageStatus:'not_requested'})));
    selected=0; go('results'); await requestImage(); return;
  }
  await runGeneration();
}
async function runGeneration() {
  if (!ready()||controller) return;
  controller=new AbortController();
  $('#app').innerHTML=head('正在准备这一次灵感','按所选平台整理品牌、商品事实与营销目的。')+'<div class="card"><p role="status">正在生成文案，请稍候…</p><button onclick="cancelJob()">取消等待</button></div>';
  try { results=await generateCampaign(draft,{signal:controller.signal}); selected=0; controller=null; go('results'); scheduleDraft(); }
  catch (error) {
    controller=null;
    $('#app').innerHTML=head(error.name==='AbortError'?'已取消等待':'生成未完成','品牌、产品和创作需求仍保留。')+`<div class="card"><p class="error">${e(error.message)}</p><button onclick="runGeneration()">重试本次请求</button> <button onclick="go('create')">返回创作</button></div>`;
  } finally { controller=null; await refreshQuota(); }
}
function selectResult(index) { if (controller) { say('请先等待或取消当前请求'); return; } readResult(); selected=index; renderResults(); }
function readResult() {
  const r=results[selected]; if (!r) return;
  for (const [id,key] of [['rt','title'],['rb','body'],['rs','summary'],['rh','tags']]) if ($('#'+id)&&r[key]!==$('#'+id).value) { r[key]=$('#'+id).value; r.saved=false; }
}
function renderResults() {
  const r=results[selected]; if (!r) { go('create'); return; }
  r.versions??=[]; r.imageVersions??=[];
  const imageOnly=draft.format==='仅图片',busy=!!controller,disabled=busy?'disabled':'';
  $('#app').innerHTML=head('把灵感，打磨成满意的作品','切换内容时会保留当前编辑，满意后请保存到历史作品。')+`<div class="tabs">${results.map((item,index)=>`<button ${disabled} class="${index===selected?'active':''}" onclick="selectResult(${index})">${e(item.platform)} · ${e(item.subject)}${item.saved?' ✓':''}</button>`).join('')}</div><div class="grid"><section class="card"><div class="row spread"><h2>${imageOnly?'配图信息':e(r.platform)+'内容'}</h2><span class="badge">${r.mock?'模板演示':'创作结果'} · ${r.saved?'已保存':'未保存'}</span></div>
    ${input('rt','标题',r.title)}${r.platform==='微信公众号'?input('rs','文章摘要',r.summary):''}${area('rb',imageOnly?'画面产品信息':'正文',r.body)}${input('rh','话题标签',r.tags)}<div class="row" style="margin-top:18px">${imageOnly?'':`<button ${disabled} onclick="rewrite()">输入文案修改意见</button><button ${disabled} onclick="copyText()">复制文案</button>`}<button ${disabled} class="primary" onclick="saveWork()">保存当前版本</button></div>
    <details><summary>文案历史版本（${r.versions.length}）</summary>${r.versions.map((v,index)=>`<div class="historyline">第 ${index+1} 版 · ${e(v.time)} <button ${disabled} onclick="restore(${index})">恢复</button></div>`).join('')||'<p>保存作品后保留版本。</p>'}</details>
    ${r.references?.length?`<details><summary>参考案例来源（${r.references.length}）</summary>${r.references.map(ref=>`<p>${e(ref.platform)} · ${e(ref.title||ref.document_id)}</p>`).join('')}</details>`:''}</section>
    <div><section class="card"><h2>${r.platform==='微信公众号'?'文章封面':'营销配图'}</h2>${draft.format==='仅文案'?'<p>本次选择了仅文案；如需配图，可开启配图功能。</p><button onclick="enableImages()">为这次作品添加配图</button>':`
      ${r.imageStatus==='processing'?'<p role="status">图片正在生成…</p>':''}${r.imageStatus==='mock'?'<p class="note">当前为后端演示占位图，尚未调用真实生图服务。</p>':''}${r.imageError?`<p class="error">${e(r.imageError)} 原有文案和图片均已保留。</p>`:''}
      ${r.imageUrl?`<img class="result-image" src="${e(r.imageUrl)}" alt="营销配图"><p><a href="${e(r.imageUrl)}" target="_blank" rel="noopener noreferrer" ${r.imageUrl.startsWith('data:')?'download="营销配图"':''}>打开或下载配图</a></p>`:`<div class="art"><span>等待生成图片</span><strong>${e(r.subject)}</strong><small>生成图片会使用后端生图服务</small></div>`}
      ${r.gallery?.length?`<div class="row">${r.gallery.map((g,i)=>`<button onclick="selectGallery(${i})"><img src="${e(g.url)}" alt="第${i+1}张" style="width:65px;height:75px;object-fit:cover"></button>`).join('')}</div>`:''}<div class="row"><button ${disabled} onclick="requestImage()">${r.imageUrl?'重新生成图片':'生成图片'}</button>${r.finalPrompt&&r.parsedPrompt?.method!=='product_photo'?`<button ${disabled} onclick="openReviseImage()">继续修改图片</button>`:''}</div>
      ${r.finalPrompt?`<details><summary>提示词与海报解析</summary><p class="resulttext">${e(r.finalPrompt)}</p>${Object.entries(r.parsedPrompt||{}).map(([key,value])=>`<p>${e(key)}：${e(value)}</p>`).join('')}</details>`:''}
      ${r.imageVersions.length?`<details><summary>图片历史版本（${r.imageVersions.length}）</summary>${r.imageVersions.map((v,index)=>`<div class="historyline">第 ${index+1} 版 · ${e(v.time)} <button ${disabled} onclick="restoreImage(${index})">恢复图片</button></div>`).join('')}</details>`:''}`}
    </section><section class="card"><h3>记住这一次的表达</h3><p>确认后，将表达偏好用于当前品牌的下次创作。</p><label><input type="checkbox" id="remember"> 我确认记住为品牌偏好</label><button ${disabled} onclick="remember()">保存偏好</button></section><button ${disabled} onclick="exportWork()">保存并打包导出</button><button ${disabled} onclick="showJobs()">任务记录</button><button ${disabled} onclick="go('create')">＋ 开始下一次创作</button></div></div>${busy?'<div class="jobbar" role="status">请求处理中 <button onclick="cancelJob()">取消等待</button></div>':''}`;
  if (busy) document.querySelectorAll('#app input,#app textarea').forEach(el=>el.disabled=true);
}
function enableImages() { readResult(); draft.format='图文'; renderResults(); }
async function saveWork() {
  readResult(); const r=results[selected]; if (!r.title.trim()||!r.body.trim()) { say('请补齐标题和正文'); return; }
  const snapshot=structuredClone(r); snapshot.versions.push({title:r.title,body:r.body,summary:r.summary,tags:r.tags,time:new Date().toLocaleString('zh-CN')}); snapshot.saved=true;
  const work={id:r.id,brand:draft.brand.id,draft:structuredClone(draft),result:snapshot,time:new Date().toLocaleString('zh-CN')};
  const index=db.works.findIndex(w=>w.id===r.id),before=structuredClone(db.works);
  if (index<0) db.works.unshift(work); else db.works[index]=work;
  if (!await save()) { db.works=before; return; }
  Object.assign(r,snapshot); renderResults(); say('作品与版本已保存到服务端');
}
function restore(index) { readResult(); Object.assign(results[selected],results[selected].versions[index],{saved:false}); renderResults(); }
function restoreImage(index) { readResult(); const r=results[selected]; Object.assign(r,r.imageVersions[index],{saved:false,imageError:''}); renderResults(); }
function recordImage(target,outcome) { scheduleDraft(); Object.assign(target,outcome,{saved:false}); target.imageVersions??=[]; target.imageVersions.push({...outcome,time:new Date().toLocaleString('zh-CN')}); }
async function requestImage() {
  if (!ready()||controller) return; readResult(); const target=results[selected],oldStatus=target.imageStatus;
  controller=new AbortController(); target.imageStatus='processing'; target.imageError=''; renderResults();
  try { recordImage(target,await generateImage(target,draft,{signal:controller.signal})); }
  catch (error) { target.imageStatus=oldStatus||'not_requested'; if (error.name!=='AbortError') target.imageError=error.message; }
  finally { controller=null; renderResults(); await refreshQuota(); }
}
function openReviseImage() { readResult(); modal(`<h2>继续修改图片</h2><p>根据当前图片的提示词和你的意见重新生成；文案保留。</p>${area('imageFeedback','图片修改意见 *','','')}<p class="error" id="imageError"></p><div class="actions"><button onclick="closeModal()">取消</button><button class="primary" onclick="submitReviseImage()">修改图片</button></div>`); }
async function submitReviseImage() {
  if (controller) return; const feedback=$('#imageFeedback').value.trim(); if (!feedback) { $('#imageError').textContent='请填写修改意见'; return; }
  const target=results[selected],oldStatus=target.imageStatus; closeModal(); controller=new AbortController(); target.imageStatus='processing'; target.imageError=''; renderResults();
  try { recordImage(target,await generateImage(target,{...draft,points:(draft.points||'')+'；配图修改要求：'+feedback},{signal:controller.signal})); }
  catch (error) { target.imageStatus=oldStatus; if (error.name!=='AbortError') target.imageError=error.message; }
  finally { controller=null; renderResults(); await refreshQuota(); }
}
function rewrite() { readResult(); modal(`<h2>你希望如何修改文案？</h2>${area('revision','修改意见 *')}<p class="note">只改文案，保留当前图片。</p><p class="error" id="rewriteError"></p><div class="actions"><button onclick="closeModal()">取消</button><button class="primary" onclick="doRewrite()">提交改写</button></div>`); }
async function doRewrite() {
  if (controller) return; const instruction=$('#revision').value.trim(); if (!instruction) { $('#rewriteError').textContent='请输入修改意见'; return; }
  const target=results[selected]; closeModal(); controller=new AbortController(); renderResults();
  try { const updated=await rewriteContent(target,instruction,{signal:controller.signal}); Object.assign(target,{title:updated.title,body:updated.body,summary:updated.summary,tags:updated.tags,mock:updated.mock,saved:false,lastInstruction:instruction}); }
  catch (error) { if (error.name!=='AbortError') say(error.message); }
  finally { controller=null; renderResults(); await refreshQuota(); }
}
async function copyText() {
  readResult(); const r=results[selected],text=[r.title,r.summary,r.body,r.tags].filter(Boolean).join('\n\n');
  try { await navigator.clipboard.writeText(text); say('文案已复制'); }
  catch { modal(`<h2>请手动复制</h2><textarea readonly>${e(text)}</textarea><div class="actions"><button onclick="closeModal()">完成</button></div>`); }
}
async function remember() { if (!$('#remember').checked) { say('请先勾选确认'); return; } const b=db.brands.find(item=>item.id===draft.brand.id); if (!b) return; const preference=results[selected]?.lastInstruction||draft.style; if (!preference?.trim()) { say('请先填写表达偏好或文案修改意见'); return; } b.preference=preference; if (await save()) say('品牌表达偏好已保存'); }
async function clearPreference() { if (!brand()) return; const before=brand().preference; brand().preference=''; if (await save()) { go('brand'); say('品牌偏好已清除'); } else brand().preference=before; }
function renderHistory() { $('#app').innerHTML=head('历史作品','保存在服务端的作品与版本。')+`<div class="card">${db.works.filter(w=>w.brand===current).map(w=>`<div class="historyline row spread"><div><strong>${e(w.result.title)}</strong><br><small>${e(w.result.platform)} · ${e(w.time)} · ${w.result.versions?.length||0} 个文案版本</small></div><button onclick="openWork('${e(w.id)}')">打开并继续修改</button></div>`).join('')||'<div class="empty">还没有保存的作品。</div>'}</div>`; }
function openWork(id) { const w=db.works.find(item=>item.id===id); if (!w) return; if (view==='results') readResult(); current=w.brand; draft=structuredClone(w.draft); results=[structuredClone(w.result)]; selected=0; view='history'; go('results'); }
async function refreshQuota() {
  if (mode==='mock'||!serverReady) return;
  try { const q=await getQuota(); $('#quotaStatus').textContent=q.remaining==null?'':`剩余额度：${q.remaining} 次`; }
  catch { $('#quotaStatus').textContent='额度暂不可用'; }
}
function showAccess() { modal(`<h2>输入访问密码</h2><p>这是应用访问密码，由项目负责人提供。</p><label for="accessKey">访问密码</label><input type="password" id="accessKey" autocomplete="current-password"><p class="error" id="accessError"></p><div class="actions"><button class="primary" onclick="submitAccess()">进入应用</button></div>`); $('#accessKey').focus(); }
async function submitAccess() {
  const button=$('#modal button'); button.disabled=true;
  try { await verifyAccess($('#accessKey').value.trim()); serverReady=true; closeModal(); await connectWorkspace(); await refreshQuota(); say('访问校验通过'); }
  catch (error) { $('#accessError').textContent=error.message; }
  finally { if (button.isConnected) button.disabled=false; }
}
async function loadWorkspace() {
  clearTimeout(autoSaveTimer);studioDraftBrand=null;draftPaused=false;
  const previous=current||(workspaceInfo&&localStorage.getItem('active-brand:'+workspaceInfo.id));
  db=await knowledge('/workspace');
  db.products.forEach(p=>{ p.image=p.image_document_id?'/api/knowledge/brands/'+encodeURIComponent(p.brand)+'/documents/'+encodeURIComponent(p.image_document_id)+'/file':''; });
  current=db.brands.some(b=>b.id===previous)?previous:db.brands[0]?.id;if(current)await primeDraft(current); createCache=null; referencePoster=''; referenceName=''; view=''; go('brand');
}
async function connectWorkspace(){
  workspaceInfo=await knowledge('/workspace-info');
  $('#workspaceStatus').textContent='共享品牌工作空间';
  await loadWorkspace();
}
async function importLegacy() {
  if (!legacyDb?.brands?.length) { say('当前浏览器没有可导入的旧品牌资料。'); return; }
  if (!confirm('将旧品牌、产品和作品导入当前工作空间；同一标识的已有资料会被旧资料覆盖。继续吗？')) return;
  try {
    const imported=structuredClone(legacyDb);
    imported.works=imported.works||[];
    for (const product of imported.products||[]) {
      product.image_document_id='';
    }
    imported.revision=db.revision||0;
    const first=await knowledge('/workspace/sync',{method:'POST',body:imported});
    imported.revision=first.revision;
    for (const product of imported.products||[]) {
      if (!product.image?.startsWith('data:image/')) continue;
      const response=await fetch(product.image),blob=await response.blob(),form=new FormData();
      form.append('file',blob,'legacy-product.'+(blob.type==='image/png'?'png':blob.type==='image/webp'?'webp':'jpg'));
      const uploaded=await knowledge('/brands/'+encodeURIComponent(product.brand)+'/documents?purpose=product_image',{method:'POST',body:form});
      product.image_document_id=uploaded.id; product.image='';
    }
    await knowledge('/workspace/sync',{method:'POST',body:imported});
    await loadWorkspace(); say('品牌、产品、产品图片和历史作品已导入。');
  } catch (error) { await loadWorkspace().catch(()=>{}); say('导入未完全完成：'+error.message); }
}
async function uploadBrandFile(documentId='') {
  const file=$('#brandFile')?.files[0]; if (!file) { say('请选择文件'); return; }
  const form=new FormData(); form.append('file',file);
  try { await knowledge('/brands/'+encodeURIComponent(current)+'/documents?purpose=knowledge&category='+encodeURIComponent($('#uploadCategory')?.value||'品牌资料')+(documentId?'&document_id='+encodeURIComponent(documentId):''),{method:'POST',body:form}); say('文件已上传，请核对解析结果后启用。');closeModal();await loadBrandDocuments(); }
  catch(error) { say(error.message); }
}
function replaceBrandDocument(id){openKnowledgeUpload(id);}
async function previewBrandDocument(id,version) {
  try { const data=await knowledge('/brands/'+encodeURIComponent(current)+'/documents/'+encodeURIComponent(id)+'/versions/'+encodeURIComponent(version));
    modal(`<h2>确认解析结果</h2><p>确认后才会作为本品牌资料参与创作。请核对文件内容。</p><p>${e(data.source_text||'')}</p>${data.brand_candidate?.name?`<label><input type="checkbox" id="applyBrandCandidate"> 使用以下品牌资料</label>${input('candidateBrandName','品牌名称',data.brand_candidate.name)}${area('candidateBrandIntro','品牌介绍',data.brand_candidate.intro||brand().intro)}`:''}<div class="card">${data.chunks.map(c=>`<p><b>${e(c.source_label)}</b>：${e(c.content)}</p>`).join('')}</div>${data.product_candidates?.length?`<h3>确认导入产品（可修改，默认不导入）</h3>${data.product_candidates.map((p,i)=>`<div class="card" data-candidate="${i}"><label><input type="checkbox" class="candidate-selected"> 导入此产品</label><label>更新现有产品（或新建）<select class="candidate-target"><option value="">新建产品</option>${products().map(p=>`<option value="${e(p.id)}">${e(p.name)}</option>`).join('')}</select></label><label>产品名称<input class="candidate-name" value="${e(p.name)}"></label><label>价格<input class="candidate-price" value="${e(p.price)}"></label><label>卖点<input class="candidate-selling" value="${e(p.selling)}"></label></div>`).join('')}`:''}<button onclick="closeModal()">取消</button>${data.version.status==='pending_confirmation'||data.organized&&!data.confirmed?`<button class="primary" onclick="confirmBrandDocument('${e(id)}','${e(version)}')">确认并启用</button>`:''}`);
  } catch(error) { say(error.message); }
}
async function confirmBrandDocument(id,version) { try { const products=[...document.querySelectorAll('[data-candidate]')].filter(row=>row.querySelector('.candidate-selected').checked).map(row=>({id:row.querySelector('.candidate-target')?.value||'',name:row.querySelector('.candidate-name').value.trim(),price:row.querySelector('.candidate-price').value.trim(),selling:row.querySelector('.candidate-selling').value.trim()})); if(products.some(p=>!p.name||!p.selling)){say('请填写选中产品的名称和卖点');return;} await knowledge('/brands/'+encodeURIComponent(current)+'/documents/'+encodeURIComponent(id)+'/versions/'+encodeURIComponent(version)+'/confirm',{method:'POST',body:{products,...($('#applyBrandCandidate')?.checked?{brand:{...brand(),name:$('#candidateBrandName').value.trim(),intro:$('#candidateBrandIntro').value.trim()}}:{})}}); closeModal(); await loadWorkspace(); say('品牌资料已启用'); } catch(error) { say(error.message); } }
async function retryBrandDocument(id,version) { try { await knowledge('/brands/'+encodeURIComponent(current)+'/documents/'+encodeURIComponent(id)+'/versions/'+encodeURIComponent(version)+'/retry',{method:'POST'}); await loadBrandDocuments(); } catch(error) { say(error.message); } }
async function deleteBrandDocument(id) { if (!confirm('删除后该资料及其索引将无法恢复，确定删除？')) return; try { await knowledge('/brands/'+encodeURIComponent(current)+'/documents/'+encodeURIComponent(id),{method:'DELETE'}); await loadWorkspace(); say('资料已删除'); } catch(error) { say(error.message); } }
async function initialize() {
  if (mode==='mock') { $('#modeStatus').textContent='前端本地演示'; return; }
  try {
    const health=await getHealth();
    $('#modeStatus').textContent=health.mock?(health.image_mock?'后端演示模式':'文字演示 · 生图已配置'):(health.image_mock?'文字已配置 · 生图演示':'文字与生图已配置');
    if (health.need_key) {
      const key=sessionStorage.getItem('marketing_access_key');
      if (key) { try { await verifyAccess(key); serverReady=true; } catch { sessionStorage.removeItem('marketing_access_key'); showAccess(); } }
      else showAccess();
    } else serverReady=true;
    if(serverReady)await connectWorkspace();
    await refreshQuota();
  } catch { serverReady=false; $('#modeStatus').textContent='后端未连接'; say('后端未连接，本地资料仍可编辑；启动后端后点击重新连接。'); }
}
Object.assign(window,{go,changeBrand,newBrand,saveBrand,demo,editProduct,saveProduct,fillSuggestion,importProducts,doImport,openSearch,lookupProducts,adoptProduct,cacheCreate,goalFields,clearPoster,generate,runGeneration,cancelJob,selectResult,saveWork,restore,restoreImage,enableImages,requestImage,openReviseImage,submitReviseImage,rewrite,doRewrite,copyText,remember,clearPreference,openWork,closeModal,submitAccess,initialize,importLegacy,uploadBrandFile,replaceBrandDocument,previewBrandDocument,confirmBrandDocument,retryBrandDocument,deleteBrandDocument,loadBrandDocuments});

document.addEventListener('keydown',event=>{ if (event.key==='Escape'&&!$('#accessKey')) closeModal(); });


function renderStudioTools(){if(!current||!workspaceInfo||(view==='brand'&&brandScene==='directory'))return;if(workspaceInfo.reference_data)$('#app').insertAdjacentHTML('afterbegin',`<div class="tip">已接入清理后的品牌产品资料 · 历史价格请核对 · 文案${$('#modeStatus').textContent.includes('演示')?'当前为演示模式':'按模型配置生成'} <button onclick="showPreviewInfo()">数据与运行状态</button><button onclick="showCatalogSources()">当前产品来源</button></div>`);$('#app').insertAdjacentHTML('afterbegin',`<div class="row" style="margin-bottom:18px"><button onclick="restoreStudioDraft()">恢复上次草稿</button><button onclick="showJobs()">任务记录</button><button onclick="showMemories()">品牌记忆</button><span id="draftStatus" class="note"></span></div>`);}
function selectGallery(index){const r=results[selected];r.imageUrl=r.gallery[index].url;renderResults();}
async function exportWork(){await saveWork();const r=results[selected];if(!r?.saved)return;const a=document.createElement('a');a.href='/api/knowledge/brands/'+encodeURIComponent(current)+'/works/'+encodeURIComponent(r.id)+'/export';a.download='营销素材.zip';a.click();}
function scheduleDraft(){clearTimeout(autoSaveTimer);if(!workspaceInfo||!current||draftPaused||!['create','results'].includes(view))return;autoSaveTimer=setTimeout(()=>{autoSaveChain=autoSaveChain.then(persistDraft).catch(error=>say('草稿保存失败：'+error.message));},900);}
async function persistDraft(){if(!workspaceInfo||!current||draftPaused||!['create','results'].includes(view))return;const bid=current;if(view==='create'&&$('#goal')){cacheCreate();createCache.imageMode=$('#imageMode')?.value||'photo';createCache.imageCount=$('#imageCount')?.value||3;}if(view==='results')readResult();if(studioDraftBrand!==bid){const old=await knowledge('/brands/'+encodeURIComponent(bid)+'/draft');if(current!==bid)return;studioDraftBrand=bid;studioDraftRevision=old.revision;}
const payload={createCache,draft,results,selected,view,referencePoster,referenceName};try{const saved=await knowledge('/brands/'+encodeURIComponent(bid)+'/draft',{method:'PUT',body:{revision:studioDraftRevision,payload}});studioDraftRevision=saved.revision;if($('#draftStatus'))$('#draftStatus').textContent='草稿已保存';}catch(error){if(error.status===409)draftPaused=true;throw error;}}
async function restoreStudioDraft(){try{clearTimeout(autoSaveTimer);await autoSaveChain;const data=await knowledge('/brands/'+encodeURIComponent(current)+'/draft');studioDraftBrand=current;studioDraftRevision=data.revision;draftPaused=false;if(!data.payload){say('还没有保存的创作草稿');return;}const p=data.payload;createCache=p.createCache;selectedProductIds=p.createCache?.ids||[];draft=p.draft||{};results=p.results||[];selected=p.selected||0;referencePoster=p.referencePoster||'';referenceName=p.referenceName||'';view='';go(p.view==='results'&&results.length?'results':'create');say('已恢复上次创作');}catch(error){say(error.message);}}
document.addEventListener('input',event=>{if(event.target.closest('#app'))scheduleDraft();});
document.addEventListener('change',event=>{if(event.target.closest('#app'))scheduleDraft();});
let memoryRows=[];
const memoryNames={audience:'目标人群',tone:'表达语气',prohibited:'禁用表达',other:'其他偏好'};
async function showMemories(){try{memoryRows=(await knowledge('/brands/'+encodeURIComponent(current)+'/memories')).memories;modal(`<h2>品牌记忆</h2><p>长期偏好用于后续创作。本次优惠和活动时间请填写在营销需求中。</p>${memoryRows.map((m,i)=>`<div class="historyline"><b>${e(memoryNames[m.kind])}</b><p>${e(m.content)}</p><button onclick="editMemory(${i})">编辑</button><button onclick="deleteMemory('${e(m.id)}')">删除</button></div>`).join('')}<button onclick="editMemory()">添加记忆</button><button onclick="closeModal()">关闭</button>`);}catch(error){say(error.message);}}
function editMemory(index){const m=memoryRows[index]||{};modal(`<h2>编辑品牌记忆</h2><label>类型<select id="memoryKind">${Object.entries(memoryNames).map(([k,n])=>`<option value="${k}" ${m.kind===k?'selected':''}>${n}</option>`).join('')}</select></label>${area('memoryContent','内容',m.content)}<button onclick="saveMemory('${e(m.id||'')}')">确认保存</button><button onclick="closeModal()">取消</button>`);}
async function saveMemory(id){try{await knowledge('/brands/'+encodeURIComponent(current)+'/memories'+(id?'/'+encodeURIComponent(id):''),{method:id?'PUT':'POST',body:{kind:$('#memoryKind').value,content:$('#memoryContent').value.trim()}});await showMemories();}catch(error){say(error.message);}}
async function deleteMemory(id){try{await knowledge('/brands/'+encodeURIComponent(current)+'/memories/'+encodeURIComponent(id),{method:'DELETE'});await showMemories();}catch(error){say(error.message);}}
async function showJobs(){try{const data=await knowledge('/brands/'+encodeURIComponent(current)+'/jobs');modal(`<h2>任务记录</h2><p>刷新页面后，可在此继续查看。失败任务需要你确认后重试。</p>${data.jobs.map(j=>`<div class="historyline"><b>${e({copy:'文案生成',image:'配图生成',organize:'资料整理'}[j.kind])}</b> · ${e(j.status)}<p>${e(j.error||'')}</p><button onclick="resumeJob('${e(j.id)}')">查看结果 / 等待完成</button>${j.status==='failed'?`<button onclick="retryStudioJob('${e(j.id)}')">重试</button>`:''}</div>`).join('')||'<p>暂无任务</p>'}<button onclick="showJobs()">刷新</button><button onclick="closeModal()">关闭</button>`);}catch(error){say(error.message);}}
async function retryStudioJob(id){try{await knowledge('/jobs/'+encodeURIComponent(id)+'/retry',{method:'POST'});await showJobs();}catch(error){say(error.message);}}
async function resumeJob(id){if(controller)return;closeModal();controller=new AbortController();say('正在读取任务；可在任务记录中再次查看');try{const job=await waitJob(id,{signal:controller.signal});if(job.kind==='organize'){say('整理完成，请在品牌文件中查看并确认');await loadBrandDocuments();return;}draft=job.context.draft;current=draft.brand.id;if(job.kind==='copy'){results=adaptContents(job.result);selected=0;}else{const content=job.context.content;Object.assign(content,{gallery:job.result.gallery,imageUrl:job.result.image.url,imageStatus:'succeeded',finalPrompt:job.result.final_prompt});results=[content];selected=0;}controller=null;go('results');scheduleDraft();}catch(error){say(error.message);}finally{controller=null;}}
async function organizeDocument(version){try{say('正在整理文件；任务记录中可继续查看');await startJob(current,'organize',{version_id:version});await loadBrandDocuments();say('整理完成，请查看并确认');}catch(error){say(error.message);}}
Object.assign(window,{filterProducts,bulkProducts,selectGallery,exportWork,restoreStudioDraft,showMemories,editMemory,saveMemory,deleteMemory,showJobs,retryStudioJob,resumeJob,organizeDocument});

async function primeDraft(id){const data=await knowledge('/brands/'+encodeURIComponent(id)+'/draft');if(current===id){studioDraftBrand=id;studioDraftRevision=data.revision;}}

async function showPreviewInfo(){try{const info=await knowledge('/workspace-info');modal(`<h2>共享品牌工作空间</h2><p>品牌资料、产品、作品和草稿保存在同一个工作空间中。</p><p>品牌：${info.brands} 个<br>产品：${info.products} 条<br>已接入原始产品图：${info.product_images} 张</p><p>${e(info.note)}</p><p>文案：${info.copy_mock?'演示模式（尚未配置真实文字模型）':'真实模型'}<br>图片：产品原图排版可直接使用；${info.image_mock?'AI 创意生图尚未配置':'AI 创意生图已配置'}</p><button onclick="closeModal()">关闭</button>`);}catch(error){say(error.message);}}
async function showCatalogSources(){try{const data=await knowledge('/brands/'+encodeURIComponent(current)+'/catalog-sources');modal(`<h2>${e(brand().name)} · 产品来源</h2><p>以下来自原有采集资料，价格和规格未重新在线核验。</p>${data.sources.map(s=>`<div class="historyline"><b>${e(db.products.find(p=>p.id===s.product_id)?.name)}</b><p>${e(s.price_status)}</p>${/^https?:\/\//.test(s.source_url)?`<a target="_blank" rel="noopener noreferrer" href="${e(s.source_url)}">查看原始来源</a>`:''}</div>`).join('')||'<p>当前品牌为新建资料。</p>'}<button onclick="closeModal()">关闭</button>`);}catch(error){say(error.message);}}
Object.assign(window,{showPreviewInfo,showCatalogSources});

let knowledgeTab='overview',libraryMatches=[],documentRequest=0,addRequest=0;
const categories=rows=>[...new Set(rows.map(p=>p.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
const brandComplete=b=>!!(b.intro?.trim()&&b.position?.trim()&&b.style?.trim());
const statusName={active:'已启用',pending_confirmation:'待确认',processing:'解析中',failed:'解析失败',superseded:'历史版本'};
function pagination(p,handler){return `<div class="pager"><span>共 ${p.total} 条 · 第 ${p.page} / ${p.pages} 页</span><div class="row"><button ${p.page<=1?'disabled':''} onclick="${handler}(${p.page-1})">上一页</button><button ${p.page>=p.pages?'disabled':''} onclick="${handler}(${p.page+1})">下一页</button></div></div>`;}
function brandDirectory(){brandScene='directory';go('brand');}
function renderBrand(){if(brandScene==='directory')renderBrandDirectory();else if(brandScene==='editor')renderBrandEditor();else renderBrandKnowledge();}
function renderBrandDirectory(){
  $('#app').innerHTML=head('品牌资料库','先找到已有品牌补充知识，或从头建立自己的品牌。')+`<div class="row spread"><h2>选择已有品牌</h2><div class="row">${workspaceInfo&&current?'<button onclick="restoreStudioDraft()">恢复上次草稿</button>':''}<button class="primary" onclick="newBrand()">＋ 新建我的品牌</button></div></div><form class="filters card" onsubmit="event.preventDefault();applyBrandFilters()"><label>搜索品牌<input id="brandQuery" placeholder="输入品牌名称" value="${e(brandQuery)}"></label><label>产品类别<select id="brandIndustry"><option value="">全部类别</option>${categories(db.products).map(c=>`<option ${brandIndustryFilter===c?'selected':''}>${e(c)}</option>`).join('')}</select></label><label>资料完整度<select id="brandCompleteness"><option value="">全部</option><option value="incomplete" ${brandCompleteFilter==='incomplete'?'selected':''}>待补充</option><option value="complete" ${brandCompleteFilter==='complete'?'selected':''}>已完善</option></select></label><button class="primary">搜索品牌</button><button type="button" onclick="resetBrandFilters()">重置</button></form><div id="brandResults"></div>`;
  renderBrandResults();
}
function applyBrandFilters(){brandQuery=$('#brandQuery').value;brandIndustryFilter=$('#brandIndustry').value;brandCompleteFilter=$('#brandCompleteness').value;renderBrandResults();}
function resetBrandFilters(){brandQuery='';brandIndustryFilter='';brandCompleteFilter='';renderBrandDirectory();}
function renderBrandResults(){const rows=db.brands.filter(b=>normalize(b.name).includes(normalize(brandQuery))&&(!brandIndustryFilter||db.products.some(p=>p.brand===b.id&&p.category===brandIndustryFilter))&&(!brandCompleteFilter||(brandCompleteFilter==='complete'?brandComplete(b):!brandComplete(b))));
  $('#brandResults').innerHTML=`<p class="note" role="status">找到 ${rows.length} 个品牌</p><div class="brand-grid">${rows.map(b=>{const ps=db.products.filter(p=>p.brand===b.id&&!p.archived);return `<section class="card brand-tile"><span class="badge">${brandComplete(b)?'资料已完善':'有资料待补充'}</span><h2>${e(b.name)}</h2><p class="clamp">${e(b.intro)}</p><p>${ps.length} 款产品 · ${e(categories(ps).slice(0,3).join(' / ')||'尚无产品分类')}</p><button class="primary" onclick="openBrandKnowledge('${e(b.id)}')">进入品牌知识页</button></section>`;}).join('')||'<div class="card empty">没有匹配品牌，可调整筛选或新建自己的品牌。</div>'}</div>`;
}
async function openBrandKnowledge(id){await changeBrand(id);brandScene='knowledge';knowledgeTab='overview';go('brand');}
function brandKnowledgeTab(tab){knowledgeTab=tab;renderBrandKnowledge();}
function knowledgePanel(){return `<section class="card"><div class="row spread"><div><h2>知识资料</h2><p>集中管理品牌手册、产品说明和活动规则。产品图片在产品详情中维护。</p></div><button class="primary" onclick="openKnowledgeUpload()">＋ 补充资料</button></div><form class="filters" onsubmit="event.preventDefault();filterDocuments()"><label>搜索资料<input id="documentQuery" value="${e(docQuery)}" placeholder="按文件名搜索"></label><label>资料分类<select id="documentCategory"><option value="">全部分类</option>${['品牌资料','产品说明','活动规则','其他'].map(c=>`<option ${docCategory===c?'selected':''}>${c}</option>`).join('')}</select></label><button>筛选资料</button><button type="button" onclick="loadBrandDocuments()">刷新状态</button></form><div id="brandDocuments" role="status">正在读取知识资料…</div></section>`;}
function renderBrandKnowledge(){const b=brand();if(!b){brandDirectory();return;}const ps=products();const missing=[!b.position&&'品牌定位',!b.style&&'表达风格',!ps.length&&'产品资料'].filter(Boolean);
  $('#app').innerHTML=head(b.name+' · 品牌知识','查看已有资料，补充自己的表达与商品事实。')+`<button onclick="brandDirectory()">← 返回品牌库</button><div class="tabs knowledge-tabs">${[['overview','品牌概况'],['supplement','待补充资料'],['documents','知识资料']].map(([key,title])=>`<button class="${knowledgeTab===key?'active':''}" onclick="brandKnowledgeTab('${key}')">${title}</button>`).join('')}</div>`;
  if(knowledgeTab==='overview')$('#app').insertAdjacentHTML('beforeend',`<div class="grid"><section class="card"><span class="badge">${b.id.startsWith('brand_')?'已有来源参考资料':'自建品牌资料'}</span><h2>品牌概况</h2><p>${e(b.intro)}</p><p>品牌定位：${e(b.position||'待补充')}<br>表达风格：${e(b.style||'待补充')}</p><button onclick="brandKnowledgeTab('supplement')">完善品牌信息</button></section><section class="card"><h2>知识概览</h2><p>${ps.length} 款在用产品 · ${ps.filter(p=>p.image_document_id).length} 款有产品图</p><p>${missing.length?'建议补充：'+e(missing.join('、')):'主要品牌信息已补齐，可继续维护知识资料。'}</p><button onclick="go('products')">完善已有产品</button><button onclick="brandKnowledgeTab('documents')">管理知识资料</button><button onclick="showMemories()">管理表达记忆</button></section></div><p class="note">已有来源资料保留在原始数据包中；此处的补充用于当前工作空间。产品价格为历史来源价格，发布前请核对。</p>`);
  if(knowledgeTab==='supplement')$('#app').insertAdjacentHTML('beforeend',`<section class="card"><h2>补充品牌知识</h2><p>核对已有内容后补充定位和表达风格，或上传文档整理。</p>${input('bn','品牌名称 *',b.name)}${area('bi','品牌介绍 *',b.intro)}<div class="two">${input('bp','品牌定位',b.position)}${input('bs','表达风格',b.style)}</div><p class="error" id="be"></p><div class="actions"><button onclick="openKnowledgeUpload()">上传资料补充</button><button class="primary" onclick="saveBrand()">保存品牌补充</button></div></section>`);
  if(knowledgeTab==='documents'){$('#app').insertAdjacentHTML('beforeend',knowledgePanel());loadBrandDocuments();}
}
function filterDocuments(){docQuery=$('#documentQuery').value;docCategory=$('#documentCategory').value;docPage=1;loadBrandDocuments();}
function documentPage(page){docPage=page;loadBrandDocuments();}
async function loadBrandDocuments(){const id=current,host=$('#brandDocuments'),request=++documentRequest;if(!host)return;try{const params=new URLSearchParams({purpose:'knowledge',q:docQuery,category:docCategory,page:docPage,page_size:10});const data=await knowledge('/brands/'+encodeURIComponent(id)+'/documents?'+params);if(!host.isConnected||current!==id||request!==documentRequest)return;docRows=data.documents;docPage=data.page;
  host.innerHTML=data.documents.map(d=>{const v=d.versions[0];return `<div class="document-row"><div><strong>${e(d.name)}</strong><p class="note">${e(d.category||'品牌资料')} · ${e(statusName[v?.status]||'待处理')} · ${e(new Date(Number(v?.created||d.created)/1e6).toLocaleDateString())}</p></div><button onclick="documentDetails('${e(d.id)}')">查看详情</button></div>`;}).join('')||'<div class="empty">暂无符合条件的知识资料。产品图片已归入对应产品，不在这里重复展示。</div>';host.insertAdjacentHTML('beforeend',pagination(data,'documentPage'));
}catch(error){if(host.isConnected)host.textContent=error.message;}}
function openKnowledgeUpload(id=''){modal(`<h2>${id?'上传资料新版本':'补充品牌知识'}</h2><p>上传后核对解析内容，再确认用于创作。产品照片请在产品详情中上传。</p><label>资料分类<select id="uploadCategory">${['品牌资料','产品说明','活动规则','其他'].map(c=>`<option>${c}</option>`).join('')}</select></label><label>选择文件<input type="file" id="brandFile" accept=".txt,.md,.csv,.pdf,.docx,.png,.jpg,.jpeg,.webp"></label><p class="note">支持文档、表格和扫描图片，单文件最大 10MB。</p><div class="actions"><button onclick="closeModal()">取消</button><button class="primary" onclick="uploadKnowledge('${e(id)}')">上传并解析</button></div>`);}
async function uploadKnowledge(id){await uploadBrandFile(id);if(!$('#brandFile')){if(view==='brand'){knowledgeTab='documents';if(brandScene!=='editor')brandScene='knowledge';renderBrand();}}}
function documentDetails(id){docDetails=docRows.find(d=>d.id===id);if(!docDetails)return;const d=docDetails;modal(`<h2>${e(d.name)}</h2><p>${e(d.category||'品牌资料')} · ${d.versions.length} 个版本</p>${d.versions.map(v=>`<div class="historyline"><strong>${e(v.filename)}</strong><p>${e(statusName[v.status]||v.status)} · ${e(new Date(Number(v.created)/1e6).toLocaleString())}</p>${v.error?`<p class="error">${e(v.error)}</p>`:''}<button onclick="previewBrandDocument('${e(d.id)}','${e(v.id)}')">${v.status==='pending_confirmation'?'核对并确认':'查看解析内容'}</button><button onclick="organizeDocument('${e(v.id)}')">智能整理</button>${v.status==='failed'?`<button onclick="retryBrandDocument('${e(d.id)}','${e(v.id)}')">重试解析</button>`:''}</div>`).join('')}<div class="actions"><button onclick="openKnowledgeUpload('${e(d.id)}')">上传新版本</button><button onclick="deleteBrandDocument('${e(d.id)}')">删除资料</button><button onclick="closeModal()">关闭</button></div>`);}

function catalogFilters(prefix,state,rows){return `<label>搜索名称或关键词<input id="${prefix}Query" value="${e(state.query)}" placeholder="名称、分类、卖点"></label><label>分类<select id="${prefix}Category"><option value="">全部分类</option>${categories(rows).map(c=>`<option ${state.category===c?'selected':''}>${e(c)}</option>`).join('')}</select></label><label>产品图<select id="${prefix}Image"><option value="">全部</option><option value="present" ${state.image==='present'?'selected':''}>有图</option><option value="missing" ${state.image==='missing'?'selected':''}>缺图</option></select></label><label>资料完整度<select id="${prefix}Complete"><option value="">全部</option><option value="complete" ${state.completeness==='complete'?'selected':''}>已完善</option><option value="incomplete" ${state.completeness==='incomplete'?'selected':''}>待补充</option></select></label>`;}
function readCatalogFilters(prefix,state){Object.assign(state,{query:$('#'+prefix+'Query').value,category:$('#'+prefix+'Category').value,image:$('#'+prefix+'Image').value,completeness:$('#'+prefix+'Complete').value,page:1});}
function renderProducts(){if(needBrand())return;const rows=db.products.filter(p=>p.brand===current);$('#app').innerHTML=head('产品库','搜索、筛选后维护产品，每页展示 20 款。')+chooseBrand()+`<form class="card filters" onsubmit="event.preventDefault();filterProducts()">${catalogFilters('library',library,rows)}<label>状态<select id="libraryStatus"><option value="active" ${library.status==='active'?'selected':''}>在用</option><option value="archived" ${library.status==='archived'?'selected':''}>已归档</option><option value="all" ${library.status==='all'?'selected':''}>全部</option></select></label><label>排序<select id="librarySort"><option value="updated" ${library.sort==='updated'?'selected':''}>最近更新</option><option value="name" ${library.sort==='name'?'selected':''}>名称排序</option></select></label><button class="primary">搜索产品</button><button type="button" onclick="resetLibrary()">重置</button></form><div class="row spread"><div class="row"><button class="primary" onclick="openAddProduct()">＋ 添加产品</button><button onclick="importProducts()">批量导入 JSON</button><button onclick="go('create')">开始营销创作 →</button></div><div class="row"><button onclick="libraryLayout('cards')" aria-pressed="${library.layout==='cards'}">卡片</button><button onclick="libraryLayout('list')" aria-pressed="${library.layout==='list'}">列表</button></div></div><div class="row bulkbar"><span id="bulkCount"></span><button onclick="bulkProducts('category')">批量分类</button><button onclick="bulkProducts('archive')">归档所选</button><button onclick="bulkProducts('restore')">恢复所选</button><button onclick="clearBulk()">清空选择</button></div><div id="libraryResults"></div>`;renderLibraryResults();}
function filterProducts(){readCatalogFilters('library',library);library.status=$('#libraryStatus').value;library.sort=$('#librarySort').value;renderLibraryResults();}
function resetLibrary(){library={query:'',category:'',image:'',completeness:'',status:'active',sort:'updated',page:1,layout:library.layout};renderProducts();}
function libraryPage(page){library.page=page;renderLibraryResults();$('#libraryResults').scrollIntoView({block:'start'});}
function libraryLayout(layout){library.layout=layout;renderProducts();}
function productThumb(p){return p.image?`<img loading="lazy" src="${e(p.image)}" alt="${e(p.name)}">`:'<span class="note">暂无产品图</span>';}
function renderLibraryResults(){libraryMatches=filterCatalog(db.products.filter(p=>p.brand===current),library);const page=pageOf(libraryMatches,library.page);library.page=page.page;$('#bulkCount').textContent=`已选 ${bulkIds.size} 款（跨页保留）`;$('#libraryResults').innerHTML=pagination(page,'libraryPage')+`<div class="${library.layout==='list'?'catalog-list':'catalog-grid'}">${page.rows.map(p=>`<section class="product catalog-product" data-product-id="${e(p.id)}"><label class="catalog-check"><input type="checkbox" class="bulkProduct" value="${e(p.id)}" ${bulkIds.has(p.id)?'checked':''} onchange="toggleBulk(this.value,this.checked)"> 选择</label><div class="productimg">${productThumb(p)}</div><div class="product-description"><h3>${e(p.name)}</h3><p>${e(p.category||'未分类')} · ${e(p.price||'价格待补充')}</p><p class="clamp">${e(p.selling)}</p><span class="badge">${p.archived?'已归档':completeProduct(p)?'资料已完善':'有资料待补充'}</span></div><button onclick="editProduct('${e(p.id)}')">编辑资料</button></section>`).join('')||'<div class="card empty">没有匹配产品。调整筛选，或添加新产品。</div>'}</div>`+pagination(page,'libraryPage');}
function toggleBulk(id,checked){if(checked)bulkIds.add(id);else bulkIds.delete(id);$('#bulkCount').textContent=`已选 ${bulkIds.size} 款（跨页保留）`;}
function clearBulk(){bulkIds.clear();renderLibraryResults();}
async function bulkProducts(action){const rows=db.products.filter(p=>p.brand===current&&bulkIds.has(p.id));if(!rows.length){say('请先选择产品');return;}const category=action==='category'?prompt('填写分类名称'):null;if(action==='category'&&category===null)return;for(const p of rows){if(action==='category')p.category=category.trim();else p.archived=action==='archive';}if(await save()){bulkIds.clear();renderProducts();say('产品已批量更新');}}
function openAddProduct(){addMatches=[];modal(`<h2>添加产品</h2><p>先搜索当前品牌，避免重复添加。也可查询已有参考目录。</p><form onsubmit="event.preventDefault();searchAddProducts()"><label>产品名称<input id="addProductQuery" placeholder="输入名称或关键词" autocomplete="off"></label><div class="actions"><button>搜索已有产品</button><button type="button" onclick="searchReferenceProducts()">查参考目录</button></div></form><div id="addProductResults" role="status"><p>输入名称开始查找。</p></div><div class="actions"><button onclick="closeModal()">取消</button><button onclick="editProduct('__new__')">未找到，手动新建</button></div>`);$('#addProductQuery').addEventListener('input',searchAddProducts);$('#addProductQuery').focus();}
function searchAddProducts(){++addRequest;const q=normalize($('#addProductQuery').value);addMatches=db.products.filter(p=>p.brand===current&&normalize(p.name).includes(q)).slice(0,10);$('#addProductResults').innerHTML=!q?'<p>输入名称开始查找。</p>':addMatches.map(p=>`<div class="document-row"><div><strong>${e(p.name)}</strong><p>${p.archived?'已归档':'当前品牌已有'} · ${e(p.price||'价格待补充')}</p></div><button onclick="editProduct('${e(p.id)}')">编辑已有产品</button></div>`).join('')||'<p>当前品牌未找到同名产品，可查参考目录或手动新建。</p>';}
async function searchReferenceProducts(){const input=$('#addProductQuery'),host=$('#addProductResults'),q=input.value.trim(),request=++addRequest;if(!q){host.textContent='请输入名称';return;}host.textContent='正在搜索参考目录…';try{const data=await searchProducts(current,q,false);if(!host.isConnected||request!==addRequest)return;addMatches=data.products;host.innerHTML=addMatches.map((p,i)=>{const existing=db.products.find(x=>x.brand===current&&normalize(x.name)===normalize(p.name));const other=p.brand&&normalize(p.brand)!==normalize(brand().name);return `<div class="document-row"><div><strong>${e(p.name)}</strong><p>${e(p.brand||brand().name)} · ${e(p.price||'价格待核对')}</p></div>${other?'<span class="note">其他品牌，请切换品牌后维护</span>':`<button onclick="${existing?`editProduct('${e(existing.id)}')`:`useReferenceProduct(${i})`}">${existing?'编辑已有产品':'核对并添加'}</button>`}</div>`;}).join('')||'<p>未找到，可手动新建。</p>';}catch(error){if(host.isConnected)host.textContent=error.message;}}
function useReferenceProduct(index){const p=addMatches[index];if(!p||p.brand&&normalize(p.brand)!==normalize(brand().name))return;editProduct('__new__');$('#pn').value=p.name;$('#pp').value=p.price||'';$('#ps').value=(p.selling_points||[]).join('、');}

function selectedProductCards(){const rows=selectedProductIds.map(id=>products().find(p=>p.id===id)).filter(Boolean);return `<p id="campaignSelectedCount" role="status">已选 ${rows.length} / 10 款产品</p>`+(rows.length?rows.map(p=>`<div class="selected-product"><div class="selected-thumb">${productThumb(p)}</div><div><strong>${e(p.name)}</strong><p>${e(p.price||'价格待补充')} · ${e(p.category||'未分类')}</p></div><button onclick="removeCampaignProduct('${e(p.id)}')">移除</button></div>`).join(''):'<div class="empty">尚未选择产品，点击“选择产品”进行搜索和筛选。</div>');}
function removeCampaignProduct(id){selectedProductIds=selectedProductIds.filter(x=>x!==id);$('#createProductOptions').innerHTML=selectedProductCards();cacheCreate();scheduleDraft();}
function openProductPicker(){cacheCreate();picker={query:'',category:'',image:'',completeness:'',status:'active',sort:'name',page:1,tab:'all',ids:[...selectedProductIds],brand:current};modal(`<div class="row spread"><h2>选择本次营销产品</h2><button onclick="closeModal()">取消</button></div><p>${e(brand().name)} · 筛选和翻页不会丢失勾选，最多选择 10 款。</p><div class="tabs"><button id="pickerAllTab" onclick="pickerTab('all')">全部产品</button><button id="pickerSelectedTab" onclick="pickerTab('selected')">已选产品</button></div><form class="filters" onsubmit="event.preventDefault();filterPicker()">${catalogFilters('picker',picker,products())}<button>筛选产品</button><button type="button" onclick="resetPicker()">重置筛选</button></form><p id="pickerError" class="error" role="alert"></p><div id="pickerResults"></div><div class="picker-footer"><span id="pickerCount" role="status"></span><button class="primary" onclick="confirmProductPicker()">确认加入</button></div>`);$('#modal .modal').classList.add('wide-modal');renderPickerResults();}
function renderPickerResults(){if(!picker||picker.brand!==current)return;const rows=filterCatalog(products(),picker).filter(p=>picker.tab!=='selected'||picker.ids.includes(p.id));const page=pageOf(rows,picker.page);picker.page=page.page;$('#pickerCount').textContent=`已选 ${picker.ids.length} / 10 款`;$('#pickerAllTab').classList.toggle('active',picker.tab==='all');$('#pickerSelectedTab').classList.toggle('active',picker.tab==='selected');$('#pickerResults').innerHTML=`<div class="picker-list">${page.rows.map(p=>`<label class="picker-row"><input type="checkbox" name="pickerProduct" value="${e(p.id)}" ${picker.ids.includes(p.id)?'checked':''} onchange="togglePicker(this.value,this.checked,this)"><span class="selected-thumb">${productThumb(p)}</span><span><strong>${e(p.name)}</strong><small>${e(p.category||'未分类')} · ${e(p.price||'价格待补充')}</small></span></label>`).join('')||'<p class="empty">没有符合条件的产品。</p>'}</div>`+pagination(page,'pickerPage');}
function filterPicker(){readCatalogFilters('picker',picker);renderPickerResults();}
function resetPicker(){Object.assign(picker,{query:'',category:'',image:'',completeness:'',page:1});$('#pickerQuery').value='';$('#pickerCategory').value='';$('#pickerImage').value='';$('#pickerComplete').value='';renderPickerResults();}
function pickerPage(page){picker.page=page;renderPickerResults();$('#pickerResults').scrollIntoView({block:'start'});}
function pickerTab(tab){picker.tab=tab;picker.page=1;renderPickerResults();}
function togglePicker(id,checked,input){const result=toggleSelected(picker.ids,id,checked);$('#pickerError').textContent=result.overflow?'每次最多选择 10 款产品，请先取消一款。':'';if(result.overflow){input.checked=false;return;}picker.ids=result.ids;if(picker.tab==='selected')renderPickerResults();else $('#pickerCount').textContent=`已选 ${picker.ids.length} / 10 款`;}
function confirmProductPicker(){if(picker.brand!==current)return;selectedProductIds=picker.ids.filter(id=>products().some(p=>p.id===id));closeModal();$('#createProductOptions').innerHTML=selectedProductCards();cacheCreate();scheduleDraft();}
Object.assign(window,{brandDirectory,renderBrand,openBrandKnowledge,brandKnowledgeTab,applyBrandFilters,resetBrandFilters,filterDocuments,documentPage,openKnowledgeUpload,uploadKnowledge,documentDetails,filterProducts,resetLibrary,libraryPage,libraryLayout,toggleBulk,clearBulk,bulkProducts,openAddProduct,searchAddProducts,searchReferenceProducts,useReferenceProduct,openProductPicker,removeCampaignProduct,filterPicker,resetPicker,pickerPage,pickerTab,togglePicker,confirmProductPicker});

go('brand'); initialize();
