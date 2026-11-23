// Exercise the actual form/send controller with a small DOM and transport double.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import * as sendState from '../src/send-state.js';
const source=await readFile(new URL('../src/agent.js',import.meta.url),'utf8');
let sequence=0;
async function harness({reject=false,lost=false,pollFails=false,question=false,offlineFirst=false,malformed=false,runFailed=false}={}) {
  const nodes=new Map(),disk=new Map(),calls=[];
  class Element {
    constructor(id=''){this.id=id;this.value='';this.dataset={};this.hidden=false;this.innerHTML='';this.classList={remove(){},toggle(){}};this.listeners={};}
    querySelectorAll(){return [];}
    addEventListener(name,cb){this.listeners[name]=cb;}
    before(element){nodes.set(element.id,element);if(element.innerHTML.includes('checkSubmission'))nodes.set('checkSubmission',new Element('checkSubmission'));}
    append(element){this.retry=element;}
    remove(){nodes.delete(this.id);nodes.delete('checkSubmission');}
    focus(){} scrollTo(){} setAttribute(){}
  }
  for(const id of ['error','chatRoot','message','thinking','suggestions','history','brandLabel','dataNote','stage','messages','scrollArea','chat','newTask','toggleSidebar','settings','mode','connection','connectionStatus','access','unlock','accessKey'])nodes.set(id,new Element(id));
  const doc={getElementById:id=>nodes.get(id),querySelectorAll:()=>[],createElement:()=>new Element(),dispatchEvent(){},body:{classList:{remove(){}}}};
  const state={brief:{brand_id:'brand',sku_id:'sku',goal:'介绍',platform:null,task_kind:'content'},stage:'collecting',strategies:[],strategy:null,artifacts:[],messages:[],suggestions:[],options:[]};
  if(question)state.input_request={id:'q',reason:'平台',questions:[{id:'q1',question:'平台?',choices:[]}]};
  const task={id:'task',revision:0,state,catalog:{sku:{name:'桂花茶',spec:'500mL'}}};
  let received=false,pollBroken=pollFails,unavailable=offlineFirst;
  async function request(path,options={}){
    const body=options.body?JSON.parse(options.body):null;calls.push({path,body});
    if(path.endsWith('/config'))return {mode:'mock'};
    if(path==='/api/agent/conversations')return body?{id:'task'}:{conversations:[]};
    if(path==='/api/agent/conversations/task')return structuredClone(task);
    if(path.includes('/submissions/'))return received?{found:true,run_id:'run',status:'succeeded'}:{found:false};
    if(path.endsWith('/runs/run')){if(pollBroken){pollBroken=false;throw Error('poll offline');}return runFailed?{status:'failed',error:'执行失败'}:{status:'succeeded'};}
    if(path.endsWith('/messages')||path.endsWith('/answers')){
      if(unavailable){unavailable=false;throw Error('offline');}
      if(reject)throw Object.assign(Error('版本已更新'),{status:409});
      received=true;if(lost)throw Error('response lost');return malformed?{}:{run_id:'run'};
    }
    throw Error('Unexpected request '+path);
  }
  const storage={getItem:k=>disk.get(k)||null,setItem:(k,v)=>disk.set(k,v),removeItem:k=>disk.delete(k)};
  Object.assign(globalThis,{document:doc,sessionStorage:storage,localStorage:storage,location:{search:''},requestAnimationFrame:cb=>cb(),CustomEvent:class{},__agentTest:{request,sendState}});
  if(question)storage.setItem('agent-batch:task:q',JSON.stringify({q1:{choice_id:'xiaohongshu'}}));
  const injected=source.replace(/^import .*send-state.js';$/m,'const {createSendState,prepareAttempt,restoredDraft,acceptedDraft,submissionPath}=globalThis.__agentTest.sendState;')
    .replace(/^import .*services\/api.js';$/m,'const {request}=globalThis.__agentTest;const verifyAccess=()=>{};')
    .replace(/^import .*agent-workspace.js';$/m,"const attachmentCards=()=>'',bindAttachmentCards=()=>{},setupWorkspace=()=>{};");
  const controller=await import('data:text/javascript;base64,'+Buffer.from(injected+'\n// '+sequence++).toString('base64'));
  await controller.initializeAgent({taskId:'task'});
  const settle=async()=>{for(let i=0;i<30;i++){await new Promise(resolve=>setImmediate(resolve));if(!controller.currentAgent().busy)return;}throw Error('controller stayed busy');};
  return {nodes,disk,calls,controller,settle,submit:async text=>{nodes.get('message').value=text;nodes.get('message').listeners.input();nodes.get('chat').onsubmit({preventDefault(){}});await settle();}};
}
test('explicit rejection keeps editable answer, options and SKU without a fake sent bubble',async()=>{
  const h=await harness({reject:true,question:true});await h.submit('补充文字');
  assert.equal(h.nodes.get('message').value,'补充文字');
  assert.match(h.disk.get('agent-batch:task:q'),/xiaohongshu/);
  assert.equal(h.controller.currentAgent().task.state.brief.sku_id,'sku');
  assert.equal(JSON.parse(h.disk.get('agent-send:task')).state,'rejected');
  assert.doesNotMatch(h.nodes.get('messages').innerHTML,/class="message user"/);
  assert.ok(h.calls.some(c=>c.path.endsWith('/answers')));
});
test('lost response is reconciled by receipt without a second POST; newer typing survives',async()=>{
  const h=await harness({lost:true});await h.submit('原消息');
  assert.equal(JSON.parse(h.disk.get('agent-send:task')).state,'unknown');
  h.nodes.get('message').value='较新输入';
  await h.nodes.get('checkSubmission').onclick();await h.settle();
  assert.equal(h.calls.filter(c=>c.path.endsWith('/messages')).length,1);
  assert.equal(h.nodes.get('message').value,'较新输入');assert.equal(h.disk.get('agent-send:task'),undefined);
});
test('accepted request with polling failure keeps run and only resumes polling',async()=>{
  const h=await harness({pollFails:true});await h.submit('原消息');
  const attempt=JSON.parse(h.disk.get('agent-send:task'));
  assert.equal(attempt.state,'accepted');assert.equal(attempt.runId,'run');
  assert.equal(h.nodes.get('message').value,'');
  await h.nodes.get('checkSubmission').onclick();await h.settle();
  assert.equal(h.calls.filter(c=>c.path.endsWith('/messages')).length,1);
  assert.equal(h.disk.get('agent-send:task'),undefined);
});
test('unknown with no receipt waits for explicit retry and reuses the full original request',async()=>{
  const h=await harness({offlineFirst:true});await h.submit('原消息');
  assert.equal(h.calls.filter(c=>c.path.endsWith('/messages')).length,1);
  await h.nodes.get('checkSubmission').onclick();await h.settle();
  assert.equal(h.calls.filter(c=>c.path.endsWith('/messages')).length,1);
  await h.nodes.get('sendRecovery').retry.onclick();await h.settle();
  const posts=h.calls.filter(c=>c.path.endsWith('/messages'));
  assert.deepEqual(posts[0].body,posts[1].body);assert.equal(h.nodes.get('message').value,'');
});
test('invalid success response stays unknown and protects draft for receipt lookup',async()=>{
  const h=await harness({malformed:true});await h.submit('原消息');
  assert.equal(JSON.parse(h.disk.get('agent-send:task')).state,'unknown');
  assert.equal(h.nodes.get('message').value,'原消息');
});
test('new product conversation passes SKU before any message, and editing text needs no transient patch',async()=>{
  const h=await harness();await h.controller.createAgent('brand',{skuId:'sku',text:'初始预填'});
  assert.deepEqual(h.calls.find(c=>c.path==='/api/agent/conversations'&&c.body).body,{brand_id:'brand',demo:false,sku_id:'sku'});
  assert.equal(h.calls.filter(c=>c.path.endsWith('/messages')).length,0);
  await h.submit('编辑后的文案要求');assert.equal(h.controller.currentAgent().task.state.brief.sku_id,'sku');
});
test('failed generation is still an accepted submission and never restored as unsent',async()=>{
  const h=await harness({runFailed:true});await h.submit('原消息');
  assert.equal(h.nodes.get('message').value,'');assert.equal(h.nodes.get('error').textContent,'执行失败');
  assert.equal(h.disk.get('agent-send:task'),undefined);
  assert.equal(h.calls.filter(c=>c.path.endsWith('/messages')).length,1);
});
