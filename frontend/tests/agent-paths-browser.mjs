// Four-path conversation, conflicts and shared archive. Run against an isolated offline server.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.argv[2]).href);
const base=process.argv[3]||'http://127.0.0.1:8027';
const browser=await chromium.launch({headless:true,channel:'msedge'});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
async function ready(){await page.waitForFunction(()=>document.querySelector('#message')&&!document.querySelector('#message').disabled);}
async function task(){const id=await page.evaluate(()=>localStorage.getItem('marketing-agent-task'));return (await page.request.get(base+'/api/agent/conversations/'+id)).json();}
async function say(text){const n=await page.locator('.message.assistant').count();await page.fill('#message',text);await page.press('#message','Enter');await page.waitForFunction(n=>!document.querySelector('#message').disabled&&document.querySelectorAll('.message.assistant').length>n,n);assert(await page.locator('#error').isHidden(),await page.locator('#error').innerText());}
async function upload(text){await page.click('#attach');await page.selectOption('#attachmentKind','knowledge');await page.setInputFiles('#attachmentFile',{name:'brand.txt',mimeType:'text/plain',buffer:Buffer.from(text)});await page.click('#uploadAttachment');await page.waitForFunction(()=>!document.querySelector('#attachmentDialog').open&&!document.querySelector('#message').disabled);}
async function confirm(){await page.click('[data-confirm-attachment]');await page.waitForFunction(()=>!document.querySelector('#message').disabled&&!document.querySelector('[data-confirm-attachment]'));}
try{
 await page.goto(base+'/agent.html');await ready();
 assert((await page.locator('#brandLabel').innerText()).includes('新品牌'));
 assert.deepEqual((await task()).catalog,{});
 await upload('品牌名称：四路径浏览器测试\n产品名称：桂花茶\n规格：500ml');
 assert.equal(await page.locator('.question-item').count(),2);
 await say('品牌介绍：校园茶饮品牌；可核实的商品卖点：桂花香气');
 await confirm();
 await say('帮我写小红书桂花茶商品介绍，不做优惠活动');
 assert.equal((await task()).state.brief.task_kind,'content');
 assert.equal(await page.locator('.artifact').count(),1);
 assert(!(await page.locator('.artifact').innerText()).includes('vnull'));
 const taskId=(await task()).id;
 await say('只检查第二杯半价是否满足成本');
 assert((await task()).state.pending_fields.includes('products.0.price'));
 await say('单杯售价：18元');await confirm();
 assert.equal(await page.locator('.question-item').count(),2);
 await say('单杯成本6.5元，最低贡献5元');
 await page.waitForSelector('#unitResult');
 assert((await page.locator('#unitResult').innerText()).includes('¥7.00'));
 await upload('产品名称：桂花茶\n规格：500ml\n价格：20元\n卖点：桂花香气');
 await page.waitForSelector('[data-conflict]');
 assert((await task()).attachments.at(-1).payload.conflicts.some(c=>c.field==='price'));
 await page.screenshot({path:'.local-data/agent-paths-conflict.png',fullPage:false});
 for(const box of await page.locator('[data-conflict]').all())await box.check();
 await confirm();
 await say('帮我写小红书桂花茶商品介绍，不做优惠活动');
 const t=await task();assert.equal(t.state.stage,'completed');
 const workspace=await (await page.request.get(base+'/api/knowledge/workspace')).json();
 const work=workspace.works.find(w=>w.agent_origin?.task_id===taskId&&!w.agent_origin.stale);assert(work);
 await page.screenshot({path:'.local-data/agent-paths-desktop.png',fullPage:false});
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:'.local-data/agent-paths-mobile.png',fullPage:false});
 await page.goto(base+'/agent.html?task='+taskId);await ready();assert.equal((await task()).id,taskId);
 await page.setViewportSize({width:1440,height:1000});
 await page.locator('#primaryNav [data-view="creations"]').click();
 await page.getByRole('button',{name:'回到对话继续修改'}).first().click();
 await page.waitForURL('**/#/chat/'+taskId);await ready();
 assert.equal((await task()).id,taskId);
 assert.deepEqual(errors,[]);
 console.log('PASS: upload, batched questions, ordinary copy, deferred price, unit check, conflict acceptance, archive and mobile layout');
}finally{await browser.close();}
