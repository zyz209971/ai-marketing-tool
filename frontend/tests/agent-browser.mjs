// Chat-only E2E; no structured form or test-case injection in the product UI.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.argv[2]?pathToFileURL(process.argv[2]).href:'playwright');
const base=process.argv[3]||'http://127.0.0.1:8021';
let browser;
try{browser=await chromium.launch({headless:true});}catch{browser=await chromium.launch({headless:true,channel:'msedge'});}
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function say(text){
 const count=await page.locator('#messages .message.assistant').count();
 await page.fill('#message',text);await page.press('#message','Enter');
 await page.waitForFunction(n=>!document.querySelector('#message').disabled&&document.querySelectorAll('#messages .message.assistant').length>n,count,{timeout:30000});
 assert(await page.locator('#error').isHidden(),await page.locator('#error').textContent());
}
try{
 await page.goto(base+'/agent.html');
 await page.waitForFunction(()=>document.querySelector('#stage')?.textContent==='正在聊需求');
 assert.equal(await page.locator('#briefForm').count(),0);
 assert.equal(await page.locator('#trace').count(),0);
 await mkdir('.local-data',{recursive:true});
 await page.screenshot({path:'.local-data/agent-chat-desktop.png'});
 await say('帮我制定下周的促销方案');
 assert.match(await page.locator('#messages .assistant').last().innerText(),/主推/);
 await say('茉莉鲜奶茶，小红书，第二杯半价');
 await say('200元');await say('就按预算花');await say('160杯');
 await page.waitForSelector('#confirm',{timeout:30000});
 assert.match(await page.locator('#strategy').innerText(),/第二杯5折/);
 assert.equal(await page.locator('#strategy').evaluate(el=>!!el.closest('#messages .message.assistant')),true);
 await page.click('#confirm');
 await page.waitForFunction(()=>document.querySelectorAll('.artifact').length===1&&!document.querySelector('#message').disabled,{timeout:30000});
 assert.match(await page.locator('.artifact').innerText(),/第二杯5折/);
 await page.reload();
 await page.waitForFunction(()=>document.querySelectorAll('.artifact').length===1&&!document.querySelector('#message').disabled);
 await say('标题活泼一点');
 assert.equal(await page.locator('.artifact').count(),2);
 assert.match(await page.locator('.artifact').last().innerText(),/来一杯/);
 await say('好的，不过第二杯改成七折');
 await page.waitForSelector('#confirm');
 assert.match(await page.locator('#strategy').innerText(),/v2/);
 assert.equal(await page.locator('.artifact.stale').count(),2);
 await page.screenshot({path:'.local-data/agent-chat-plan.png'});
 await page.click('#newTask');
 await page.waitForFunction(()=>document.querySelectorAll('#messages .message').length===1);
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile overflow');
 const composer=await page.locator('#chat').boundingBox();
 assert(composer.y+composer.height<=844,'composer must stay visible');
 await page.screenshot({path:'.local-data/agent-chat-mobile.png'});
 assert.deepEqual(errors,[]);
 console.log('PASS: chat-only clarification, short answers, inline confirmation, generation, reload, rewrite, invalidation, desktop/mobile');
}finally{await browser.close();}
