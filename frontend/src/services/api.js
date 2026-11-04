import {config} from '../config.js';
import {generateMock} from './mock.js';

export const mode = config.mode;
export const platformIds = {'小红书':'xiaohongshu','抖音':'douyin','微信公众号':'wechat_official_account'};
const platformNames = Object.fromEntries(Object.entries(platformIds).map(([name,id])=>[id,name]));
export const endpoints = {copy:'/api/v2/copywriting',image:'/api/v2/images',reviseImage:'/api/v2/images/revise',rewrite:'/api/v2/copywriting/rewrite',search:'/api/v2/products/search'};
const uid = ()=>globalThis.crypto?.randomUUID?.()||('local_'+Date.now().toString(36)+Math.random().toString(36).slice(2));

export function visitorId() {
  let id = localStorage.getItem('visitor_id');
  if (!id) { id = 'v_' + uid(); localStorage.setItem('visitor_id',id); }
  return id;
}
export async function request(path,{signal,timeout=30000,...options}={}) {
  const controller = new AbortController();
  const onAbort = ()=>controller.abort(signal.reason);
  if (signal?.aborted) onAbort(); else signal?.addEventListener('abort',onAbort,{once:true});
  const timer = setTimeout(()=>controller.abort(new Error('timeout')),timeout);
  try {
    const response = await fetch(config.apiBaseUrl.replace(/\/$/,'')+path,{
      ...options,headers:{'Content-Type':'application/json','X-Visitor-Id':visitorId(),
        'X-Access-Key':sessionStorage.getItem('marketing_access_key')||'',...options.headers},signal:controller.signal
    });
    const data = await response.json();
    if (!response.ok) {
      let detail = data.detail || data.error;
      if (Array.isArray(detail)) detail = detail.map(item=>item.msg).join('；');
      const error = Error(typeof detail==='string'?detail:`服务请求失败（${response.status}）。`);
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (signal?.aborted) throw new DOMException('已取消请求','AbortError');
    if (controller.signal.aborted) throw Error('服务响应超时，请检查后端日志后再决定是否重试。');
    throw error;
  } finally { clearTimeout(timer); signal?.removeEventListener('abort',onAbort); }
}
const post = (path,body,options={})=>request(path,{method:'POST',body:JSON.stringify(body),...options});
export const getHealth = ()=>request('/api/health');
export const getQuota = ()=>request('/api/quota');
export async function verifyAccess(key) {
  const result = await post('/api/verify_key',{key});
  if (!result.ok) throw Error(result.reason||'访问密码错误。');
  sessionStorage.setItem('marketing_access_key',key);
}
export function toRequest(draft) {
  return {
    brand:{id:draft.brand.id,name:draft.brand.name,description:draft.brand.intro,positioning:draft.brand.position||'',style:draft.style||''},
    marketing_goal:{'新品推广':'new_product','促销':'promotion','品牌曝光':'brand_awareness','节日活动':'holiday'}[draft.goal],
    products:draft.ps.map(p=>({id:p.id,name:p.name,price:p.price||null,selling_points:p.selling.split(/[、，,]/).map(x=>x.trim()).filter(Boolean)})),
    platforms:draft.plats.map(p=>platformIds[p]),generation_mode:draft.format==='图文'?'text_and_image':draft.format==='仅图片'?'image_only':'text_only',
    product_strategy:draft.merge==='separate'?'separate':'merged',theme:draft.theme||'',promotion_rules:draft.rules||'',activity_time:draft.dates||'',
    additional_selling_points:draft.points||'',style_requirements:draft.style||''
  };
}
export function adaptContents(response) {
  if (!Array.isArray(response.contents)||!response.contents.length) throw Error('后端没有返回可用内容。');
  return response.contents.map(c=>{
    if (!platformNames[c.platform]||typeof c.title!=='string'||!c.title.trim()||typeof c.body!=='string'||!c.body.trim()) throw Error('后端结果缺少有效的平台、标题或正文。');
    return {id:c.id||uid(),platform:platformNames[c.platform],subject:c.product_label||c.title,productIds:c.product_ids||[],title:c.title,
      summary:c.summary||'',body:c.body,tags:Array.isArray(c.hashtags)?c.hashtags.map(t=>'#'+t.replace(/^#/,'')).join(' '):'',
      imageUrl:null,imageStatus:'not_requested',imageError:'',imageVersions:[],finalPrompt:'',parsedPrompt:{},versions:[],saved:false,mock:!!c.mock,references:c.references||[]};
  });
}
export function imageSource(img) {
  if (typeof img?.url==='string'&&/^https?:\/\//.test(img.url)) return img.url;
  if (typeof img?.base64==='string'&&['png','jpeg','jpg','webp','svg+xml'].includes(img.format)) return `data:image/${img.format};base64,${img.base64}`;
  throw Error('图片服务未返回可用图片。');
}
export async function generateCampaign(draft,options={}) {
  if (mode==='mock') return (await generateMock(draft)).map(r=>({...r,mock:true,imageStatus:'not_requested',imageVersions:[],productIds:[],versions:[]}));
  return adaptContents(await post(endpoints.copy,{...toRequest(draft),generation_mode:'text_only'},{...options,timeout:240000}));
}
export async function generateImage(content,draft,options={}) {
  if (mode==='mock') throw Error('本地演示模式不调用图片服务，请连接后端后再使用。');
  const data = await post(endpoints.image,{campaign:{...toRequest(draft),reference_poster:draft.referencePoster||''},
    content:{id:content.id,platform:platformIds[content.platform],title:content.title,body:content.body,
      product_label:content.subject,product_ids:content.productIds||[]},purpose:content.platform==='微信公众号'?'article_cover':'post_image'},{...options,timeout:240000});
  return {imageUrl:imageSource(data.image),imageStatus:data.mock?'mock':'succeeded',imageError:'',finalPrompt:data.final_prompt||'',parsedPrompt:data.parsed_prompt||{}};
}
export async function reviseImage(originalPrompt,feedback,options={}) {
  const data = await post(endpoints.reviseImage,{original_prompt:originalPrompt,feedback},{...options,timeout:240000});
  return {imageUrl:imageSource(data.image),imageStatus:data.mock?'mock':'succeeded',imageError:'',finalPrompt:data.final_prompt||'',parsedPrompt:data.parsed_prompt||{}};
}
export async function rewriteContent(content,instruction,options={}) {
  if (!instruction.trim()) throw Error('请先填写修改意见。');
  if (mode==='mock') return {...content,body:content.body+'\n\n【演示模式：已记录修改意见，未调用模型】',mock:true};
  const data = await post(endpoints.rewrite,{id:content.id,platform:platformIds[content.platform],title:content.title,body:content.body,
    summary:content.summary||'',hashtags:content.tags.split(/\s+/).filter(Boolean).map(t=>t.replace(/^#/,'')),instruction},{...options,timeout:120000});
  return adaptContents({contents:[data.content]})[0];
}
export const searchProducts = (brandId,query,semantic=false,options={})=>post(endpoints.search,{client_brand_id:brandId,query,limit:10,semantic},options);
