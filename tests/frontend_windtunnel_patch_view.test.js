'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const sandbox={pageInfo:{},console,setInterval(){},setTimeout(){},clearInterval(){},clearTimeout(){},location:{hash:''},fetch:async()=>({ok:true,json:async()=>({})}),
  esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  document:{querySelectorAll:()=>[],addEventListener(){}},
  localStorage:{getItem(){return null;},setItem(){}}};
 vm.createContext(sandbox);
 vm.runInContext(fs.readFileSync('frontend/windtunnel.js','utf8'),sandbox);
 const load=state=>vm.runInContext(`wt.run=${JSON.stringify(state)};wt.batch='';`,sandbox);
 const evalIn=code=>vm.runInContext(code,sandbox);
 return {sandbox,load,evalIn};
}
function run(overrides={}){
 const draft={id:'d1',title:'教程',text:'第一段\n\n第二段',hash:'h1'};
 return {
  run_id:'r',mode:'live',in_flight:false,allowed_actions:['propose_patch','recheck','apply_patch'],wait_reason:'wt_report',
  windtunnel:{
   drafts:[draft],current_set_id:'s1',batch_id:'b1',material_hash:'m1',
   condition_sets:[{id:'s1',confirmed:true,hash:'c1',conditions:[{id:'q1',question:'怎么开始？'},{id:'q2',question:'失败怎么办？'},{id:'q3',question:'结果怎么确认？'}]}],
   reports:[{id:'p1',batch_id:'b1',draft_id:'d1',draft_hash:'h1',condition_set_id:'s1',condition_hash:'c1',material_hash:'m1',results:[
    {condition_id:'q1',status:'unclear'},{condition_id:'q2',status:'insufficient'},{condition_id:'q3',status:'pass'}]}],
   patches:[]
  },...overrides};
}
test('patch form lists only the problems that did not pass',()=>{
 const s=setup();s.load(run());
 const html=s.evalIn('wtPatchForm()');
 assert.equal((html.match(/name="condition_id"/g)||[]).length,2);
 assert.doesNotMatch(html,/结果怎么确认？/);
 assert.match(html,/按勾选的问题生成修改提案/);
});
test('patch form refuses to work from an outdated report',()=>{
 const s=setup();const state=run();state.windtunnel.batch_id='b2';
 s.load(state);
 const html=s.evalIn('wtPatchForm()');
 assert.match(html,/先按原条件复查当前版本/);
 assert.doesNotMatch(html,/name="condition_id"/);
});
test('simulation never offers a patch it cannot ground',()=>{
 const s=setup();const state=run();state.mode='simulation';
 s.load(state);
 const html=s.evalIn('wtPatchForm()');
 assert.match(html,/模拟模式不生成修改提案/);
 assert.match(html,/disabled/);
 assert.match(html,/name="condition_id" value="q1" disabled>/);
});
test('empty patch stays a record and says why nothing was proposed',()=>{
 const s=setup();const state=run();state.windtunnel.patches=[{id:'pt1',base_hash:'h1',draft_id:'d1',items:[],created_at:1}];
 s.load(state);
 const html=s.evalIn('wtPatch(wt.run.windtunnel.patches[0])');
 assert.match(html,/没有生成可采用的修改/);
 assert.doesNotMatch(html,/采用勾选项/);
});
