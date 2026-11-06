// 这些单元测试使用请求替身，不读取 backend/.env，不调用模型或真实后端。
import test from 'node:test';
import assert from 'node:assert/strict';
import {toRequest,adaptContents,imageSource,generateCampaign,generateImage,reviseImage,rewriteContent,searchProducts,request,visitorId} from '../src/services/api.js';

function memoryStorage() { const values=new Map(); return {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key)}; }
globalThis.localStorage=memoryStorage();
globalThis.sessionStorage=memoryStorage();
const draft={brand:{id:'b',name:'品牌',intro:'品牌介绍',position:'下午茶'},goal:'新品推广',ps:[{id:'p',name:'商品',selling:'轻便、便携',price:''}],plats:['小红书','抖音','微信公众号'],format:'图文',merge:'separate',style:'自然'};
const content={id:'c',platform:'xiaohongshu',title:'标题',body:'正文',summary:'',hashtags:['分享'],product_label:'商品',product_ids:['p']};

test('保留品牌、多产品策略和抖音，空价格保持 null',()=>{
  const body=toRequest(draft); assert.deepEqual(body.platforms,['xiaohongshu','douyin','wechat_official_account']);
  assert.equal(body.products[0].price,null); assert.equal(body.product_strategy,'separate'); assert.equal(body.brand.positioning,'下午茶');
});
test('结果映射保留产品关联和后端演示状态',()=>{
  const row=adaptContents({contents:[{...content,mock:true}]})[0]; assert.equal(row.platform,'小红书'); assert.deepEqual(row.productIds,['p']); assert.equal(row.mock,true);
  assert.throws(()=>adaptContents({contents:[{platform:'xiaohongshu',body:'缺少标题'}]}));
});
test('兼容 URL、Base64 与后端 SVG 占位图',()=>{
  assert.equal(imageSource({url:'https://example.test/a.png'}),'https://example.test/a.png');
  assert.equal(imageSource({format:'png',base64:'abc'}),'data:image/png;base64,abc');
  assert.equal(imageSource({format:'svg+xml',base64:'abc'}),'data:image/svg+xml;base64,abc'); assert.throws(()=>imageSource({url:'javascript:alert(1)'}));
});
test('访客标识复用原页面 visitor_id',()=>{ localStorage.setItem('visitor_id','original-visitor'); assert.equal(visitorId(),'original-visitor'); });
test('真实请求结构、图片独立失败、改图与改文案的接口彼此独立',async()=>{
  const oldFetch=globalThis.fetch,calls=[]; sessionStorage.setItem('marketing_access_key','application-access-password');
  globalThis.fetch=async(url,options)=>{
    const payload=options.body?JSON.parse(options.body):{}; calls.push({url,options,payload});
    if (url.endsWith('/copywriting')) return {ok:true,json:async()=>({status:'succeeded',contents:[content]})};
    if (url.endsWith('/images')) return {ok:false,status:502,json:async()=>({detail:'生图失败'})};
    if (url.endsWith('/images/revise')) return {ok:true,json:async()=>({image:{format:'png',base64:'abc'},final_prompt:'修订提示词'})};
    if (url.endsWith('/copywriting/rewrite')) return {ok:true,json:async()=>({content:{...content,body:'改写正文'}})};
    if (url.endsWith('/products/search')) return {ok:true,json:async()=>({products:[]})};
    throw Error('意外请求');
  };
  try {
    const [row]=await generateCampaign(draft); assert.equal(calls.length,1); assert.equal(calls[0].payload.generation_mode,'text_only');
    await assert.rejects(generateImage(row,{...draft,referencePoster:'data:image/png;base64,abc'}),/生图失败/); assert.equal(row.body,'正文');
    assert.deepEqual(calls[1].payload.content.product_ids,['p']); assert.ok(calls[1].payload.campaign.reference_poster);
    const image=await reviseImage('原提示词','绿色背景'); assert.equal(image.finalPrompt,'修订提示词');
    const updated=await rewriteContent(row,'自然一点'); assert.equal(updated.body,'改写正文');
    await searchProducts('local-brand','商品',true); assert.equal(calls[4].payload.semantic,true);
    assert.equal(calls[0].options.headers['X-Visitor-Id'],'original-visitor'); assert.equal(calls[0].options.headers['X-Access-Key'],'application-access-password');
    assert.ok(!calls.some(call=>JSON.stringify(call.payload).includes('api_key')));
  } finally { globalThis.fetch=oldFetch; sessionStorage.removeItem('marketing_access_key'); }
});
test('取消信号传递到请求层',async()=>{
  const original=globalThis.fetch; globalThis.fetch=async(url,options)=>{ if (options.signal.aborted) throw new DOMException('cancelled','AbortError'); };
  try { const controller=new AbortController(); controller.abort(); await assert.rejects(request('/cancel',{signal:controller.signal}),{name:'AbortError'}); }
  finally { globalThis.fetch=original; }
});
