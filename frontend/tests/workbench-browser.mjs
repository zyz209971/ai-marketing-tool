// Run against an isolated offline runtime, never the user's working database.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.argv[2]).href);
const base=process.argv[3]||'http://127.0.0.1:8028';
const browser=await chromium.launch({headless:true,channel:'msedge'});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
page.on('pageerror',e=>errors.push(e.message));
async function ready(){await page.waitForFunction(()=>document.querySelector('#message')&&!document.querySelector('#message').disabled&&location.hash.startsWith('#/chat/'));}
async function task(){const id=await page.evaluate(()=>localStorage.getItem('marketing-agent-task'));return (await page.request.get(base+'/api/agent/conversations/'+id)).json();}
async function navigate(view){await page.locator(`#primaryNav [data-view="${view}"]`).click();await page.waitForFunction(v=>document.body.dataset.view===v,view);}
async function say(text){const n=await page.locator('.message.assistant').count();await page.fill('#message',text);await page.press('#message','Enter');await page.waitForFunction(n=>!document.querySelector('#message').disabled&&document.querySelectorAll('.message.assistant').length>n,n);assert(await page.locator('#error').isHidden(),await page.locator('#error').innerText());}
try{
 await page.goto(base+'/');await ready();
 assert.equal(await page.locator('#primaryNav a').count(),5);assert(await page.locator('#contextPanel').isVisible());
 await page.screenshot({path:'.local-data/workbench-empty.png'});
 await page.click('#attach');await page.setInputFiles('#attachmentFile',{name:'brand.txt',mimeType:'text/plain',buffer:Buffer.from('品牌名称：山茶小站 UI 验收\n产品名称：桂花鲜奶茶\n规格：500ml')});await page.click('#uploadAttachment');
 await page.waitForFunction(()=>!document.querySelector('#attachmentDialog').open&&!document.querySelector('#message').disabled);
 assert.equal(await page.locator('.question-item').count(),2);
 await say('品牌介绍：校园茶饮品牌；可核实的商品卖点：桂花香气');
 await page.click('[data-confirm-attachment]');await page.waitForFunction(()=>!document.querySelector('#message').disabled&&!document.querySelector('[data-confirm-attachment]'));
 const intake=await task(),brandId=intake.state.brief.brand_id,skuId=Object.keys(intake.catalog)[0];
 await page.waitForFunction(()=>document.querySelector('.context-brand strong')?.textContent.includes('山茶小站'));
 await page.fill('#message','这条是还未发送的草稿');await navigate('products');
 await page.waitForSelector('.catalog-product');assert((await page.locator('.catalog-product').first().innerText()).includes('桂花鲜奶茶'));
 await navigate('chat');assert.equal(await page.inputValue('#message'),'这条是还未发送的草稿');
 await navigate('products');await page.click('.product-compose');await ready();
 assert.notEqual((await task()).id,intake.id);assert.equal((await task()).state.brief.brand_id,brandId);
 assert((await page.inputValue('#message')).includes('桂花鲜奶茶'));
 let posted;page.on('request',r=>{if(r.url().endsWith('/messages'))posted=r.postDataJSON();});
 const composed=await page.inputValue('#message');await say(composed);
 assert.equal(posted.patch.sku_id,skuId);
 // Select platform if this prompt left it unspecified.
 if(!(await task()).state.artifacts.length)await say('小红书，普通商品介绍，不做优惠活动');
 await page.waitForSelector('.artifact');const contentTask=await task();
 await page.screenshot({path:'.local-data/workbench-desktop.png'});
 await navigate('creations');await page.getByRole('button',{name:'回到对话继续修改'}).first().click();await ready();assert.equal((await task()).id,contentTask.id);
 await navigate('conversations');await page.waitForSelector('.conversation-record');await page.fill('#conversationSearch','山茶小站');
 await page.waitForFunction(()=>document.querySelector('.conversation-record p')?.textContent.includes('山茶小站'));
 await page.locator(`.conversation-record[href="#/chat/${contentTask.id}"]`).click();await ready();
 // Keep a request pending while leaving chat; background completion must not redirect management.
 let release;const gate=new Promise(r=>release=r);let held=false;
 await page.route('**/api/agent/runs/*',async route=>{if(!held){held=true;await gate;}await route.continue();});
 await page.fill('#message','只改标题，活泼一点');await page.press('#message','Enter');
 await page.waitForFunction(()=>document.querySelector('#message').disabled);
 await navigate('products');await page.waitForSelector('.catalog-product');assert(await page.locator('#managementRoot').isVisible());
 release();await page.waitForFunction(()=>!document.querySelector('#message').disabled);await page.unroute('**/api/agent/runs/*');
 assert.equal(await page.evaluate(()=>document.body.dataset.view),'products');
 // Browsing another brand doesn't change the active conversation's brand.
 const other=await (await page.request.post(base+'/api/knowledge/brands',{data:{name:'另一品牌',intro:'仅用于浏览隔离测试'}})).json();
 await page.reload();await page.waitForFunction(()=>document.querySelector('#workspaceBrand option')&&[...document.querySelector('#workspaceBrand').options].some(o=>o.text==='另一品牌'));
 await page.selectOption('#workspaceBrand',other.id);await navigate('chat');await ready();
 assert.equal((await task()).state.brief.brand_id,brandId);assert.equal(await page.inputValue('#workspaceBrand'),brandId);
 await page.goto(base+'/agent.html?task='+contentTask.id);await ready();assert.equal((await task()).id,contentTask.id);
 const beforeIds=(await (await page.request.get(base+'/api/agent/conversations?limit=100')).json()).conversations.map(t=>t.id).sort();
 await navigate('conversations');await page.waitForSelector('.conversation-record');await page.goBack();await ready();
 assert.equal((await task()).id,contentTask.id);await page.reload();await ready();
 const afterIds=(await (await page.request.get(base+'/api/agent/conversations?limit=100')).json()).conversations.map(t=>t.id).sort();
 assert.deepEqual(afterIds,beforeIds);
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:'.local-data/workbench-mobile.png'});
 await page.click('#toggleContext');assert(await page.locator('#contextPanel').isVisible());await page.click('.context-close');assert(await page.locator('#contextPanel').isHidden());
 await page.click('#toggleSidebar');await navigate('products');await page.waitForSelector('.catalog-product');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:'.local-data/workbench-products-mobile.png'});
 assert.deepEqual(errors,[]);
 console.log('PASS: upload/batched intake, actual context, draft retention, SKU compose, works, history, navigation during run, brand isolation, legacy link and mobile layout');
}catch(e){await page.screenshot({path:'.local-data/workbench-failure.png'});console.error('Browser errors:',errors);throw e;}finally{await browser.close();}
