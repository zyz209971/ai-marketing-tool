import {request, verifyAccess} from './services/api.js';
import {attachmentCards,bindAttachmentCards,setupWorkspace} from './agent-workspace.js';
const $=id=>document.getElementById(id);
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key=()=>globalThis.crypto?.randomUUID?.()||('local_'+Date.now().toString(36)+Math.random().toString(36).slice(2));
const post=(path,body)=>request('/api/agent'+path,{method:'POST',body:JSON.stringify(body)});
const get=path=>request('/api/agent'+path);
const money=v=>v==null?'暂未测算':'¥'+(v/100).toFixed(2);
const taskNames={brand_setup:'品牌建档 / 更新',content:'普通文案',unit_economics:'单位优惠检查',campaign:'活动策略与文案'};
const stages={collecting:'正在聊需求',analyzing:'正在分析',awaiting_confirmation:'等待你的确认',generating:'正在创作文案',completed:'可以继续调整',blocked:'一起调整方案',failed:'需要重试'};
const names={T001:'茉莉鲜奶茶',T002:'乌龙鲜奶茶',T003:'红茶鲜奶茶'};
const platforms={xiaohongshu:'小红书',douyin:'抖音',wechat_official_account:'微信公众号'};
let task=null,busy=false;
let selectedAnswers={};
function fail(e){$('error').hidden=false;$('error').textContent=e.message||String(e);}
function bottom(){if($('chatRoot')?.hidden)return;requestAnimationFrame(()=>{$('scrollArea').scrollTo({top:$('scrollArea').scrollHeight,behavior:'instant'});});}
function setBusy(value){busy=value;($('chatRoot')||document).querySelectorAll('button:not(#toggleSidebar):not(#mode):not(#settings):not(.close)').forEach(b=>b.disabled=value||b.dataset.incomplete==='true'||(b.dataset.option!==undefined&&!task?.state.options?.[Number(b.dataset.option)]?.evaluation.result.feasible));$('message').disabled=value;$('thinking').hidden=!value;$('suggestions').hidden=value;if(value)bottom();document.dispatchEvent(new CustomEvent('workbench:busy',{detail:{busy:value,task}}));}
async function history(){const {conversations}=await get('/conversations');$('history').innerHTML=conversations.map(c=>`<button class="task ${c.id===task?.id?'active':''}" data-id="${escape(c.id)}" title="${escape(c.title||'营销对话')}">${escape(c.title||'营销对话')}<small>${escape(new Date(c.updated).toLocaleDateString())}</small></button>`).join('');$('history').querySelectorAll('button').forEach(b=>{b.disabled=busy;b.onclick=()=>open(b.dataset.id).catch(fail);});}
function period(b){const end=new Date(b.end_date+'T12:00:00');end.setDate(end.getDate()-1);return `${b.start_date} 至 ${end.getFullYear()}-${String(end.getMonth()+1).padStart(2,'0')}-${String(end.getDate()).padStart(2,'0')}（含）`;}
function strategyCard(strategy,s){
 const r=strategy.evaluation.result,b=strategy.brief,current=strategy.id===s.strategy?.id;
 const ready=current&&(strategy.status==='proposed'||(s.stage==='failed'&&!s.artifacts.some(a=>a.strategy_id===strategy.id&&!a.stale)));
 const offer=b.offer.type==='none'?'原价推广':(b.offer.type==='second_cup_discount'?'第二杯':'每杯')+(b.offer.pay_bps/1000)+'折';
 return `<section ${current?'id="strategy"':''} class="card ${r.incremental_contribution_minor<0?'warning':''} ${current?'':'stale'}"><div class="row"><h2>活动方案 · v${strategy.version}</h2><span class="pill">${!current?'历史方案':strategy.status==='approved'?'已确认':'待确认'}</span></div><p class="facts">${escape(strategy.product_name||names[b.sku_id])} · ${escape(platforms[b.platform])}\n${escape(period(b))}\n${escape(offer)} · 同款同规格，不叠加优惠</p><div class="metrics"><div class="metric"><small>平均每杯贡献收益</small><strong>${money(r.average_contribution_minor)}</strong></div><div class="metric"><small>活动增量贡献</small><strong>${money(r.incremental_contribution_minor)}</strong></div></div>${r.incremental_contribution_minor<0?'<p class="risk">按当前销量假设，这次活动可能不如不促销。可以考虑缩小优惠或减少支出。</p>':''}<p class="prose">${escape(strategy.rationale)}</p><details><summary>看看测算依据和活动细则</summary><p>预算上限 ${money(b.budget_minor)}；预计支出 ${money(b.spend_minor)}；销量假设 ${b.scenario_qty??'未提供'} 杯；参与第二杯优惠 ${b.promotion_pairs??'未提供'} 组。</p><p>情景增量 ROI：${r.incremental_roi==null?'未计算':(r.incremental_roi*100).toFixed(1)+'%'}。门店自提，${b.offer.type==='second_cup_discount'?'同单每两杯重复配对，未配对单杯原价；':''}不叠加优惠。</p><ul>${[...strategy.evaluation.assumptions,...(strategy.risks||[])].map(a=>'<li>'+escape(a)+'</li>').join('')}</ul>${(r.candidates||[]).length?'<p>保持相同销量假设的候选折扣：</p>'+r.candidates.map(c=>`<p>支付原价 ${c.pay_bps/100}%：平均贡献 ${money(c.average_contribution_minor)}，增量贡献 ${money(c.incremental_contribution_minor)}。</p>`).join(''):''}</details>${ready?'<button class="primary" id="confirm">这个方案可以，帮我写文案</button>':''}</section>`;
}
function artifactEvidence(a){
 const sources=(a.source_refs||[]).map(id=>task.attachments?.find(x=>x.payload.document_id===id)?.payload.filename||('已确认品牌资料 · '+id.slice(0,8)));
 return `<details><summary>查看依据与检查结果</summary><p>${a.kind==='content'?'普通文案：使用已确认品牌事实，不含优惠承诺。':`依据已确认策略 v${a.strategy_version}；交易条件${a.validation?.terms_match?'已核对':'待核对'}。`}</p><p>商品事实：${escape(sources.join('、')||'已确认商品目录')}。</p><p>写作参考：${(a.retrieval?.marketing_refs||[]).length} 条；品牌偏好：${(a.retrieval?.memory_refs||[]).length} 条。参考案例仅用于写作结构。</p><p class="note">语义与品牌表达仍需人工复核，当前没有自动证明每句话准确。</p></details>`;
}
function artifactCard(a){return `<section class="card artifact ${a.stale?'stale':''}" data-artifact="${escape(a.id)}"><div class="row"><h2>为你准备的文案</h2><span class="pill">v${a.version}${a.stale?' · 历史版本':''}</span></div><h3>${escape(a.title)}</h3><div class="prose">${escape(a.body)}</div><p class="note">${a.mock?'离线演示文案 · ':''}${a.kind==='content'?'普通品牌 / 商品文案':'基于活动方案 v'+a.strategy_version}，发布前请核对。${task.state.brief.brand_id?'已归档至品牌与作品管理。':''}</p>${artifactEvidence(a)}<button class="copy" data-copy="${escape(a.id)}">复制文案</button></section>`;}
function render(){
 const s=task.state;$('stage').textContent=stages[s.stage]||s.stage;
 Object.entries(task.catalog||{}).forEach(([id,p])=>names[id]=p.name);
 $('brandLabel').textContent=s.brief.brand_id?(task.brand_name||'品牌工作空间')+' · 本地开发版':s.demo_mode?'模拟门店 · 本地开发版':'新品牌 · 从对话开始';
 $('dataNote').textContent=s.brief.brand_id?'使用已确认的品牌资料与用户经营数据；缺失项需补充，收益仅为情景测算。':s.demo_mode?'当前使用模拟商品与经营数据。收益测算基于假设，活动方案由你确认。':'上传品牌介绍、菜单或商品说明，我会整理并询问缺项，确认后建立知识库。';
 const strategies=new Map([...s.strategies,...(s.strategy?[s.strategy]:[])].map(x=>[x.id,x]));
 const artifacts=new Map(s.artifacts.map(x=>[x.id,x])),seenStrategies=new Set(),seenArtifacts=new Set();
 const messages=s.messages.map((m,mi)=>{
  let cards='';
  if(m.sales){const x=m.sales.result;cards+=`<section class="card"><h2>经营数据概览</h2><p class="note">${m.sales.data_kind==='synthetic'?'示例数据':'用户确认的经营资料'} · 历史变化不证明原因</p>${x.metrics.map(v=>`<p>${escape(v.name)}：上期 ${v.previous_qty??'未知'} 杯 → 本期 ${v.current_qty??'未知'} 杯${v.change_ratio==null?'':'（'+(v.change_ratio*100).toFixed(1)+'%）'}</p>`).join('')}<details><summary>统计范围与数据依据</summary><p>${escape(x.previous_period.join(' 至 '))}；${escape(x.current_period.join(' 至 '))}（结束日期不含）</p><p>${escape(m.sales.warnings.join('；'))}</p></details></section>`;}
  if(m.strategy_ref&&strategies.has(m.strategy_ref)&&!seenStrategies.has(m.strategy_ref)){cards+=strategyCard(strategies.get(m.strategy_ref),s);seenStrategies.add(m.strategy_ref);}
  if(m.artifact_ref&&artifacts.has(m.artifact_ref)&&!seenArtifacts.has(m.artifact_ref)){cards+=artifactCard(artifacts.get(m.artifact_ref));seenArtifacts.add(m.artifact_ref);}
  return `<article class="message ${m.role==='user'?'user':'assistant'}"><span class="avatar">✳</span><div class="message-content"><div class="message-name">${m.role==='user'?'你':'营销助手'}</div><div class="message-text">${escape(mi===s.messages.length-1&&s.input_request&&m.role==='assistant'&&!/用途|未知|过期|检查/.test(m.content)?'已有资料和回答已保留。请一起确认下面几项，回答后我会继续。':m.content)}</div>${cards}</div></article>`;
 });
 let legacy='';if(s.strategy&&!seenStrategies.has(s.strategy.id))legacy+=strategyCard(s.strategy,s);
 for(const a of s.artifacts)if(!seenArtifacts.has(a.id))legacy+=artifactCard(a);
 if(legacy)messages.push(`<article class="message assistant"><span class="avatar">✳</span><div class="message-content">${legacy}</div></article>`);
 const options=(s.options||[]).map((o,i)=>`<section class="card"><h3>${escape(o.name)}</h3><p>${escape(o.rationale)}</p><p>平均每杯贡献 ${money(o.evaluation.result.average_contribution_minor)}；情景增量贡献 ${money(o.evaluation.result.incremental_contribution_minor)}</p><p>${escape(o.evaluation.result.violations.join('；'))}</p><button class="primary" data-option="${i}" ${o.evaluation.result.feasible?'':'disabled'}>${o.evaluation.result.feasible?'选择这个方案':'暂不可行'}</button></section>`).join('');
 const q=s.input_request;
 const savedKey=q?'agent-batch:'+task.id+':'+q.id:null;
 try{selectedAnswers=savedKey?JSON.parse(sessionStorage.getItem(savedKey)||'{}'):{};}catch{selectedAnswers={};}
 const questions=q?(q.questions?.length?q.questions:[{id:q.id,question:q.question,fields:q.fields,choices:q.choices||[]}]):[];
 const question=q?`<section class="card" id="inputRequest" aria-label="一起确认"><h2>一起确认 ${questions.length} 件事</h2><p class="note">${escape(q.reason)}</p>${questions.map((item,i)=>`<div class="question-item"><p><strong>${i+1}. ${escape(item.question)}</strong></p><div>${item.choices.map(c=>`<button type="button" data-question="${escape(item.id)}" data-answer="${escape(c.id)}" aria-pressed="${selectedAnswers[item.id]?.choice_id===c.id}">${escape(c.label)}</button>`).join('')}</div>${!item.choices.length?'<small>在下方对话框回答即可，可以一句话补充多项。</small>':''}</div>`).join('')}<button id="submitBatch" class="primary">提交本组回答</button><p class="note">也可以只回答已知部分，或告诉我暂时不知道、想换个目标。</p></section>`:'';
 const summary=s.brief.brand_id?`<details class="card task-summary"><summary>${escape(taskNames[s.brief.task_kind]||'当前任务')} · ${escape(task.brand_name||'品牌资料整理中')}</summary><p>${escape(s.brief.goal)} · ${escape(platforms[s.brief.platform]||'平台待定')}</p><p>已选择商品：${escape(names[s.brief.sku_id]||'待确定')}；${s.strategy?'策略 v'+s.strategy.version:'尚未确认策略'}</p></details>`:'';
 const u=s.unit_result?.result;
 const unit=u?`<section class="card" id="unitResult"><h2>单位优惠检查</h2><div class="metrics"><div class="metric"><small>同单两杯收入</small><strong>${money(u.pair_revenue_minor)}</strong></div><div class="metric"><small>平均每杯贡献</small><strong>${money(u.average_contribution_minor)}</strong></div></div><p>${u.feasible===null?'未指定最低标准，仅展示计算结果':u.feasible?'达到已提供的最低贡献标准':'未达到当前约束'}</p><p>${escape((u.violations||[]).join('；'))}</p><p class="note">贡献扣除变动成本，不等于净利润；不预测活动销量。</p><details><summary>查看假设和来源</summary><p>${escape(s.unit_result.assumptions.join('；'))}</p></details></section>`:'';
 $('messages').innerHTML=summary+messages.join('')+unit+options+attachmentCards(task)+question;
 $('message').placeholder=q?'可以一次回答多项；不知道或想换目标也可以直接说…':'告诉我下一步想做什么…';
 document.querySelectorAll('[data-question]').forEach(b=>b.onclick=()=>{
  const id=b.dataset.question,choice=b.dataset.answer;
  if(selectedAnswers[id]?.choice_id===choice)delete selectedAnswers[id];else selectedAnswers[id]={choice_id:choice};
  sessionStorage.setItem(savedKey,JSON.stringify(selectedAnswers));
  document.querySelectorAll('[data-question]').forEach(x=>x.setAttribute('aria-pressed',String(selectedAnswers[x.dataset.question]?.choice_id===x.dataset.answer)));
 });
 if($('submitBatch'))$('submitBatch').onclick=()=>$('chat').requestSubmit();
 if(s.brief.brand_id&&s.artifacts.length&&s.brief.style&&s.brief.style!=='自然、简洁，不夸大功效'&&!(s.brand_context?.memories||[]).some(m=>m.kind==='tone'&&m.content===s.brief.style)){
  $('messages').insertAdjacentHTML('beforeend','<section class="card"><p>当前表达偏好：'+escape(s.brief.style)+'</p><button id="rememberStyle">确认将此风格保存为品牌长期偏好</button><p class="note">仅在点击确认后保存；可在品牌管理中修改或删除。</p></section>');
  $('rememberStyle').onclick=async()=>{setBusy(true);try{await post('/conversations/'+task.id+'/remember-style',{expected_revision:task.revision});await load();}catch(e){fail(e);}finally{setBusy(false);}};
 }
 bindAttachmentCards();
 document.querySelectorAll('[data-option]').forEach(b=>b.onclick=()=>{const o=s.options[Number(b.dataset.option)];if(o.evaluation.result.feasible)send('message',{text:'选择'+o.name,patch:{offer:o.offer}});});
 if($('confirm'))$('confirm').onclick=()=>send('confirm',{strategy_id:s.strategy.id,strategy_version:s.strategy.version});
 document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{try{const a=artifacts.get(b.dataset.copy);await navigator.clipboard.writeText(a.title+'\n\n'+a.body);b.textContent='已复制';}catch(e){fail(e);}});
 $('suggestions').innerHTML=(s.suggestions||[]).map(text=>`<button>${escape(text)}</button>`).join('');
 $('suggestions').querySelectorAll('button').forEach(b=>b.onclick=()=>send('message',{text:b.textContent}));
 setBusy(busy);bottom();document.dispatchEvent(new CustomEvent('workbench:task',{detail:task}));
}
async function load(){task=await get('/conversations/'+task.id);render();await history();}
async function poll(runId){for(;;){const run=await get('/runs/'+runId);if(['succeeded','failed'].includes(run.status)){await load();if(run.status==='failed')fail(Error(run.error));return;}await new Promise(r=>setTimeout(r,800));}}
async function open(id){if(busy){if(task?.id===id)return;throw Error('当前对话仍在执行。可以浏览资料，完成后再切换对话。');}const previous=task;if(task?.id)sessionStorage.setItem('compose:'+task.id,$('message').value);setBusy(true);try{task={id};$('message').value=sessionStorage.getItem('compose:'+id)||'';document.body.classList.remove('sidebar-open');await load();localStorage.setItem('marketing-agent-task',id);if(task.active_run)await poll(task.active_run);}catch(e){task=previous;if(previous?.state){$('message').value=sessionStorage.getItem('compose:'+previous.id)||'';render();}throw e;}finally{setBusy(false);}}
async function send(action,body){
 if(busy||!task||action==='message'&&!body.text?.trim())return;
 $('error').hidden=true;
 if(action==='message'){const context=JSON.parse(sessionStorage.getItem('compose-context:'+task.id)||'null');if(context?.text===body.text)body.patch={...body.patch,sku_id:context.skuId};sessionStorage.removeItem('compose-context:'+task.id);$('messages').insertAdjacentHTML('beforeend',`<article class="message user"><div class="message-content"><div class="message-text">${escape(body.text)}</div></div></article>`);$('message').value='';sessionStorage.removeItem('compose:'+task.id);}
 setBusy(true);
 try{const r=await post('/conversations/'+task.id+'/'+(action==='confirm'?'confirm':action==='answer'?'answers':'messages'),{...body,request_id:key(),expected_revision:task.revision});await poll(r.run_id);}
 catch(e){fail(e);try{await load();if(task.active_run)await poll(task.active_run);}catch{}}
 finally{setBusy(false);if(!$('chatRoot')?.hidden)$('message').focus();bottom();}
}
$('chat').onsubmit=e=>{e.preventDefault();const text=$('message').value.trim();const q=task?.state.input_request;
 if(q&&(Object.keys(selectedAnswers).length||text)){
  if(!Object.keys(selectedAnswers).length){send('message',{text});return;}
  $('message').value='';send('answer',{question_id:q.id,...(q.questions?.length?{answers:selectedAnswers}:{choice_id:Object.values(selectedAnswers)[0]?.choice_id}),text});
 }else if(text)send('message',{text});};
