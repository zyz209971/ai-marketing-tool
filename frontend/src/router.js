const views=new Set(['chat','brands','products','creations','conversations']);
export function parseRoute(hash=''){
 const [raw,id]=hash.replace(/^#\/?/,'').split('/');
 const view=views.has(raw)?raw:'chat';
 return {view,taskId:view==='chat'&&/^[a-zA-Z0-9_-]{1,100}$/.test(id||'')?id:null};
}
export function routeHref(view,taskId=null){
 return '#/'+(views.has(view)?view:'chat')+(view==='chat'&&taskId?'/'+encodeURIComponent(taskId):'');
}
