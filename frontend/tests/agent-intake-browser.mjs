// Upload-first intake, chat completion, durable state, backend gates, then marketing.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.argv[2]).href);
const base=process.argv[3]||'http://127.0.0.1:8025';
const browser=await chromium.launch({headless:true,channel:'msedge'});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function ready(){await page.waitForFunction(()=>!document.querySelector('#message').disabled);}
async function say(text){
 const n=await page.locator('.message.assistant').count();
 await page.fill('#message',text);await page.press('#message','Enter');
 await page.waitForFunction(n=>!document.querySelector('#message').disabled&&document.querySelectorAll('.message.assistant').length>n,n);
 assert(await page.locator('#error').isHidden(),await page.locator('#error').innerText());
}
async function task(){const id=await page.evaluate(()=>localStorage.getItem('marketing-agent-task'));return (await page.request.get(base+'/api/agent/conversations/'+id)).json();}
try{
 await page.goto(base+'/agent.html');await page.waitForSelector('#attach');await ready();
 await page.click('#attach');
 assert(await page.locator('#attachmentDialog').isVisible());
 assert(!(await page.locator('#brandDialog').isVisible()));
 await page.setInputFiles('#attachmentFile',{name:'brand.txt',mimeType:'text/plain',buffer:Buffer.from('品牌名称：对话建档测试（虚构）\n产品名称：桂花鲜奶茶\n价格：18元')});
 await page.click('#uploadAttachment');await page.waitForSelector('[data-confirm-attachment]');await ready();
 assert(await page.locator('[data-confirm-attachment]').isDisabled());
 assert((await task()).state.pending_fields.includes('brand.intro'));
 assert.equal(await page.locator('.question-item').count(),2);
 await say('品牌介绍：校园花香茶饮品牌');
 await page.waitForFunction(()=>!document.querySelector('#message').disabled&&document.querySelector('#inputRequest')?.textContent.includes('卖点'));
 await ready();
 assert((await task()).state.pending_fields.includes('products.0.selling'));
 await page.reload();await page.waitForSelector('[data-confirm-attachment]');await ready();
 assert((await task()).state.pending_fields.includes('products.0.selling'));
 await say('桂花香气与鲜奶风味');
 assert(!(await page.locator('[data-confirm-attachment]').isDisabled()));
 await page.click('[data-confirm-attachment]');
 await page.waitForFunction(()=>!document.querySelector('#message').disabled&&!document.querySelector('[data-confirm-attachment]'));
 const t=await task(),pid=Object.keys(t.catalog)[0];assert(pid);
 assert.equal(t.brand_name,'对话建档测试（虚构）');
 const csv='product_id,current_start,current_end,previous_start,previous_end,current_qty,previous_qty,variable_cost_minor,min_contribution_minor\n'+pid+',2026-11-02,2026-11-16,2026-10-19,2026-11-02,140,200,,500\n';
 await page.click('#attach');await page.selectOption('#attachmentKind','business');
 await page.setInputFiles('#attachmentFile',{name:'sales.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
 await page.click('#uploadAttachment');await page.waitForSelector('[data-confirm-attachment]');await ready();
 assert(await page.locator('[data-confirm-attachment]').isDisabled());
 await say('6.5元');assert.equal((await task()).attachments.at(-1).payload.rows[0].variable_cost_minor,650);
 await page.click('[data-confirm-attachment]');
 await page.waitForFunction(()=>!document.querySelector('#message').disabled&&!document.querySelector('[data-confirm-attachment]'));
 await say('桂花鲜奶茶，小红书，下周，预算200元，预计花费200元，预计销量160杯，第二杯半价');
 await page.waitForSelector('#confirm');await page.click('#confirm');await page.waitForSelector('.artifact');await ready();
 assert.equal((await task()).state.stage,'completed');
 await say('只把语气改得活泼一点');
 await page.click('#rememberStyle');
 await page.waitForFunction(()=>!document.querySelector('#message').disabled&&document.querySelector('#messages').textContent.includes('已按你的确认保存'));
 const oldTask=(await task()).id;
 await page.click('#newTask');
 await page.waitForFunction(id=>localStorage.getItem('marketing-agent-task')!==id&&!document.querySelector('#message').disabled,oldTask);await ready();
 await say('主推桂花鲜奶茶');
 await page.waitForSelector('[data-answer="xiaohongshu"]');
 await page.click('[data-answer="xiaohongshu"]');
 await page.fill('#message','预算200元');
 await page.click('#submitBatch');
 await page.waitForFunction(()=>!document.querySelector('#message').disabled&&document.querySelector('#inputRequest')?.textContent.includes('开始'));
 assert.equal((await task()).state.brief.platform,'xiaohongshu');
 await page.screenshot({path:'.local-data/agent-intake-desktop.png'});
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.locator('#submitBatch').scrollIntoViewIfNeeded();
 const button=await page.locator('#submitBatch').boundingBox(),composer=await page.locator('.composer-wrap').boundingBox();
 assert(button.y+button.height<=composer.y,'补充按钮应可滚动到输入栏上方');
 await page.screenshot({path:'.local-data/agent-intake-mobile.png'});
 assert.deepEqual(errors,[]);
 console.log('PASS: upload-first, missing fields, short answers, reload, confirmation, business supplement, marketing generation, mobile');
}finally{await browser.close();}
