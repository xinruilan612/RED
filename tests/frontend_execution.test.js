'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,value:'',textContent:'',innerHTML:'',selectedOptions:[],addEventListener(){},scrollIntoView(){},insertAdjacentHTML(_where,text){this.innerHTML+=text;}});return elements.get(id);};
 const sandbox={document:{getElementById:element,addEventListener(){},querySelector:element,querySelectorAll(){return [];}},window:{addEventListener(){},confirm(){return true;}},setInterval(){},setTimeout(){},clearTimeout(){},crypto:{randomUUID:()=> 'test-key'},websiteSession:{auth_required:true}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/app.js','utf8'),sandbox);
 vm.runInContext(`run={run_id:'run-1',mode:'live',current_stage:'brief',status_version:1,run_status:'RUNNING',context:{topic:'护肤',tone:'清楚',audience:'新手',web_research:{enabled:true,status:'pending',queries:['护肤']}},usage:{},drafts:[],node_runs:[],artifacts:[],events:[],snapshot_id:'snapshot',allowed_actions:['next','cancel'],background:{status:'paused'},in_flight:false};
 actualRenderHuman=renderHuman; renderDetails=renderHuman=renderDraft=renderTimeline=renderCalls=()=>{};
 history=async()=>[]; currentAgent=()=> 'research'; calls=[]; confirmations=0;
 confirmLiveBudget=()=>{confirmations++;return true;};
 api=async(path,method,body)=>{calls.push(body);return run;};`,sandbox);
 return {sandbox,element,eval:code=>vm.runInContext(code,sandbox)};
}
test('next executes one background step and free research does not request model budget',async()=>{
 const s=setup();await s.eval("act('next')");assert.equal(s.eval('calls[0].action'),'step');assert.equal(s.eval('confirmations'),0);
 s.eval("run.context.web_research.status='complete'");await s.eval("act('next')");assert.equal(s.eval('confirmations'),1);
});
test('step button stays visible while paused and hides during execution',()=>{
 const s=setup();s.eval('render()');assert.equal(s.element('next').hidden,false);assert.match(s.element('next').textContent,/联网搜索/);
 s.eval("run.in_flight=true;run.background.status='running';render()");assert.equal(s.element('next').hidden,true);assert.equal(s.element('auto').textContent,'暂停执行');
});
test('blocked research offers same-task retry rather than repeated start',async()=>{
 const s=setup();s.eval("run.context.web_research.status='insufficient';render()");assert.equal(s.element('next').hidden,true);assert.equal(s.element('auto').hidden,true);
 assert.match(s.element('webResearchReport').innerHTML,/重新搜索这一步/);
 s.element('retryQuery1').value='新手 护肤 顺序';s.element('retryQuery2').value='';await s.element('retryWebResearch').onsubmit({preventDefault(){}});
 assert.equal(s.eval('calls[0].action'),'retry_research');assert.equal(s.eval('calls[0].queries[0]'),'新手 护肤 顺序');assert.equal(s.eval('confirmations'),0);
});
test('continuous execution remains an explicit separate command',async()=>{
 const s=setup();await s.eval('autoRun()');assert.equal(s.eval('calls[0].action'),'start');assert.equal(s.eval('confirmations'),1);
});
test('request errors remain visible instead of being replaced by stale job errors',async()=>{
 const s=setup();s.eval("run.context.web_research.status='insufficient';run.background.error='old failure';api=async(_p,method)=>{if(method==='POST')throw new Error('任务已更新，请刷新');return run;}");
 await s.eval("backgroundCommand('retry_research',{queries:['护肤']})");assert.equal(s.element('error').textContent,'任务已更新，请刷新');
});
test('rejected review shows a free recovery action and hides pointless repeat execution',()=>{
 const s=setup();s.eval("run.current_stage='reviewer';run.drafts=[{}];run.allowed_actions=['next','cancel','repair_review'];run.calls=[{stage:'review',status:'invalid',diagnostic_response:{issues:[{excerpt:'标题',reason:'没有依据',suggestion:'修正标题'}]}}];renderRecovery()");
 assert.equal(s.element('reviewRecovery').hidden,false);assert.equal(s.element('repairReview').hidden,false);
 assert.equal(s.element('next').hidden,true);assert.equal(s.element('auto').hidden,true);
 assert.match(s.element('reviewRecoveryIssues').innerHTML,/修正标题/);
});
test('free recovery dispatches repair action rather than approval or model execution',async()=>{
 const s=setup();await s.element('repairReview').onclick();
 assert.equal(s.eval('calls[0].action'),'repair_review');assert.equal(s.eval('confirmations'),0);
});
test('review recovery is hidden once final confirmation is available',()=>{
 const s=setup();s.eval("run.current_stage='reviewer';run.drafts=[{}];run.allowed_actions=['accept','edit'];renderRecovery()");
 assert.equal(s.element('reviewRecovery').hidden,true);assert.equal(s.element('repairReview').hidden,true);
});
test('unavailable confirmation buttons remain disabled after workbench rendering',()=>{
 const s=setup();s.eval('render()');
 assert.equal(s.element('reviewConfirmUnavailable').disabled,true);
 assert.equal(s.element('confirmationPending').disabled,true);
});
test('routine budget explanation stays hidden',()=>{
 const s=setup();s.eval("run.testing_budget={target_cny:0.30,target_runs:3,spent_cny:0.09,warning:''};renderTestingBudget()");
 assert.equal(s.element('testingBudget').hidden,true);
 assert.equal(s.element('testingBudget').textContent,'');
});
test('only actionable budget warning is shown without disabling continuation',()=>{
 const s=setup();s.eval("run.testing_budget={warning:'已超过参考预算，仍可继续'};renderTestingBudget()");
 assert.equal(s.element('testingBudget').hidden,false);
 assert.equal(s.element('testingBudget').textContent,'预算提醒：已超过参考预算，仍可继续');
 assert.equal(s.element('start').disabled,false);
 s.eval('run.testing_budget=null;renderTestingBudget()');
 assert.equal(s.element('testingBudget').hidden,true);
});