$('message').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chat').requestSubmit();}};
$('newTask').onclick=async()=>{if(busy)return;setBusy(true);try{const created=await post('/conversations',{brand_id:task?.state.brief.brand_id||null,demo:!!task?.state.demo_mode});setBusy(false);await open(created.id);$('message').focus();}catch(e){fail(e);}finally{setBusy(false);}};
$('toggleSidebar').onclick=()=>{if(innerWidth<=700){document.body.classList.toggle('sidebar-open');document.body.classList.remove('sidebar-hidden');}else document.body.classList.toggle('sidebar-hidden');};
$('scrollArea').onclick=()=>{if(innerWidth<=700)document.body.classList.remove('sidebar-open');};
$('settings').onclick=$('mode').onclick=()=>$('connection').showModal();
async function initialize({taskId=null}={}){try{
 const c=await get('/config'),live=c.mode==='llm';$('mode').textContent=live?'已配置模型':'未连接模型 · 演示';$('mode').classList.toggle('connected',live);
 $('connectionStatus').textContent=live?'当前使用已配置的模型进行对话和工具决策；经营数据取决于所选品牌，来源会在结果中标明。':'当前没有启用真实模型，仅能识别有限的演示表达。配置密钥后才能测试完整的自然语言理解。';
 $('settings').textContent=live?'模型连接设置':'连接模型';$('access').hidden=true;$('error').hidden=true;
 const previous=taskId||new URLSearchParams(location.search).get('task')||localStorage.getItem('marketing-agent-task');if(previous){try{await open(previous);return;}catch(e){if(e.status!==404)throw e;}}
 const created=await post('/conversations',{});await open(created.id);
 }catch(e){if(e.status===403){$('access').hidden=false;$('connection').showModal();}fail(e);}}
$('unlock').onclick=async()=>{try{await verifyAccess($('accessKey').value);$('connection').close();await initialize();}catch(e){fail(e);}};
setupWorkspace({getTask:()=>task,load,open,fail,setBusy,isBusy:()=>busy,resumeAttachment:()=>send('message',{text:'继续补资料'})});
export {initialize as initializeAgent,open as openAgent};
export const currentAgent=()=>({task,busy});
export function prefillAgent(value){if(!task?.state)return;$('message').value=value;sessionStorage.setItem('compose:'+task.id,value);sessionStorage.removeItem('compose-context:'+task.id);if(!$('chatRoot')?.hidden)$('message').focus();}
export async function createAgent(brandId=null,{demo=false,skuId=null,text=''}={}){if(busy)throw Error('请等待当前任务完成后再开启另一段对话。');setBusy(true);let created;try{created=await post('/conversations',{brand_id:brandId,demo});}finally{setBusy(false);}await open(created.id);if(text){prefillAgent(text);if(skuId)sessionStorage.setItem('compose-context:'+created.id,JSON.stringify({skuId,text}));}return created;}
$('message').addEventListener('input',()=>{if(task?.id)sessionStorage.setItem('compose:'+task.id,$('message').value);});
