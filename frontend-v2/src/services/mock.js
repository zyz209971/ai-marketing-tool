function makeContent(ps,platform,draft){let subject=ps.map(p=>p.name).join('、')||draft.theme||draft.brand.name;let facts=ps.map(p=>`${p.name}\n${p.selling}${p.price?'\n价格：'+p.price:''}`).join('\n\n');let body=`${draft.brand.intro}\n\n${facts}\n\n${draft.theme?'本次主题：'+draft.theme+'\n':''}${draft.rules?'优惠规则：'+draft.rules+'\n':''}${draft.dates?'活动时间：'+draft.dates+'\n':''}${draft.points?'补充亮点：'+draft.points+'\n':''}`;return {id:uid(),platform,subject,title:platform==='小红书'?`${subject}｜日常里的新灵感`:`${subject}：${draft.goal}特别分享`,summary:`${draft.brand.name}的${draft.goal}分享。`,body:body+(platform==='小红书'?'你会想和谁一起分享？欢迎留言。':'欢迎留言，告诉我们你关注的商品信息。'),tags:'#品牌分享 #日常灵感',versions:[],saved:false}}

export async function generateMock(draft){
 const groups=draft.merge==='separate'&&draft.ps.length?draft.ps.map(p=>[p]):[draft.ps];
 return groups.flatMap(group=>draft.plats.map(p=>({...makeContent(group,p,draft),imageUrl:null})));
}
function uid(){return 'mock_'+Date.now().toString(36)+Math.random().toString(36).slice(2,6)}
