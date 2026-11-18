import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {chromium}=await import(pathToFileURL(process.argv[2]).href);
const base=process.argv[3],accounts=JSON.parse(await readFile(process.argv[4],'utf8'));
const browser=await chromium.launch({headless:true,channel:'msedge'});
const page=await browser.newPage({viewport:{width:1100,height:800}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
async function login(account){await page.fill('#username',account.username);await page.fill('#password',account.password);await page.locator('#login button').click();await page.waitForURL('**/#/chat/**');await page.waitForFunction(()=>document.querySelector('#history button'));}
try{
 await page.goto(base+'/agent.html');await page.waitForURL('**/login.html');
 await page.fill('#username','missing');await page.fill('#password','invalid-test-password');await page.locator('#login button').click();await page.waitForFunction(()=>document.getElementById('loginError').textContent.length>0);
 await page.screenshot({path:'.local-data/agent-login.png'});
 await login(accounts[0]);const first=await page.evaluate(()=>localStorage.getItem('marketing-agent-task'));
 await page.locator('.session-logout').click();await page.waitForURL('**/login.html');
 assert.equal((await page.request.get(base+'/api/agent/conversations/'+first)).status(),401);
 await login(accounts[1]);assert.equal((await page.request.get(base+'/api/agent/conversations/'+first)).status(),404);
 const list=await (await page.request.get(base+'/api/agent/conversations')).json();assert.equal(list.conversations.length,1);
 assert.deepEqual(errors,[]);console.log('PASS: login redirect, invalid password, logout, different workspace isolation');
}finally{await browser.close();}
