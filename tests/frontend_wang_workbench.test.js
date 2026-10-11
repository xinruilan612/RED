'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const elements=new Map();
 function element(id){if(!elements.has(id))elements.set(id,{hidden:true,disabled:false,checked:false,value:'',innerHTML:'',textContent:'',selectedOptions:[],addEventListener(){},scrollIntoView(){},insertAdjacentHTML(_where,value){this.innerHTML+=value;}});return elements.get(id);}
 const sandbox={document:{getElementById:element,querySelector:element,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(){},confirm(){throw Error('Native confirm must not start fees/cancel');}},setInterval(){},setTimeout(){},clearTimeout(){},crypto:{randomUUID:()=> 'unique-key'},websiteSession:{auth_required:true},URL};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/app.js','utf8'),sandbox);
 const evaluate=code=>vm.runInContext(code,sandbox);
 evaluate(`provider={run_attempts_max:16,run_tokens_max:80000,run_budget_usd:.1,day_budget_usd:.2};
 run={run_id:'r1',snapshot_id:'s1',status_version:5,mode:'live',model_policy:{routes:{body:{model:'frozen-model',run_budget_usd:.3,day_budget_usd:.5}}},context:{topic:'主题',audience:'读者',tone:'清楚',creation_classification:{domains:['digital'],format:'note'}},run_status:'RUNNING',current_stage:'content',drafts:[],artifacts:[],node_runs:[],events:[],allowed_actions:['next','cancel'],usage:{},in_flight:false};
 actualRenderDraft=renderDraft;actualRender=render;render=()=>{};history=async()=>[];calls=[];
 api=async(path,method,body)=>{calls.push({path,method,body});return run;};`);
 return {eval:evaluate,element,sandbox};
}
const draft=(ref,body)=>({ref,snapshot_id:'s1',actor:'content',content:{selected_title:ref,body,cta:'提问',tags:[]}});
test('live fee confirmation is in-page, frozen-route aware and starts only after one approval',async()=>{
 const s=setup();await s.eval("backgroundCommand('start')");
 assert.equal(s.eval('calls.length'),0);assert.equal(s.element('liveBudgetConfirmation').hidden,false);
 assert.match(s.element('liveBudgetMessage').textContent,/\$0\.30/);assert.match(s.element('liveBudgetMessage').textContent,/\$0\.50/);
 assert.match(s.element('liveBudgetMessage').textContent,/通用方法、匹配样例与独立事实/);
 await s.element('approveLiveBudget').onclick();await s.element('approveLiveBudget').onclick();
 assert.equal(s.eval('calls.length'),1);assert.equal(s.eval('calls[0].body.action'),'start');
 assert.equal(s.eval('calls[0].body.version'),5);
});
test('fee decline and changed snapshot or frozen policy cannot resume a stale command',async()=>{
 const s=setup();await s.eval("backgroundCommand('step')");s.element('declineLiveBudget').onclick();await s.element('approveLiveBudget').onclick();assert.equal(s.eval('calls.length'),0);
 await s.eval("backgroundCommand('step');run.snapshot_id='s2'");await s.element('approveLiveBudget').onclick();assert.equal(s.eval('calls.length'),0);assert.match(s.element('error').textContent,/变化/);
 await s.eval("backgroundCommand('step');run.model_policy.routes.body.run_budget_usd=.8");await s.element('approveLiveBudget').onclick();assert.equal(s.eval('calls.length'),0);
});
test('unknown-usage server refusal is shown and never retried automatically',async()=>{
 const s=setup();s.eval("api=async(path,method,body)=>{if(method==='POST'){calls.push({path,body});throw Error('上次用量未知；已停止，未重复收费调用');}return run;}");
 await s.eval("backgroundCommand('start')");await s.element('approveLiveBudget').onclick();
 assert.equal(s.eval('calls.length'),1);assert.match(s.element('error').textContent,/用量未知/);
});
test('cancel uses explicit in-page decision and never cancels a newly selected task',async()=>{
 const s=setup();await s.element('cancel').onclick();assert.equal(s.eval('calls.length'),0);assert.equal(s.element('cancelConfirmation').hidden,false);
 s.element('keepTask').onclick();await s.element('confirmCancel').onclick();assert.equal(s.eval('calls.length'),0);
 await s.element('cancel').onclick();s.eval("run.run_id='r2'");await s.element('confirmCancel').onclick();assert.equal(s.eval('calls.length'),0);
 await s.element('cancel').onclick();await s.element('confirmCancel').onclick();assert.equal(s.eval('calls.length'),1);assert.equal(s.eval('calls[0].body.action'),'cancel');
});
test('draft-first rendering follows worker latest, comparison is opt-in and frozen evidence remains',()=>{
 const s=setup();s.sandbox.fixtureDrafts=[draft('v1','旧正文'),draft('v2','新正文')];
 s.eval("run.drafts=fixtureDrafts;run.allowed_actions=[];draftEvidenceHTML=d=>'<details>frozen-evidence-'+d.ref+'</details>';actualRenderDraft()");
 assert.match(s.element('draftView').innerHTML,/新正文/);assert.doesNotMatch(s.element('draftView').innerHTML,/旧正文/);assert.match(s.element('draftView').innerHTML,/frozen-evidence-v2/);
 assert.equal(s.eval('viewVersion'),null);assert.equal(s.element('compareVersionsWrap').hidden,false);
 s.element('compareVersions').checked=true;s.element('compareVersions').onchange();assert.match(s.element('draftView').innerHTML,/旧正文/);assert.match(s.element('draftView').innerHTML,/新正文/);
 s.sandbox.nextDraft=draft('v3','后台最新');s.eval('run.drafts.push(nextDraft);actualRenderDraft()');assert.match(s.element('draftView').innerHTML,/后台最新/);
 s.element('versionSelect').onchange({target:{value:'0'}});assert.equal(s.eval('viewVersion'),0);assert.equal(s.element('compareVersionsWrap').hidden,true);
 s.element('versionSelect').onchange({target:{value:'2'}});assert.equal(s.eval('viewVersion'),null);
});
test('guidance reflects review and manual decisions without removed reader-trial UI',()=>{
 const s=setup();assert.match(s.eval('nextStepGuidance(run)'),/连续运行/);
 s.eval("run.in_flight=true");assert.match(s.eval('nextStepGuidance(run)'),/无需重复点击/);
 s.eval("run.in_flight=false;run.review={decision:'revision_required'}");assert.match(s.eval('nextStepGuidance(run)'),/重新审核/);
 assert.doesNotMatch(s.eval('nextStepGuidance(run)'),/读者理解|试飞|风洞/);
});
test('material responses retain requesting account across asynchronous account switches',async()=>{
 const s=setup();
 s.eval(`activeAccount='account-a';currentAccount=()=>({id:activeAccount});requests={};renderedAccounts=[];
 renderMaterialUploads=()=>renderedAccounts.push(currentAccount().id);
 api=path=>new Promise((resolve,reject)=>{requests[path]={resolve,reject};});
 requestA=refreshMaterialDocuments();duplicateA=refreshMaterialDocuments();activeAccount='account-b';requestB=refreshMaterialDocuments();`);
 assert.equal(s.eval('Object.keys(requests).length'),2);
 s.eval("requests['/api/knowledge?account_id=account-b'].resolve([{id:'doc-b',title:'乙资料',version:1,metadata:{}}])");await s.eval('requestB');
 s.eval("requests['/api/knowledge?account_id=account-a'].resolve([{id:'doc-a',title:'甲资料',version:1,metadata:{}}])");await s.eval('Promise.all([requestA,duplicateA])');
 assert.equal(s.eval("materialDocsCache.find(d=>d.id==='doc-a').account_id"),'account-a');
 assert.equal(s.eval("materialDocsCache.find(d=>d.id==='doc-b').account_id"),'account-b');
 assert.equal(s.eval("JSON.stringify(renderedAccounts)"),'["account-b"]');
 assert.equal(s.eval('materialRefreshes.size'),0);
});
test('late material error for another account does not replace active-page state',async()=>{
 const s=setup();s.eval(`activeAccount='account-a';currentAccount=()=>({id:activeAccount});api=()=>new Promise((_resolve,reject)=>{rejectMaterial=reject;});pendingMaterials=refreshMaterialDocuments();activeAccount='account-b';`);
 s.eval("rejectMaterial(new Error('旧账号读取失败'))");await s.eval('pendingMaterials');
 assert.equal(s.element('error').hidden,true);assert.equal(s.eval('materialRefreshes.size'),0);
});

test('background reviewer button matches the saved-version guidance',()=>{
 const s=setup();s.sandbox.fixtureDrafts=[draft('v1','已保存正文')];
 s.eval("run.drafts=fixtureDrafts;run.current_stage='reviewer';run.background={status:'paused'};run.review=null;renderDetails=renderHuman=renderRecovery=renderDraft=renderTimeline=renderCalls=()=>{};actualRender()");
 assert.equal(s.element('next').textContent,'复审当前版本 →');
 assert.match(s.element('workbenchGuide').textContent,/复审当前版本/);
 assert.equal(s.element('next').hidden,false);
 s.eval("run.in_flight=true;run.background.status='running';actualRender()");
 assert.equal(s.element('next').hidden,true);
});
