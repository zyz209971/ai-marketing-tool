import {request} from './services/api.js';
import {initializeAgent,openAgent,createAgent,prefillAgent} from './agent.js';
import {parseRoute,routeHref} from './router.js';
import {icon} from './icons.js';

const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nav=[['chat','chat','与 Agent 对话'],['brands','layers','品牌资料'],['products','box','产品库'],['creations','spark','营销创作记录'],['conversations','clock','对话记录']];
const stageNames={collecting:'待补充 / 继续对话',analyzing:'正在分析',awaiting_confirmation:'待确认策略',generating:'正在创作',completed:'已完成',blocked:'待调整',failed:'需重试'};
const commands=[['layers','建立品牌资料','上传资料，边聊边完善','我想建立品牌资料，请引导我上传需要的文件'],['pencil','写营销文案','商品介绍 / 品牌表达','帮我写一篇普通商品介绍文案，不做优惠活动'],['chart','检查优惠收益','售价 / 成本 / 优惠边界','我想只检查优惠是否满足成本，请帮我做单位收益测算'],['target','制定活动策略','经营分析 / 方案 / 文案','请结合我的销售情况制定下一步营销活动策略']];
let route=parseRoute(location.hash),task=null,busy=false,workspace={brands:[],products:[],works:[]},recent=[];
let selectedBrand=sessionStorage.getItem('workbench-brand')||'',routeToken=0,refreshTimer,refreshToken=0;
let managementPromise,managementQueue=Promise.resolve(),managementKey='',managementDirty=true;
let conversationQuery='',conversationBrand='',conversationOffset=0,conversationRequest=0;
let ready;

function alert(message){$('workspaceAlert').textContent=message||'';$('workspaceAlert').hidden=!message;}
function brandValue(){return task?.state.brief.brand_id||(task?.state.demo_mode?'__demo__':'');}
function updateHeader(){
 $('primaryNav').innerHTML=nav.map(([id,i,label])=>`<a href="${routeHref(id,id==='chat'?task?.id:null)}" data-view="${id}" ${route.view===id?'aria-current="page"':''}>${icon(i)}<span>${label}</span></a>`).join('');
 $('pageCaption').textContent=route.view==='chat'?'从创意到落地，一站式智能营销助手':nav.find(n=>n[0]===route.view)?.[2]||'营销助手';
 $('workspaceBrand').innerHTML='<option value="">新品牌 / 选择品牌</option>'+workspace.brands.map(b=>`<option value="${esc(b.id)}">${esc(b.name)}</option>`).join('')+'<option value="__demo__">模拟门店 · 示例数据</option>';
 $('workspaceBrand').value=route.view==='chat'?brandValue():selectedBrand;
 $('workspaceBrand').disabled=route.view==='chat'&&busy;
 $('newTask').disabled=busy;
 $('toggleContext').hidden=route.view!=='chat';
}
function renderContext(){
 const bid=task?.state.brief.brand_id,b=workspace.brands.find(b=>b.id===bid),pending=!!task?.state.brand_setup_pending;
 const products=workspace.products.filter(p=>p.brand===bid&&!p.archived);
 const brand=b&&!pending?`<div class="context-brand"><span class="brand-mark">${icon('leaf')}</span><div><strong>${esc(b.name)}</strong><p>${esc(b.intro)}</p></div></div><dl><dt>品牌定位</dt><dd>${esc(b.position||'尚未补充')}</dd><dt>表达风格</dt><dd>${esc(b.style||'尚未补充')}</dd><dt>已建商品</dt><dd>${products.length} 款 · 可在产品库核对</dd></dl>`:
 `<div class="context-empty">${icon('layers')}<strong>${pending?'品牌资料待确认':task?.state.demo_mode?'模拟门店 · 示例数据':'先认识你的品牌'}</strong><p>${pending?'资料已经整理成草稿，确认后将显示在这里。':task?.state.demo_mode?'当前使用虚构商品与经营数据，请勿当作真实门店结果。':'上传品牌介绍或菜单，我会整理资料并询问必要的缺项。'}</p><button data-upload>上传品牌资料 ${icon('arrow')}</button></div>`;
 const status=task?.state.input_request?'等待你补充信息':task?.state.active_attachment_id?'等待核对资料':stageNames[task?.state.stage]||'准备开始';
 const scope=task?.state.messages.some(m=>m.role==='user')?task.state.brief.task_kind:null;
 $('contextPanel').innerHTML=`<button class="context-close icon-button" aria-label="关闭品牌上下文">×</button><section class="context-card"><div class="context-heading"><h2>${icon('layers')}品牌上下文</h2><a href="#/brands">管理品牌资料 ${icon('arrow')}</a></div>${brand}</section>
 <section class="context-card"><div class="context-heading"><h2>${icon('spark')}快捷指令</h2><small>从一个需求开始</small></div><div class="quick-grid">${commands.map(([i,title,desc],n)=>`<button data-command="${n}">${icon(i)}<span><strong>${title}</strong><small>${desc}</small></span></button>`).join('')}</div></section>
 <section class="context-card"><div class="context-heading"><h2>${icon('target')}推荐任务</h2></div><p class="context-note">结合品牌资料，逐步完成你的营销计划</p><button class="recommended-task" data-command="1"><span class="task-symbol">${icon('pencil')}</span><span><strong>品牌与商品文案</strong><small>根据已确认资料创作，支持多轮修改</small></span><span class="use-task">开始</span></button><button class="recommended-task" data-command="3"><span class="task-symbol">${icon('chart')}</span><span><strong>经营促销方案</strong><small>检查成本与收益，确认策略后写文案</small></span><span class="use-task">开始</span></button></section>
 <section class="context-card"><div class="context-heading"><h2>${icon('file')}当前与最近任务</h2><a href="#/conversations">查看全部 ${icon('arrow')}</a></div><div class="current-status"><span class="status-dot ${busy?'running':''}"></span>${esc(status)}${scope?'<small>'+esc(({brand_setup:'品牌建档',content:'普通文案',unit_economics:'单位收益',campaign:'活动策略'})[scope])+'</small>':''}</div>${recent.slice(0,3).map(r=>`<a class="recent-task" href="${routeHref('chat',r.id)}">${icon('clock')}<span>${esc(r.title)}</span><small>${esc(new Date(r.updated).toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'}))}</small></a>`).join('')||'<p class="context-note">开始对话后，任务记录会保存在这里。</p>'}</section>`;
 $('contextPanel').querySelectorAll('[data-command]').forEach(b=>b.onclick=()=>useCommand(Number(b.dataset.command)));
 $('contextPanel').querySelector('[data-upload]')?.addEventListener('click',()=>{if(!busy)$('attach').click();});
 $('contextPanel').querySelector('.context-close').onclick=closeContext;
}
function closeContext(){document.body.classList.remove('context-open');$('toggleContext').setAttribute('aria-expanded','false');}
async function refreshData(){
 const token=++refreshToken;
 try{
  const [w,r]=await Promise.all([request('/api/knowledge/workspace'),request('/api/agent/conversations?limit=3')]);
  if(token!==refreshToken)return;
  workspace=w;recent=r.conversations;
  if(selectedBrand&&selectedBrand!=='__demo__'&&!workspace.brands.some(b=>b.id===selectedBrand))selectedBrand='';
  updateHeader();renderContext();
 }catch(e){alert(e.message);}
}
function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refreshData,120);}
function rememberBrand(value){selectedBrand=value||'';sessionStorage.setItem('workbench-brand',selectedBrand);}
async function newConversation(brandId=selectedBrand,{text='',skuId=null}={}){
 await ready;
 if(busy){alert('当前对话还在执行。可以先浏览资料，完成后再开启新对话。');return;}
 try{
  alert('');const created=await createAgent(brandId==='__demo__'?null:brandId||null,{demo:brandId==='__demo__',text,skuId});
  rememberBrand(brandId);location.hash=routeHref('chat',created.id);scheduleRefresh();
 }catch(e){alert(e.message);updateHeader();}
}
async function useCommand(n){await ready;if(busy){alert('当前任务正在执行，请稍候再提交新的需求。');return;}location.hash=routeHref('chat',task?.id);prefillAgent(commands[n][3]);closeContext();}

