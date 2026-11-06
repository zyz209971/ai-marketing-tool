import {generateCampaign,rewriteContent,generateImage,reviseImage,searchProducts,getHealth,getQuota,verifyAccess,mode} from './services/api.js';

const $ = s=>document.querySelector(s);
const e = s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = ()=>globalThis.crypto?.randomUUID?.()||('local_'+Date.now().toString(36)+Math.random().toString(36).slice(2));
let db;
try { db=JSON.parse(localStorage.getItem('inspiration-v2')); } catch {}
if (!db||!Array.isArray(db.brands)||!Array.isArray(db.products)||!Array.isArray(db.works)) db={brands:[],products:[],works:[]};
let current=db.brands[0]?.id,view='brand',draft={},results=[],selected=0,toastTimer;
let controller=null,serverReady=mode==='mock',retrievedProducts=[],suggestTimer,suggestController;
let referencePoster='',referenceName='',createCache=null;
let createMatches=[],createSearchTimer,createSearchController;
const brand = ()=>db.brands.find(b=>b.id===current);
const products = ()=>db.products.filter(p=>p.brand===current);

function save() {
  try { localStorage.setItem('inspiration-v2',JSON.stringify(db)); return true; }
  catch { say('保存失败：浏览器空间不足，请改用更小的参考海报或产品图片。'); return false; }
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
  view=next;
  $('#nav').innerHTML=[['brand','◈　品牌资料'],['products','▦　产品库'],['create','✧　营销创作'],['history','▤　历史作品']].map(([key,label])=>`<button class="${next===key?'active':''}" onclick="go('${key}')">${label}</button>`).join('');
  ({brand:renderBrand,products:renderProducts,create:renderCreate,results:renderResults,history:renderHistory}[next])();
  window.scrollTo(0,0);
}
function changeBrand(id) { const next=view; current=id; createCache=null; referencePoster=''; referenceName=''; view=''; go(next); }
function newBrand() { current=null; createCache=null; go('brand'); }
function renderBrand() {
  const b=brand()||{};
  $('#app').innerHTML=head('让每一次表达，都像你的品牌','品牌定位、产品资料和表达偏好，将用于这一次创作。')+`<div class="row" style="margin-bottom:20px">${db.brands.map(x=>`<button onclick="changeBrand('${e(x.id)}')">${e(x.name)}</button>`).join('')}<button onclick="newBrand()">＋ 新建品牌</button><button onclick="demo()">填入示例资料</button></div>
    <div class="grid"><section class="card"><h2>品牌基本资料</h2>${input('bn','品牌名称 *',b.name)}${area('bi','品牌介绍 *',b.intro)}<div class="two">${input('bp','品牌定位',b.position)}${input('bs','表达风格',b.style)}</div>
    <label for="bf">品牌资料文件（仅记录文件名，不解析内容）</label><input type="file" multiple id="bf"><small>${e((b.files||[]).join('、'))}</small><p class="error" id="be"></p><div class="actions"><button class="primary" onclick="saveBrand()">保存品牌</button></div></section>
    <div><div class="hero"><span class="eyebrow">从品牌开始</span><h2>少一些重复输入，<br>多一点创作空间。</h2><p>整理品牌资料，带着已经确认的产品事实开始创作。</p></div><div class="card" style="margin-top:20px"><h3>品牌偏好记忆</h3><p>${e(b.preference||'可在作品页确认后保存品牌的表达偏好。')}</p><button onclick="go('products')">管理产品资料 →</button></div></div></div>`;
}
function saveBrand() {
  const name=$('#bn').value.trim(),intro=$('#bi').value.trim();
  if (!name||!intro) { $('#be').textContent='请填写品牌名称和介绍。'; return; }
  const old=brand(),b={...(old||{id:uid()}),name,intro,position:$('#bp').value,style:$('#bs').value,files:[...(old?.files||[]),...[...$('#bf').files].map(f=>f.name)]};
  if (old) Object.assign(old,b); else db.brands.push(b);
  current=b.id; if (save()) say('品牌资料已保存到当前浏览器'); go('brand');
}
function demo() {
  const id=uid(); db.brands.push({id,name:'拾光烘焙（示例）',intro:'围绕日常下午茶与分享场景的烘焙品牌。',position:'日常下午茶',style:'温暖自然',files:[]});
  db.products.push({id:uid(),brand:id,name:'草莓巴斯克（示例）',price:'38 元（示例）',selling:'草莓风味、适合分享',image:''},{id:uid(),brand:id,name:'原味曲奇（示例）',price:'28 元（示例）',selling:'原味、下午茶搭配',image:''});
  current=id; createCache=null; if (save()) say('示例已加入，生成前请核对资料'); go('brand');
}
function renderProducts() {
  if (needBrand()) return;
  $('#app').innerHTML=head('产品库','可以手动填写，也可以从现有产品知识库检索后加入。')+chooseBrand()+`<div class="row" style="margin:20px 0"><button class="primary" onclick="editProduct()">＋ 添加产品</button><button onclick="importProducts()">批量导入 JSON</button><button onclick="openSearch()">检索产品知识库</button><button onclick="go('create')">开始营销创作 →</button></div><div class="three">${products().map(p=>`<div class="card product"><div class="productimg">${p.image?`<img src="${e(p.image)}" alt="${e(p.name)}">`:'◒'}</div><h3>${e(p.name)}</h3><p>${e(p.price||'未填写价格')}<br>${e(p.selling)}</p><button onclick="editProduct('${e(p.id)}')">编辑资料</button></div>`).join('')||'<div class="card empty">添加第一款产品，或检索已有资料。</div>'}</div>`;
}
function editProduct(id='') {
  const p=db.products.find(item=>item.id===id)||{};
  modal(`<h2>${id?'编辑':'添加'}产品</h2><div class="suggest-wrap">${input('pn','产品名称 *',p.name,'输入名称，检索已有产品')}<div id="suggest" class="suggest" hidden></div></div>${input('pp','价格（选填）',p.price)}${area('ps','主要卖点 *',p.selling)}<p class="note" id="lookupHint"></p><label for="pi">产品图片（仅本地保存，最大 1MB）</label><input type="file" id="pi" accept="image/png,image/jpeg,image/webp"><p class="error" id="pe"></p><div class="actions"><button onclick="closeModal()">取消</button><button class="primary" onclick="saveProduct('${e(id)}')">保存产品</button></div>`);
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
  const p=retrievedProducts[index]; if (!p) return;
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
  const old=db.products.find(p=>p.id===id); let image=old?.image||'';
  try { if ($('#pi').files[0]) image=await readFile($('#pi').files[0],1024*1024); }
  catch (error) { $('#pe').textContent=error.message; return; }
  const p={...(old||{}),id:id||uid(),brand:current,name,price:$('#pp').value,selling,image};
  if (old) Object.assign(old,p); else db.products.push(p);
  if (!save()) return; closeModal(); go(view==='create'?'create':'products');
}
function importProducts() { modal(`<h2>批量导入产品</h2><p>粘贴 JSON 数组，最多 50 款，导入当前品牌。</p><small>[{"name":"产品名称","price":"38元","selling":"商品卖点"}]</small><textarea id="bulk"></textarea><p class="error" id="bulkerr"></p><div class="actions"><button onclick="closeModal()">取消</button><button class="primary" onclick="doImport()">导入</button></div>`); }
function doImport() {
  try {
    const rows=JSON.parse($('#bulk').value);
    if (!Array.isArray(rows)||!rows.length||rows.length>50||rows.some(p=>typeof p.name!=='string'||!p.name.trim()||typeof p.selling!=='string'||!p.selling.trim()||p.price!=null&&typeof p.price!=='string')) throw Error();
    db.products.push(...rows.map(p=>({id:uid(),brand:current,name:p.name,price:p.price||'',selling:p.selling,image:''})));
    if (save()) { closeModal(); go('products'); say('产品已导入'); }
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
function adoptProduct(index) {
  const p=retrievedProducts[index]; if (!p?.name||!p.selling_points?.length) { say('产品缺少名称或卖点，请手动补充。'); return; }
  if (products().some(x=>x.name===p.name)) { say('当前品牌已有同名产品，请在产品库中编辑。'); return; }
  db.products.push({id:uid(),serverId:p.id,brand:current,name:p.name,price:p.price||'',selling:p.selling_points.join('、'),image:''});
  if (save()) { closeModal(); go('products'); say('已加入，请核对该产品是否属于当前品牌'); }
}
function cacheCreate() {
  createCache={brand:current,goal:$('#goal').value,ids:[...document.querySelectorAll('[name=product]:checked')].map(x=>x.value),plats:[...document.querySelectorAll('[name=platform]:checked')].map(x=>x.value),merge:$('#merge').value,format:$('#format').value,points:$('#points').value,style:$('#style').value,rules:$('#rules')?.value||'',dates:$('#dates')?.value||'',theme:$('#theme')?.value||''};
}
function productChoices(ids=[]) {
  return products().map(p=>`<label class="pick"><input type="checkbox" name="product" value="${e(p.id)}" ${ids.includes(p.id)?'checked':''}><strong>${e(p.name)}</strong><small>${e(p.price)} · ${e(p.selling)}</small></label>`).join('')||'<p>输入产品名称搜索已有资料，或手动添加产品。</p>';
}
function renderCreateMatches(rows) {
  const host=$('#createProductSuggestions');
  if (!host) return;
  createMatches=rows;
  host.innerHTML=rows.map((p,index)=>`<button type="button" onclick="selectCreateProduct(${index})"><strong>${e(p.name)}</strong><small>${e(p.brand||'')} · ${e(p.price||'价格待填')} · ${e(p.localId?'当前品牌产品':p.source==='product_rag'?'产品 RAG':'产品知识库')}</small></button>`).join('');
  host.hidden=!rows.length;
}
function searchCreateProducts() {
  clearTimeout(createSearchTimer); createSearchController?.abort();
  const query=$('#createProductQuery').value.trim(),host=$('#createProductSuggestions'),hint=$('#createLookupHint'),brandId=current;
  if (!query) { renderCreateMatches([]); hint.textContent='输入一个字即可联想，点击候选会自动选中产品。'; return; }
  const local=products().filter(p=>p.name.toLowerCase().includes(query.toLowerCase())).map(p=>({localId:p.id,name:p.name,brand:brand().name,price:p.price,selling_points:p.selling.split(/[、，,]/).filter(Boolean)}));
  renderCreateMatches(local); hint.textContent='正在检索产品知识库…';
  createSearchTimer=setTimeout(async()=>{
    const requestController=new AbortController(); createSearchController=requestController;
    try {
      const response=await searchProducts(brandId,query,false,{signal:requestController.signal});
      if (!host.isConnected||current!==brandId||$('#createProductQuery')?.value.trim()!==query) return;
      if (!Array.isArray(response.products)) throw Error('产品检索结果格式不正确。');
      const rows=[...local],seen=new Set(local.map(p=>JSON.stringify([p.brand,p.name])));
      for (const p of response.products) {
        const key=JSON.stringify([p.brand||'',p.name]);
        if (!seen.has(key)) { seen.add(key); rows.push(p); }
      }
      renderCreateMatches(rows.slice(0,15));
      hint.textContent=rows.length?'点击候选自动加入并选中，请核对品牌、价格和卖点。':'没有找到匹配产品，可以点击“添加产品”手动填写。';
    } catch (error) {
      if (host.isConnected&&current===brandId&&error.name!=='AbortError') hint.textContent='知识库检索暂不可用：'+error.message+(local.length?'；仍可选择当前品牌的匹配产品。':'');
    }
  },250);
}
function selectCreateProduct(index) {
  const candidate=createMatches[index]; if (!candidate||view!=='create') return;
  const ids=[...document.querySelectorAll('[name=product]:checked')].map(item=>item.value);
  let product=products().find(p=>p.id===candidate.localId)||products().find(p=>p.name===candidate.name);
  if ((!product||!ids.includes(product.id))&&ids.length>=10) { say('每次最多选择 10 款产品，请先取消一款。'); return; }
  if (!product) {
    if (!candidate.name||!Array.isArray(candidate.selling_points)||!candidate.selling_points.length) { say('该候选缺少名称或卖点，请通过“添加产品”补齐资料。'); return; }
    product={id:uid(),serverId:candidate.id,brand:current,name:candidate.name,price:candidate.price||'',selling:candidate.selling_points.join('、'),image:''};
    db.products.push(product);
    if (!save()) { db.products.pop(); return; }
  }
  if (!ids.includes(product.id)) ids.push(product.id);
  $('#createProductOptions').innerHTML=productChoices(ids);
  clearTimeout(createSearchTimer); createSearchController?.abort();
  $('#createProductQuery').value=''; renderCreateMatches([]);
  $('#createLookupHint').textContent='已选择「'+product.name+'」，可在下方核对价格与卖点。';
  cacheCreate();
}
function renderCreate() {
  if (needBrand()) return;
  const c=createCache?.brand===current?createCache:null;
  $('#app').innerHTML=head('今天，想为品牌讲些什么？','选择产品、营销目的和平台，文案与图片可以独立生成。')+`<div class="step"><b>01　选择创作需求</b><span>02　生成内容</span><span>03　修改与保存</span></div><div class="grid"><section>
    <div class="card"><h2>01　品牌与营销目的</h2>${chooseBrand()}<label for="goal">营销目的</label><select id="goal" onchange="goalFields()">${['新品推广','促销','品牌曝光','节日活动'].map(s=>`<option ${c?.goal===s?'selected':''}>${s}</option>`).join('')}</select><div id="goalfields"></div></div>
    <div class="card"><div class="row spread"><h2>02　相关产品</h2><button onclick="cacheCreate();editProduct()">＋ 添加产品</button></div><div class="suggest-wrap">${input('createProductQuery','模糊搜索产品','','输入部分产品名称，例如：茶、奶茶')}<div id="createProductSuggestions" class="suggest" hidden></div></div><p class="note" id="createLookupHint" role="status">输入一个字即可联想，点击候选会自动选中产品。</p><p class="note">品牌曝光可以不选产品；每次最多选择 10 款。</p><div id="createProductOptions">${productChoices(c?.ids||[])}</div><label for="merge">多产品生成方式</label><select id="merge"><option value="merge">合并为一份活动素材</option><option value="separate" ${c?.merge==='separate'?'selected':''}>每款产品分别生成</option></select></div>
    <div class="card"><h2>03　平台与内容形式</h2><div class="three">${['小红书','抖音','微信公众号'].map(p=>`<label class="pick"><input type="checkbox" name="platform" value="${p}" ${(c?c.plats.includes(p):p==='小红书')?'checked':''}><strong>${p}</strong></label>`).join('')}</div><label for="format">内容形式</label><select id="format">${['仅文案','图文','仅图片'].map(s=>`<option ${c?.format===s?'selected':''}>${s}</option>`).join('')}</select>${area('points','补充卖点（选填）',c?.points)}${input('style','表达偏好',c?.style??brand().preference??brand().style)}
    <label for="poster">参考海报（选填，PNG / JPEG / WebP，最大 4MB）</label><div id="drop" class="file-drop"><span id="posterName">${e(referenceName||'点击或拖拽图片到这里')}</span><input type="file" id="poster" accept="image/png,image/jpeg,image/webp"><img id="posterPreview" ${referencePoster?`src="${e(referencePoster)}"`:'hidden'} alt="参考海报预览"></div><button onclick="clearPoster()" type="button">移除参考海报</button><p class="note">参考海报会在生成图片时交给后端解析；产品库的图片仅作本地资料。</p><p class="error" id="ce"></p><div class="actions"><button class="primary" onclick="generate()">✧ 开始创作 →</button></div></div></section>
    <div><div class="hero"><span class="eyebrow">品牌灵感板</span><h2>${e(brand().name)}</h2><p>${e(brand().intro)}</p><span class="badge">${e(brand().position||'待补充定位')}</span></div><div class="card" style="margin-top:20px"><h3>本次会带上什么？</h3><p>品牌介绍与定位<br>产品价格、卖点与知识库事实<br>营销目的、活动信息与表达偏好</p><div class="tip">图文模式先生成文案，再由你点击生成图片。仅图片模式直接生成所选平台的第一张图片，其余图片按需生成。</div><small>资料和历史作品保存在当前浏览器；自动发布尚未接入。</small></div></div></div>`;
  goalFields(c);
  createMatches=[];
  $('#createProductQuery').addEventListener('input',searchCreateProducts);
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
  try { results=await generateCampaign(draft,{signal:controller.signal}); selected=0; controller=null; go('results'); }
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
      <div class="row"><button ${disabled} onclick="requestImage()">${r.imageUrl?'重新生成图片':'生成图片'}</button>${r.finalPrompt?`<button ${disabled} onclick="openReviseImage()">继续修改图片</button>`:''}</div>
      ${r.finalPrompt?`<details><summary>提示词与海报解析</summary><p class="resulttext">${e(r.finalPrompt)}</p>${Object.entries(r.parsedPrompt||{}).map(([key,value])=>`<p>${e(key)}：${e(value)}</p>`).join('')}</details>`:''}
      ${r.imageVersions.length?`<details><summary>图片历史版本（${r.imageVersions.length}）</summary>${r.imageVersions.map((v,index)=>`<div class="historyline">第 ${index+1} 版 · ${e(v.time)} <button ${disabled} onclick="restoreImage(${index})">恢复图片</button></div>`).join('')}</details>`:''}`}
    </section><section class="card"><h3>记住这一次的表达</h3><p>确认后，将表达偏好用于当前品牌的下次创作。</p><label><input type="checkbox" id="remember"> 我确认记住为品牌偏好</label><button ${disabled} onclick="remember()">保存偏好</button></section><button ${disabled} onclick="go('create')">＋ 开始下一次创作</button></div></div>${busy?'<div class="jobbar" role="status">请求处理中 <button onclick="cancelJob()">取消等待</button></div>':''}`;
  if (busy) document.querySelectorAll('#app input,#app textarea').forEach(el=>el.disabled=true);
}
function enableImages() { readResult(); draft.format='图文'; renderResults(); }
function saveWork() {
  readResult(); const r=results[selected]; if (!r.title.trim()||!r.body.trim()) { say('请补齐标题和正文'); return; }
  const snapshot=structuredClone(r); snapshot.versions.push({title:r.title,body:r.body,summary:r.summary,tags:r.tags,time:new Date().toLocaleString('zh-CN')}); snapshot.saved=true;
  const work={id:r.id,brand:draft.brand.id,draft:structuredClone(draft),result:snapshot,time:new Date().toLocaleString('zh-CN')};
  const index=db.works.findIndex(w=>w.id===r.id),before=structuredClone(db.works);
  if (index<0) db.works.unshift(work); else db.works[index]=work;
  if (!save()) { db.works=before; return; }
  Object.assign(r,snapshot); renderResults(); say('作品与版本已保存到当前浏览器');
}
function restore(index) { readResult(); Object.assign(results[selected],results[selected].versions[index],{saved:false}); renderResults(); }
function restoreImage(index) { readResult(); const r=results[selected]; Object.assign(r,r.imageVersions[index],{saved:false,imageError:''}); renderResults(); }
function recordImage(target,outcome) { Object.assign(target,outcome,{saved:false}); target.imageVersions??=[]; target.imageVersions.push({...outcome,time:new Date().toLocaleString('zh-CN')}); }
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
  try { recordImage(target,await reviseImage(target.finalPrompt,feedback,{signal:controller.signal})); }
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
function remember() { if (!$('#remember').checked) { say('请先勾选确认'); return; } const b=db.brands.find(item=>item.id===draft.brand.id); if (!b) return; b.preference=draft.style; if (save()) say('品牌表达偏好已保存'); }
function renderHistory() { $('#app').innerHTML=head('历史作品','在当前浏览器保存的作品与版本。')+`<div class="card">${db.works.map(w=>`<div class="historyline row spread"><div><strong>${e(w.result.title)}</strong><br><small>${e(w.result.platform)} · ${e(w.time)} · ${w.result.versions?.length||0} 个文案版本</small></div><button onclick="openWork('${e(w.id)}')">打开并继续修改</button></div>`).join('')||'<div class="empty">还没有保存的作品。</div>'}</div>`; }
function openWork(id) { const w=db.works.find(item=>item.id===id); if (!w) return; if (view==='results') readResult(); current=w.brand; draft=structuredClone(w.draft); results=[structuredClone(w.result)]; selected=0; view='history'; go('results'); }
async function refreshQuota() {
  if (mode==='mock'||!serverReady) return;
  try { const q=await getQuota(); $('#quotaStatus').textContent=q.remaining==null?'':`剩余额度：${q.remaining} 次`; }
  catch { $('#quotaStatus').textContent='额度暂不可用'; }
}
function showAccess() { modal(`<h2>输入访问密码</h2><p>这是应用访问密码，由项目负责人提供。</p><label for="accessKey">访问密码</label><input type="password" id="accessKey" autocomplete="current-password"><p class="error" id="accessError"></p><div class="actions"><button class="primary" onclick="submitAccess()">进入应用</button></div>`); $('#accessKey').focus(); }
async function submitAccess() {
  const button=$('#modal button'); button.disabled=true;
  try { await verifyAccess($('#accessKey').value.trim()); serverReady=true; closeModal(); await refreshQuota(); say('访问校验通过'); }
  catch (error) { $('#accessError').textContent=error.message; }
  finally { if (button.isConnected) button.disabled=false; }
}
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
    await refreshQuota();
  } catch { serverReady=false; $('#modeStatus').textContent='后端未连接'; say('后端未连接，本地资料仍可编辑；启动后端后点击重新连接。'); }
}
Object.assign(window,{go,changeBrand,newBrand,saveBrand,demo,editProduct,saveProduct,fillSuggestion,importProducts,doImport,openSearch,lookupProducts,adoptProduct,cacheCreate,selectCreateProduct,goalFields,clearPoster,generate,runGeneration,cancelJob,selectResult,saveWork,restore,restoreImage,enableImages,requestImage,openReviseImage,submitReviseImage,rewrite,doRewrite,copyText,remember,openWork,closeModal,submitAccess,initialize});
document.addEventListener('keydown',event=>{ if (event.key==='Escape'&&!$('#accessKey')) closeModal(); });
go('brand'); initialize();
