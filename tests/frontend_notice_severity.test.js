'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function setup(){
 const host={hidden:true},source=fs.readFileSync('frontend/app.js','utf8');
 const sandbox={$:()=>host};vm.createContext(sandbox);
 vm.runInContext(source.slice(source.indexOf('let errorSource=null;'),source.indexOf('function toast(')),sandbox);
 return {host,eval:code=>vm.runInContext(code,sandbox)};
}

test('budget, missing material, busy work and recoverable network errors stay calm and visible',()=>{
 const s=setup();
 for(const [code,message,status] of [
  ['BUDGET_EXCEEDED','本次 Token 用量达到上限，已有稿件已保留。',409],
  ['USAGE_UNKNOWN','用量待核对，暂时不能重复调用。',409],
  ['INVALID_INPUT','请先填写读者问题。',400],
  ['RATE_LIMITED','请稍后再试。',429],
  ['INSUFFICIENT_EVIDENCE','资料不足，请补充来源。',409],
  ['VERSION_CONFLICT','记录已更新，请刷新。',409],
  ['PROVIDER_UNAVAILABLE','模型暂时不可用。',503],
  [undefined,'Failed to fetch',undefined],
  [undefined,'模型返回格式不正确，未自动重试',undefined],
 ]){
  s.eval(`error({code:${JSON.stringify(code)||'undefined'},message:${JSON.stringify(message)},status:${status}})`);
  assert.equal(s.host.className,'error',code);assert.equal(s.host.role,'status');
  assert.equal(s.host.textContent,message);assert.equal(s.host.hidden,false);
 }
});

test('true internal/security failures remain red alerts and reset for the next ordinary notice',()=>{
 const s=setup();
 for(const code of ['INTERNAL_ERROR','FORBIDDEN','CSRF_INVALID','DATA_INTEGRITY_ERROR']){
  s.eval(`error({code:'${code}',message:'请求被阻止'})`);
  assert.equal(s.host.className,'error critical');assert.equal(s.host.role,'alert');
 }
 s.eval("error({status:500,message:'保存失败，原记录保留'})");assert.equal(s.host.className,'error critical');
 s.eval("error(new Error('请选择两份不同的稿件'))");
 assert.equal(s.host.className,'error');assert.equal(s.host.role,'status');
 s.eval('clearError()');assert.equal(s.host.hidden,true);
});

test('critical styling is opt-in and reader-check retry/version notices use calm colors',()=>{
 const css=fs.readFileSync('frontend/style.css','utf8'),wt=fs.readFileSync('frontend/windtunnel.css','utf8');
 assert.match(css,/\.error\{background:#eef4ef;color:#486356/);
 assert.match(css,/\.error\.critical\{background:#fae9e5/);
 assert.match(wt,/\.wt-report-banner\.failed\{background:#eef4ef/);
 assert.match(wt,/\.wt-workspace \.wt-inline-error\{color:#486356;background:#eef4ef/);
 assert.match(wt,/\.wt-workspace \.wt-error\{[^}]*background:#eef4ef;color:#486356/);
 const source=fs.readFileSync('frontend/app.js','utf8');
 assert.match(source,/failure.status=r.status/);
});