async function showRoute(){
 const token=++routeToken;route=parseRoute(location.hash);alert('');
 document.body.dataset.view=route.view;document.body.classList.remove('nav-open');closeContext();
 $('chatRoot').hidden=route.view!=='chat';$('contextPanel').hidden=route.view!=='chat';
 $('managementRoot').hidden=!['brands','products','creations'].includes(route.view);
 $('conversationRoot').hidden=route.view!=='conversations';updateHeader();
 if(route.view==='chat'){
  await ready;if(token!==routeToken)return;
  if(route.taskId&&route.taskId!==task?.id){try{await openAgent(route.taskId);}catch(e){alert(e.message);history.replaceState(null,'',routeHref('chat',task?.id));route=parseRoute(location.hash);}}
  if(token!==routeToken)return;
  if(task){rememberBrand(brandValue());history.replaceState(null,'',routeHref('chat',task.id));route=parseRoute(location.hash);}
  updateHeader();renderContext();return;
 }
 if(route.view==='conversations'){conversationBrand=selectedBrand==='__demo__'?'':selectedBrand;renderConversationPage();return;}
 const target={brands:'brand',products:'products',creations:'history'}[route.view],bid=selectedBrand==='__demo__'?null:selectedBrand||null;
 const key=target+':'+(bid||'');
 if(key===managementKey&&!managementDirty)return;
 $('managementRoot').setAttribute('aria-busy','true');
 managementQueue=managementQueue.catch(()=>{}).then(async()=>{
  if(token!==routeToken)return;
  managementPromise??=import('./app.js');const m=await managementPromise;
  await m.showManagement(target,bid,{refresh:managementDirty});
  if(token===routeToken){managementKey=key;managementDirty=false;}
 });
 try{await managementQueue;}catch(e){alert(e.message);}finally{if(token===routeToken)$('managementRoot').setAttribute('aria-busy','false');}
}
function renderConversationPage(){
 $('conversationRoot').innerHTML=`<div class="records-heading"><span class="eyebrow">与你的营销助手一起完成</span><h1>对话记录</h1><p>找回需求、补充资料和每一次调整，继续未完成的任务。</p></div><div class="record-filters"><label>搜索对话<input id="conversationSearch" maxlength="100" placeholder="输入任务或品牌名称" value="${esc(conversationQuery)}"></label><label>所属品牌<select id="conversationBrand"><option value="">全部品牌</option>${workspace.brands.map(b=>`<option value="${esc(b.id)}" ${conversationBrand===b.id?'selected':''}>${esc(b.name)}</option>`).join('')}</select></label></div><div id="conversationList" aria-live="polite"></div><div id="conversationPages" class="record-pages"></div>`;
 let timer;
 $('conversationSearch').oninput=e=>{conversationQuery=e.target.value;conversationOffset=0;clearTimeout(timer);timer=setTimeout(loadConversations,250);};
 $('conversationBrand').onchange=e=>{conversationBrand=e.target.value;conversationOffset=0;loadConversations();};
 loadConversations();
}
async function loadConversations(){
 const token=++conversationRequest;
 const params=new URLSearchParams({limit:'20',offset:String(conversationOffset),q:conversationQuery});if(conversationBrand)params.set('brand_id',conversationBrand);
 $('conversationList').innerHTML='<p class="loading-message">正在读取对话记录…</p>';
 try{
  const data=await request('/api/agent/conversations?'+params);
  if(token!==conversationRequest||route.view!=='conversations')return;
  $('conversationList').innerHTML=data.conversations.map(r=>`<a class="conversation-record" href="${routeHref('chat',r.id)}"><span class="record-symbol">${icon('chat')}</span><div><h2>${esc(r.title)}</h2><p>${esc(r.brand_name)} · ${esc(new Date(r.updated).toLocaleString('zh-CN'))}</p></div><span class="record-status ${r.active_run?'running':''}">${esc(stageNames[r.stage]||r.stage)}</span>${icon('arrow')}</a>`).join('')||'<div class="records-empty">'+icon('chat')+'<h2>还没有匹配的对话</h2><p>调整筛选，或开始一段新的对话。</p></div>';
  $('conversationPages').innerHTML=`<button id="previousPage" ${conversationOffset===0?'disabled':''}>上一页</button><span>第 ${Math.floor(conversationOffset/20)+1} 页</span><button id="nextPage" ${data.has_more?'':'disabled'}>下一页</button>`;
  $('previousPage').onclick=()=>{conversationOffset=Math.max(0,conversationOffset-20);loadConversations();};$('nextPage').onclick=()=>{conversationOffset+=20;loadConversations();};
 }catch(e){if(token===conversationRequest&&route.view==='conversations')$('conversationList').textContent=e.message;}
}

