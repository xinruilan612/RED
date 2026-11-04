'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync('frontend/app.js','utf8');
function setup(fetch){
 const sandbox={fetch,csrf:'test-token'};vm.createContext(sandbox);
 vm.runInContext(app.slice(app.indexOf('async function api('),app.indexOf('let errorSource=')),sandbox);return sandbox.api;
}
for(const failure of ['network','unreadable response']){
 test(`${failure}: GET offers retry while POST requires checking the uncertain result first`,async()=>{
  let calls=0;const api=setup(async()=>{calls++;if(failure==='network')throw Error('Failed to fetch');return {ok:true,status:200,json:async()=>{throw SyntaxError('Unexpected token <');}};});
  const prefix=failure==='network'?/无法连接服务/:/未返回可识别的结果/;
  await assert.rejects(()=>api('/api/knowledge'),e=>prefix.test(e.message)&&/检查网络和本地服务.*重试/.test(e.message));
  await assert.rejects(()=>api('/api/knowledge','POST',{text:'资料'}),e=>prefix.test(e.message)&&/提交结果尚未确认.*先查看列表或任务状态.*避免重复提交/.test(e.message));
  assert.equal(calls,2,'uncertain requests must never retry automatically');
 });
}
for(const [code,status,expected] of [
 ['AUTH_REQUIRED',401,/登录已失效.*重新登录/],
 ['RATE_LIMITED',429,/操作过于频繁.*稍等.*重试/],
 ['INTERNAL_ERROR',500,/服务处理失败.*查看.*是否已保存.*未完成.*稍后重试/],
]){
 test(`${code} gives a recovery action while preserving machine-readable status and code`,async()=>{
  const api=setup(async()=>({ok:false,status,json:async()=>({error:{code,message:'internal detail'}})}));
  await assert.rejects(()=>api('/api/runs','POST',{}),e=>e.status===status&&e.code===code&&expected.test(e.message)&&!e.message.includes('internal detail'));
 });
}
test('specific business corrections remain verbatim with their error identity',async()=>{
 const message='领域“护肤”不在可选范围，请选择“美妆”后重新提交。';
 const api=setup(async()=>({ok:false,status:400,json:async()=>({error:{code:'INVALID_INPUT',message}})}));
 await assert.rejects(()=>api('/api/knowledge','POST',{}),e=>e.status===400&&e.code==='INVALID_INPUT'&&e.message===message);
});
test('an unstructured error response still provides recovery without assuming a failed POST was not saved',async()=>{
 const api=setup(async()=>({ok:false,status:502,json:async()=>({})}));
 await assert.rejects(()=>api('/api/knowledge','POST',{}),e=>e.status===502&&/请求未完成.*提交结果尚未确认.*先查看.*避免重复提交/.test(e.message));
});
test('successful requests retain payload, JSON body and CSRF protection',async()=>{
 const payload={id:'saved'},calls=[],api=setup(async(...args)=>{calls.push(args);return {ok:true,json:async()=>payload};});
 assert.equal(await api('/api/knowledge','POST',{text:'资料'}),payload);assert.equal(calls.length,1);assert.equal(calls[0][1].headers['X-CSRF-Token'],'test-token');assert.equal(calls[0][1].headers['Content-Type'],'application/json');assert.deepEqual(JSON.parse(calls[0][1].body),{text:'资料'});
});
