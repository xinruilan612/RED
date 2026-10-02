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
 actualRenderDetails=renderDetails; actualRenderHuman=renderHuman; renderDetails=renderHuman=renderDraft=renderTimeline=renderCalls=()=>{};
 history=async()=>[]; currentAgent=()=> 'research'; calls=[]; confirmations=0;
 actualConfirmLiveBudget=confirmLiveBudget;confirmLiveBudget=()=>{confirmations++;return true;};
 api=async(path,method,body)=>{calls.push(body);return run;};`,sandbox);
 return {sandbox,element,eval:code=>vm.runInContext(code,sandbox)};
}

test('cancel asks in a nonblocking panel and only dispatches after explicit confirmation',async()=>{
 const s=setup();s.element('cancelConfirmation').hidden=true;
 await s.element('cancel').onclick();assert.equal(s.element('cancelConfirmation').hidden,false);
 assert.equal(s.eval('calls.length'),0);
 s.element('keepTask').onclick();assert.equal(s.element('cancelConfirmation').hidden,true);
 await s.element('cancel').onclick();await s.element('confirmCancel').onclick();
 assert.equal(s.eval('calls[0].action'),'cancel');assert.equal(s.eval('confirmations'),0);
});

test('live budget panel blocks calls until approval and dispatches only once',async()=>{
 const s=setup();s.eval("confirmLiveBudget=actualConfirmLiveBudget;provider={run_attempts_max:16,run_tokens_max:80000,run_budget_usd:0.1,day_budget_usd:0.5};window.confirm=()=>{throw new Error('native dialog forbidden')};");
 await s.eval("backgroundCommand('start')");assert.equal(s.eval('calls.length'),0);assert.equal(s.element('liveBudgetConfirmation').hidden,false);
 assert.match(s.element('liveBudgetMessage').textContent,/80,000/);
 s.element('declineLiveBudget').onclick();assert.equal(s.eval('calls.length'),0);
 await s.element('approveLiveBudget').onclick();assert.equal(s.eval('calls.length'),0);
 await s.eval("backgroundCommand('start')");await s.element('approveLiveBudget').onclick();await s.element('approveLiveBudget').onclick();
 assert.equal(s.eval('calls.length'),1);assert.equal(s.eval('calls[0].action'),'start');
});

test('live budget approval rejects changed task or material snapshot',async()=>{
 for(const change of ["run.run_id='other'","run.snapshot_id='new-material'"]){
  const s=setup();s.eval('confirmLiveBudget=actualConfirmLiveBudget;provider={}');await s.eval("backgroundCommand('start')");s.eval(change);
  await s.element('approveLiveBudget').onclick();assert.equal(s.eval('calls.length'),0);assert.equal(s.eval('confirmedLiveRuns.size'),0);assert.match(s.element('error').textContent,/已变化/);
 }
});

test('cancel confirmation cannot cancel a different task after navigation',async()=>{
 const s=setup();await s.element('cancel').onclick();s.eval("run.run_id='other-task'");await s.element('confirmCancel').onclick();
 assert.equal(s.eval('calls.length'),0);assert.match(s.element('error').textContent,/任务已变化/);
});

test('pause refreshes moving Worker version and never restarts a completed task',async()=>{
 const s=setup();s.eval("run.in_flight=true;run.status_version=7;pausePosts=0;api=async(_p,method,body)=>{if(method==='POST'){pausePosts++;if(pausePosts===1){run.status_version=8;const e=new Error('任务已更新');e.code='VERSION_CONFLICT';throw e;}calls.push(body);}return run;}");
 await s.eval("backgroundCommand('pause')");assert.equal(s.eval('calls[0].action'),'pause');assert.equal(s.eval('calls[0].version'),8);assert.equal(s.eval('pausePosts'),2);
 s.eval('run.in_flight=false');await s.eval("backgroundCommand('pause')");assert.equal(s.eval('pausePosts'),2);
});

test('late material response retains its original account identity',async()=>{
 const s=setup();s.eval("active='a1';currentAccount=()=>({id:active});api=()=>new Promise(resolve=>{resolveMaterials=resolve});renders=0;renderMaterialUploads=()=>renders++;");
 const request=s.eval('refreshMaterialDocuments()');s.eval("active='a2';resolveMaterials([{id:'doc1',title:'A1资料',version:1,metadata:{}}])");await request;
 assert.equal(s.eval('materialDocsCache[0].account_id'),'a1');assert.equal(s.eval('renders'),0);
});

test('simulation draft enters a separately approved simulated publication instead of real archive',async()=>{
 const s=setup();vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);
 s.eval("run.mode='simulation';run.accepted_ref='d1';ops={publications:[]};archiveCalls=[];showPage=p=>page=p;operate=async(action,payload)=>{archiveCalls.push({action,payload});return true;};openPublishedArchive=()=>{throw new Error('must not open real archive')}");
 await s.element('sendToPublish').onclick();assert.equal(s.eval('archiveCalls[0].action'),'prepare');assert.equal(s.eval('page'),'publish');
 s.eval("ops.publications=[{run_id:'run-1',draft_ref:'d1'}]");await s.element('sendToPublish').onclick();assert.equal(s.eval('archiveCalls.length'),1);
});

test('simulation publication list exposes exact approval and simulation actions',()=>{
 const s=setup();vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);
 s.eval("accountRows=()=>[{id:'p1',mode:'simulation',status:'AWAITING_APPROVAL',account:'模拟账号',content:{selected_title:'模拟稿'}}];renderSimulatedPublications()");
 assert.match(s.element('operationsContent').innerHTML,/data-approve="p1"/);assert.match(s.element('operationsContent').innerHTML,/不进入真实历史/);
});

test('free weekly plan uses existing rules command and AI mode rejects missing configuration',async()=>{
 const s=setup();s.sandbox.localStorage={getItem:()=>''};vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);vm.runInContext(fs.readFileSync('frontend/account.js','utf8'),s.sandbox);
 s.eval("activeAccountId='a1';planCalls=[];operate=async(action,payload)=>{planCalls.push({action,payload});return true;}");
 s.element('planMode').value='rules';s.element('planSource').value='simulation';s.element('planWeek').value='2026-10-05';await s.eval('submitWeeklyPlan({preventDefault(){}})');
 assert.equal(s.eval('planCalls[0].action'),'create_plan');assert.equal(s.eval('planCalls[0].payload.source_type'),'simulation');assert.equal(s.eval('calls.length'),0);
 s.element('planMode').value='agent';await s.eval('submitWeeklyPlan({preventDefault(){}})');assert.equal(s.eval('planCalls.length'),1);assert.match(s.element('error').textContent,/API Key/);
});
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

test('manual-adoption availability does not hide free rejected-review recovery',()=>{
 const s=setup();s.eval("run.current_stage='reviewer';run.drafts=[{}];run.allowed_actions=['next','cancel','edit','adopt_manual','repair_review'];run.calls=[];renderRecovery()");
 assert.equal(s.element('reviewRecovery').hidden,false);
 assert.equal(s.element('repairReview').hidden,false);
 assert.equal(s.element('next').hidden,true);
 assert.equal(s.element('auto').hidden,true);
 s.eval("run.allowed_actions=['edit','adopt_manual'];renderRecovery()");
 assert.equal(s.element('repairReview').hidden,true);
});

test('question-only review recovery is labelled human handling instead of rewriting',()=>{
 const s=setup();s.eval("run.current_stage='reviewer';run.drafts=[{}];run.allowed_actions=['repair_review'];run.review_recovery={next_action:'request_human'};run.calls=[];renderRecovery()");
 assert.match(s.element('repairReview').textContent,/进入人工处理/);
 assert.doesNotMatch(s.element('repairReview').textContent,/进入改稿/);
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

test('published archive shows actual records and hides prepublication approval queue',()=>{
 const s=setup();vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);
 s.eval("currentAccount=()=>({name:'我的账号',platform:'xiaohongshu'});accountRows=()=>[{id:'p1',platform:'xiaohongshu',mode:'live',status:'MANUAL_REPORTED',content:{selected_title:'实际标题',body:'实际正文',tags:['日常']},draft_ref:'draft-1',content_hash:'hash',url:'https://www.xiaohongshu.com/explore/a',published_at:'2026-09-30T08:00:00Z',run_id:'r1',source_acceptance:{mode:'manual_override'}},{status:'AWAITING_APPROVAL',content:{selected_title:'旧队列稿'}}];renderPublications()");
 assert.match(s.element('operationsContent').innerHTML,/已发布 · 人工记录/);
 assert.match(s.element('operationsContent').innerHTML,/来源稿由用户人工采用/);
 assert.match(s.element('operationsContent').innerHTML,/实际正文/);
 assert.doesNotMatch(s.element('operationsContent').innerHTML,/确认此版本与账号|旧队列稿/);
});
test('published record prefills adopted draft then archives actual edited text in one action',async()=>{
 const s=setup();vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);
 s.eval("ops={publications:[]};currentAccount=()=>({id:'a1',platform:'xiaohongshu'});matchesAccount=()=>true;api=async()=>[{run_id:'r1',mode:'live',run_status:'SUCCEEDED',context:{topic:'选题'},accepted_ref:'d1',drafts:[{ref:'d1',content:{selected_title:'原标题',body:'原正文',cta:'互动问题',tags:['话题']}}]}];archiveCalls=[];operate=async(action,payload)=>{archiveCalls.push({action,payload});return true;}");
 s.eval("run.run_id='r1';showPage=()=>{}");
 await s.element('sendToPublish').onclick();
 assert.equal(s.eval('archiveCalls.length'),0);
 assert.equal(s.element('archiveTitle').value,'原标题');
 assert.equal(s.element('archiveBody').value,'原正文\n\n互动问题');
 assert.equal(s.element('archivePublishedAt').value,'');
 s.element('archiveTitle').value='平台实际标题';s.element('archiveBody').value='平台实际正文';
 s.element('archiveUrl').value='https://www.xiaohongshu.com/explore/a';s.element('archivePublishedAt').value='2026-09-30T16:00';
 await s.eval('savePublishedArchive({preventDefault(){}})');
 assert.equal(s.eval('archiveCalls.length'),1);assert.equal(s.eval('archiveCalls[0].action'),'archive_published');
 assert.equal(s.eval('archiveCalls[0].payload.title'),'平台实际标题');
 assert.equal(s.eval('archiveCalls[0].payload.draft_ref'),'d1');
 assert.equal(s.eval('confirmations'),0);
});
test('external published work can be archived without an AI draft',async()=>{
 const s=setup();vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);
 s.eval("ops={publications:[]};currentAccount=()=>({id:'a1',platform:'xiaohongshu'});matchesAccount=()=>true;api=async()=>[];archiveCalls=[];operate=async(action,payload)=>{archiveCalls.push({action,payload});return true;}");
 await s.eval('openPublishedArchive()');
 s.element('archiveTitle').value='我自己写的作品';s.element('archiveBody').value='实际内容';s.element('archiveTags').value='日常';s.element('archiveUrl').value='https://www.xiaohongshu.com/explore/b';s.element('archivePublishedAt').value='2026-09-30T16:00';
 await s.eval('savePublishedArchive({preventDefault(){}})');
 assert.equal(s.eval('archiveCalls[0].action'),'import_post');assert.equal(s.eval('archiveCalls[0].payload.account_id'),'a1');
});
test('manual adoption is disabled during execution or unsaved editing',()=>{
 const s=setup();s.eval("run.in_flight=true;render()");
 assert.equal(s.element('adoptManual').disabled,true);
 s.eval("run.in_flight=false;editing=true;render()");
 assert.equal(s.element('adoptManual').disabled,true);
});


test('supplemented input does not label previous snapshot output as current',()=>{
 const s=setup();s.eval("run.node_runs=[{agent:'audience',stage:'audience',snapshot_id:'old-input',output:{primary_audience:'旧读者',basis:'旧分析',content_opportunities:[]}}];actualRenderDetails()");
 const html=s.element('details').innerHTML;
 assert.match(html,/本次输入尚无通过校验的产物/);
 assert.doesNotMatch(html,/<h3>当前产物<\/h3>/);
 assert.match(html,/<details><summary>之前输入的历史记录（1，不代表本轮产物）<\/summary>/);
 assert.match(html,/旧分析/);
});
test('current snapshot output takes precedence over later previous snapshot records',()=>{
 const s=setup();s.eval("run.node_runs=[{agent:'audience',stage:'audience',snapshot_id:'snapshot',duration_ms:1,output:{primary_audience:'新读者',basis:'新分析',content_opportunities:[]}},{agent:'audience',stage:'audience',snapshot_id:'old-input',output:{primary_audience:'旧读者',basis:'旧分析',content_opportunities:[]}}];actualRenderDetails()");
 const html=s.element('details').innerHTML;
 const current=html.split('之前输入的历史记录')[0];
 assert.match(current,/<h3>当前产物<\/h3>/);
 assert.match(current,/新分析/);
 assert.doesNotMatch(current,/旧分析/);
 assert.match(html,/旧分析/);
});


test('successful background continuation clears stale failure while active failures remain visible',async()=>{
 const s=setup();s.eval("run.background={status:'blocked',error:'上次输出未通过校验'};render();api=async()=>({...run,background:{status:'running'},in_flight:true})");
 assert.equal(s.element('error').hidden,false);
 await s.eval("backgroundCommand('start')");
 assert.equal(s.element('error').hidden,true);
 s.eval("run.background={status:'blocked',error:'新的失败'};run.in_flight=false;render()");
 assert.equal(s.element('error').hidden,false);
 assert.equal(s.element('error').textContent,'新的失败');
});
test('fresh background render removes resolved run error without hiding unrelated request errors',()=>{
 const s=setup();s.eval("run.background={status:'blocked',error:'旧失败'};render();run.background={status:'waiting'};render()");
 assert.equal(s.element('error').hidden,true);
 s.eval("error(new Error('上传失败'));render()");
 assert.equal(s.element('error').hidden,false);
 assert.equal(s.element('error').textContent,'上传失败');
 s.eval("run.run_status='FAILED';run.events=[{type:'agent.failed',payload:{message:'当前执行失败'}}];render()");
 assert.equal(s.element('error').hidden,false);
 assert.equal(s.element('error').textContent,'当前执行失败');
});

test('archive accepts full share text and sends only the extracted link',async()=>{
 const s=setup();vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);
 s.eval("currentAccount=()=>({id:'a1',platform:'xiaohongshu'});accountRows=()=>[];renderPublications();archiveCalls=[];operate=async(action,payload)=>{archiveCalls.push({action,payload});return true;}");
 assert.match(s.element('operationsContent').innerHTML,/id="archiveUrl" type="text"/);
 s.element('archiveTitle').value='洗脸后先涂什么';s.element('archiveBody').value='实际正文';s.element('archivePublishedAt').value='2026-09-30T18:02';
 s.element('archiveUrl').value='洗脸后先涂什么？新手早间：先保湿再防晒 [https://xhslink.cn/o/8ZZwcVOCe77](https://xhslink.cn/o/8ZZwcVOCe77) Copy and open rednote to view the note';
 await s.eval('savePublishedArchive({preventDefault(){}})');
 assert.equal(s.eval('archiveCalls.length'),0);
 assert.match(s.element('error').textContent,/多个链接/);
 s.element('archiveUrl').value='洗脸后先涂什么？新手早间：先保湿再防晒 https://xhslink.cn/o/8ZZwcVOCe77 Copy and open rednote to view the note';
 await s.eval('savePublishedArchive({preventDefault(){}})');
 assert.equal(s.eval('archiveCalls.length'),1);
 assert.equal(s.eval('archiveCalls[0].payload.url'),'https://xhslink.cn/o/8ZZwcVOCe77');
 assert.equal(s.element('archiveUrl').value,'https://xhslink.cn/o/8ZZwcVOCe77');
});

test('share extraction preserves encoded query and trims prose boundaries',()=>{
 const s=setup();vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),s.sandbox);
 const url='https://www.xiaohongshu.com/explore/a?xsec_token=Ab%2BC%3D&xsec_source=pc_share';
 for(const pasted of [url,`链接：${url}。复制打开`, `[笔记](${url})`, `  ${url}\n复制打开`]){
  s.sandbox.pasted=pasted;assert.equal(s.eval('extractPublishedUrl(pasted)'),url);
 }
 for(const pasted of ['没有链接','javascript:alert(1)','https://xhslink.cn/o/one https://xhslink.cn/o/two']){
  s.sandbox.pasted=pasted;assert.throws(()=>s.eval('extractPublishedUrl(pasted)'),/作品链接|多个链接/);
 }
});