document.addEventListener('workbench:task',e=>{
 task=e.detail;managementDirty=true;
 const hasUser=task.state.messages.some(m=>m.role==='user');$('chatWelcome').classList.toggle('compact',hasUser);
 if(route.view==='chat'){rememberBrand(brandValue());history.replaceState(null,'',routeHref('chat',task.id));route=parseRoute(location.hash);}
 updateHeader();renderContext();scheduleRefresh();
});
document.addEventListener('workbench:busy',e=>{const was=busy;busy=e.detail.busy;updateHeader();if(was&&!busy)scheduleRefresh();});
document.addEventListener('workbench:data',()=>{managementDirty=true;scheduleRefresh();});
document.addEventListener('workbench:compose',e=>newConversation(e.detail.brandId,e.detail));
document.addEventListener('workbench:open-task',e=>{location.hash=routeHref('chat',e.detail.id);});
document.addEventListener('workbench:management',e=>{
 if($('managementRoot').hidden)return;
 const view={brand:'brands',products:'products',history:'creations',results:'creations'}[e.detail.view];if(!view)return;
 rememberBrand(e.detail.brandId);route={view,taskId:null};history.replaceState(null,'',routeHref(view));document.body.dataset.view=view;managementKey=({brands:'brand',products:'products',creations:'history'}[view])+':'+selectedBrand;updateHeader();scheduleRefresh();
});
$('workspaceBrand').onchange=e=>{const value=e.target.value;if(route.view==='chat')newConversation(value);else{rememberBrand(value);managementKey='';showRoute();}};
$('newTask').onclick=()=>newConversation(route.view==='chat'?brandValue():selectedBrand);
$('toggleSidebar').onclick=()=>document.body.classList.toggle(innerWidth<=760?'nav-open':'nav-collapsed');
$('toggleContext').onclick=()=>{const open=document.body.classList.toggle('context-open');$('toggleContext').setAttribute('aria-expanded',String(open));};
$('workspaceBody').addEventListener('click',()=>{if(innerWidth<=760)document.body.classList.remove('nav-open');});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeContext();document.body.classList.remove('nav-open');}});
window.addEventListener('hashchange',()=>showRoute().catch(e=>alert(e.message)));
updateHeader();renderContext();
ready=initializeAgent({taskId:route.taskId});
await refreshData();await showRoute();
