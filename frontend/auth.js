'use strict';
let websiteSession=null;
function showLogin(session){
 websiteSession=session;csrf=session.csrf;
 document.body.classList.add('signed-out');
 const panel=document.getElementById('loginPanel');panel.hidden=false;
 document.getElementById('authInviteWrap').hidden=!session.invite_required;
 // Legacy records are opt-in; a new user starts with their own clean workspace.
 document.getElementById('claimLegacy').checked=false;
 document.getElementById('authForm').onsubmit=async e=>{
  e.preventDefault();const button=e.submitter;button.disabled=true;
  const mode=document.getElementById('authMode').value;
  const data={username:document.getElementById('authUsername').value,password:document.getElementById('authPassword').value};
  if(mode==='register'){data.invite=document.getElementById('authInvite').value;data.claim_legacy=document.getElementById('claimLegacy').checked;}
  if(mode==='reset')data.recovery_code=document.getElementById('authRecovery').value;
  try{
   const result=await api('/api/auth/'+mode,'POST',data);csrf=result.csrf;
   document.getElementById('authPassword').value='';document.getElementById('authRecovery').value='';
   if(result.recovery_code){
    document.getElementById('authForm').hidden=true;document.getElementById('recoverySaved').hidden=false;
    document.getElementById('newRecovery').textContent=result.recovery_code;
    document.getElementById('enterWorkspace').onclick=()=>{location.hash='overview';location.reload();};
   }else location.reload();
  }catch(err){document.getElementById('authError').textContent=err.message;}
  finally{button.disabled=false;}
 };
 document.getElementById('authMode').onchange=e=>{
  const mode=e.target.value;
  document.getElementById('claimLegacyWrap').hidden=mode!=='register';
  document.getElementById('authInviteWrap').hidden=mode!=='register'||!session.invite_required;
  document.getElementById('authRecoveryWrap').hidden=mode!=='reset';
  const password=document.getElementById('authPassword'),isLogin=mode==='login';
  password.autocomplete=isLogin?'current-password':'new-password';
  password.maxLength=isLogin?128:20;
  password.placeholder=isLogin?'请输入已有密码':'8–20 位，包含英文大写和小写字母';
  password.title=isLogin?'请输入已有密码':'密码需为 8–20 个字符，并同时包含英文大写和小写字母';
  if(isLogin)password.removeAttribute('pattern');
  else password.pattern='(?=.*[A-Z])(?=.*[a-z]).{8,20}';
  document.getElementById('passwordRule').hidden=isLogin;
  document.getElementById('authSubmit').textContent={login:'登录工作空间',register:'创建网站账号',reset:'重设密码并登录'}[mode];
 };
 document.getElementById('authMode').dispatchEvent(new Event('change'));
}
function showWebsiteUser(session){
 websiteSession=session;
 document.querySelector('[data-page="windtunnel"]').hidden=!session.auth_required;
 if(!session.auth_required)return;
 document.getElementById('websiteUser').hidden=false;
 document.getElementById('libraryNav').hidden=false;document.getElementById('knowledgeOption').hidden=false;
 document.getElementById('websiteUsername').textContent=session.user.username;
 document.getElementById('materialFileBox').hidden=false;
 document.getElementById('logout').onclick=async()=>{if(!dirtyGuard())return;try{await api('/api/auth/logout','POST',{});location.reload();}catch(err){error(err);}};
}
