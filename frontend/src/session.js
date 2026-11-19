const settings=await fetch('/api/auth/mode').then(r=>r.json());
if(settings.login_required)window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
const form=document.getElementById('login');
if(form){
 if(!settings.login_required)location.replace('/agent.html');
 form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;
  try{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value})});
   const body=await r.json();if(!r.ok)throw Error(typeof body.detail==='string'?body.detail:'登录失败，请检查账号和密码。');
   // Local task IDs are only navigation hints. Drop another account's hint.
   localStorage.removeItem('marketing-agent-task');sessionStorage.removeItem('marketing_access_key');
   location.replace('/agent.html');
  }catch(error){document.getElementById('loginError').textContent=error.message;}finally{button.disabled=false;}
 };
}else if(settings.login_required){
 const button=document.createElement('button');button.textContent='退出登录';button.className='session-logout';
 button.onclick=async()=>{const r=await fetch('/api/auth/logout',{method:'POST'});if(r.ok||r.status===401)location.replace('/login.html');};
 (document.querySelector('.sidebar-footer')||document.querySelector('aside')||document.body).append(button);
}
