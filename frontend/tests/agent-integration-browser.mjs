// Brand-scoped integration: browser uploads, confirmation, proposals, local revision.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.argv[2]).href);
const base=process.argv[3]||'http://127.0.0.1:8024';
const browser=await chromium.launch({headless:true,channel:'msedge'});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function say(text){const n=await page.locator('.message.assistant').count();await page.fill('#message',text);await page.press('#message','Enter');await page.waitForFunction(n=>!document.querySelector('#message').disabled&&document.querySelectorAll('.message.assistant').length>n,n);assert(await page.locator('#error').isHidden(),await page.locator('#error').innerText());}
try{
 await page.goto(base+'/agent.html');await page.waitForFunction(()=>document.querySelector('#stage').textContent==='正在聊需求');
 await page.click('#chooseBrand');await page.locator('#brandDialog summary').click();
 await page.fill('#brandName','整合验收品牌（合成）');await page.fill('#brandIntro','用于本地验收的虚构品牌，不代表真实经营数据。');await page.click('#createBrand');
 await page.waitForFunction(()=>document.querySelector('#brandLabel').textContent.includes('整合验收'));
 await page.click('#attach');
 await page.setInputFiles('#attachmentFile',{name:'brand.txt',mimeType:'text/plain',buffer:Buffer.from('品牌名称：整合验收品牌（合成）\n品牌介绍：用于本地验收的虚构花香茶饮品牌\n表达风格：温柔简洁\n产品名称：桂花鲜奶茶\n价格：18元\n卖点：桂花香气')});
 await page.click('#uploadAttachment');await page.waitForSelector('[data-confirm-attachment]');
 await page.click('[data-confirm-attachment]');await page.waitForFunction(()=>!document.querySelector('#message').disabled&&document.querySelectorAll('[data-confirm-attachment]').length===0);
 const id=await page.evaluate(()=>localStorage.getItem('marketing-agent-task'));
 const task=await (await page.request.get(base+'/api/agent/conversations/'+id)).json();
 const pid=Object.keys(task.catalog)[0];assert(pid);
 const csv='product_id,current_start,current_end,previous_start,previous_end,current_qty,previous_qty,variable_cost_minor,min_contribution_minor,daily_capacity\n'+pid+',2026-11-02,2026-11-16,2026-10-19,2026-11-02,140,200,650,500,200\n';
 await page.click('#attach');await page.selectOption('#attachmentKind','business');
 await page.setInputFiles('#attachmentFile',{name:'business.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
 await page.click('#uploadAttachment');await page.waitForSelector('[data-confirm-attachment]');await page.click('[data-confirm-attachment]');
 await page.waitForFunction(()=>!document.querySelector('#message').disabled&&document.querySelectorAll('[data-confirm-attachment]').length===0);
 await say('桂花鲜奶茶，小红书，下周，预算200元，预计花费200元，预计销量160杯，帮我比较活动方案');
 await page.waitForSelector('[data-option]');assert.equal(await page.locator('[data-option]').count(),3);
 await page.locator('[data-option="1"]').click();await page.waitForSelector('#confirm');
 await page.click('#confirm');await page.waitForSelector('.artifact');
 await page.waitForFunction(()=>!document.querySelector('#message').disabled);
 const body=await page.locator('.artifact .prose').last().innerText();
 await say('只把标题改得活泼一点，正文不动');
 assert.equal(await page.locator('.artifact').count(),2);assert.equal(await page.locator('.artifact .prose').last().innerText(),body);
 await page.reload();await page.waitForSelector('.artifact');assert.equal(await page.locator('.artifact').count(),2);
 await page.screenshot({path:'.local-data/agent-integration-desktop.png'});
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.screenshot({path:'.local-data/agent-integration-mobile.png'});
 assert.deepEqual(errors,[]);console.log('PASS: brand creation, knowledge review, business CSV, proposal selection, approval, title-only edit, reload, mobile');
}finally{await browser.close();}