test('recovered review hides stale failure panel and explains current recovery',()=>{
 const s=setup();s.eval("run.current_stage='reviewer';run.drafts=[{}];run.allowed_actions=['repair_review'];run.review_recovery={reason:'复审编号不一致，可免费整理并补充资料'};renderRecovery()");
 assert.match(s.element('reviewRecoveryMessage').textContent,/复审编号不一致/);
 s.eval("run.review={decision:'needs_human'};run.allowed_actions=['supplement','cancel'];renderRecovery()");
 assert.equal(s.element('reviewRecovery').hidden,true);
});

test('revision limit allows manual adoption and editing without claiming review approval',()=>{
 const s=setup();s.eval("run.run_status='WAITING_USER';run.wait_reason='revision_limit';run.review={decision:'revision_required',issues:[{excerpt:'原文',reason:'缺少依据',suggestion:'补充来源'}]};run.allowed_actions=['edit','adopt_manual','cancel'];actualRenderHuman()");
 assert.equal(s.element('adoptManual').hidden,false);
 assert.equal(s.element('editButton').hidden,false);
 assert.equal(s.element('accept').hidden,true);
 assert.equal(s.element('confirmationPending').hidden,true);
 assert.match(s.element('humanMessage').textContent,/不表示 AI 审核通过/);
 assert.match(s.element('issues').innerHTML,/缺少依据/);
});
test('manual adoption sends exact draft acknowledgement without a model call',async()=>{
 const s=setup();s.eval("run.drafts=[{ref:'draft-v3',content_hash:'hash-v3'}]");
 await s.element('adoptManual').onclick();
 assert.equal(s.eval('calls[0].action'),'adopt_manual');
 assert.equal(s.eval('calls[0].payload.draft_ref'),'draft-v3');
 assert.equal(s.eval('calls[0].payload.content_hash'),'hash-v3');
 assert.equal(s.eval('calls[0].payload.acknowledge'),true);
 assert.equal(s.eval('confirmations'),0);
});
test('manual adopted result retains earlier issues and labels user choice',()=>{
 const s=setup();s.eval("run.run_status='SUCCEEDED';run.review=null;run.prior_review={issues:[{reason:'旧问题仍未复审'}]};run.acceptance={mode:'manual_override'};run.allowed_actions=['export'];actualRenderHuman()");
 assert.match(s.element('humanTitle').textContent,/人工采用/);
 assert.match(s.element('humanMessage').textContent,/不表示 AI 审核通过/);
 assert.match(s.element('issues').innerHTML,/旧问题仍未复审/);
 assert.equal(s.element('adoptManual').hidden,true);
});

test('publication displays manual provenance when there is no valid AI review',()=>{
 const s=setup();vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);
 s.eval("accountRows=()=>[{id:'p1',platform:'xiaohongshu',mode:'live',status:'AWAITING_APPROVAL',content:{selected_title:'标题',body:'正文',cta:'问题'},draft_ref:'draft-1',content_hash:'hash',review_ref:null,acceptance:{mode:'manual_override'}}];renderPublications()");
 assert.match(s.element('operationsContent').innerHTML,/用户人工采用 · 非 AI 审核通过/);
 assert.match(s.element('operationsContent').innerHTML,/当前版本无有效 AI 审核/);
 assert.match(s.element('operationsContent').innerHTML,/确认此版本与账号/);
});
test('manual adoption is disabled during execution or unsaved editing',()=>{
 const s=setup();s.eval("run.in_flight=true;render()");
 assert.equal(s.element('adoptManual').disabled,true);
 s.eval("run.in_flight=false;editing=true;render()");
 assert.equal(s.element('adoptManual').disabled,true);
});
