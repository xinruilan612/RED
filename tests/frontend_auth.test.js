'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const fields=new Map(),get=id=>{if(!fields.has(id))fields.set(id,{value:'',checked:false,hidden:false,disabled:false,textContent:'',removeAttribute(k){delete this[k];},dispatchEvent(){this.onchange?.({target:this});}});return fields.get(id);};
 get('authMode').value='register';get('authUsername').value='test-user';get('authPassword').value='PrivateInput';
 const sandbox={document:{getElementById:get,body:{classList:{add(){}}}},Event,csrf:'',location:{reload(){}},api:async()=>({csrf:'new',recovery_code:'test-recovery'})};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/auth.js','utf8'),sandbox);vm.runInContext("showLogin({csrf:'old',invite_required:false})",sandbox);
 return {sandbox,get,submit:()=>get('authForm').onsubmit({preventDefault(){},submitter:get('authSubmit')})};
}
test('authentication failure preserves inputs and unlocks retry, then successful retry clears stale error',async()=>{
 const s=setup();s.sandbox.api=async()=>{throw Error('用户名已存在，请更换');};await s.submit();
 assert.equal(s.get('authSubmit').disabled,false);assert.equal(s.get('authUsername').value,'test-user');assert.equal(s.get('authPassword').value,'PrivateInput');assert.match(s.get('authError').textContent,/用户名已存在/);
 s.get('authUsername').value='corrected-user';s.sandbox.api=async()=>({csrf:'new',recovery_code:'test-recovery'});await s.submit();
 assert.equal(s.get('authError').textContent,'');assert.equal(s.get('authPassword').value,'');assert.equal(s.get('authForm').hidden,true);assert.equal(s.get('recoverySaved').hidden,false);assert.equal(s.get('newRecovery').textContent,'test-recovery');
});
test('authentication cannot submit twice while the first response is pending',async()=>{
 const s=setup();let resolve,calls=0;s.sandbox.api=()=>{calls++;return new Promise(r=>resolve=r);};
 const pending=s.submit();await s.submit();assert.equal(calls,1);resolve({csrf:'new'});await pending;assert.equal(s.get('authSubmit').disabled,false);
});
test('switching authentication mode clears the irrelevant error without deleting user input',async()=>{
 const s=setup();s.get('authError').textContent='用户名已存在';s.get('authMode').value='login';s.get('authMode').dispatchEvent();
 assert.equal(s.get('authError').textContent,'');assert.equal(s.get('authUsername').value,'test-user');assert.equal(s.get('authPassword').value,'PrivateInput');assert.equal(s.get('authSubmit').textContent,'登录工作空间');
});
