'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const accountProfile=require('../frontend/account_profile.js');

function setup(formId='',selectedId='existing-a'){
 const elements=new Map();
 const element=id=>{
  if(!elements.has(id))elements.set(id,{value:'',hidden:false,disabled:false,innerHTML:'',outerHTML:'',textContent:'',
   addEventListener(){},scrollIntoView(){},insertAdjacentHTML(){},querySelector(){return element('submit-button');},nextElementSibling:{textContent:''}});
  return elements.get(id);
 };
 const account=id=>({id,name:id,platform:'xiaohongshu',aliases:[id],revision:1,
  profile:{positioning:'知识 / 教育',audience:'学生',pillars:'步骤教程',goal:'验证内容方向',resources:'每周 2–4 小时',weekly_frequency:3}});
 const rows=[account('existing-a'),account('existing-b')];
 const stats=[{},{},{},{}],small=[{},{},{},{}];
 const sandbox={accountProfile,ops:{accounts:rows,plans:[],publications:[],memories:[]},currentPage:'accounts',
  localStorage:{getItem:()=>selectedId,setItem(){}},window:{addEventListener(){}},document:{querySelectorAll:s=>s.includes('weekly-stats b')?stats:s.includes('weekly-stats small')?small:[]},
  $:element,esc:value=>String(value??''),badge:value=>value,stat:()=>'',empty:()=>'',platformNames:{xiaohongshu:'小红书'},states:{},
  busy:false,opsBusy:false,dirtyGuard:()=>true,toast(){},error(){},calls:[],renders:0,
  run:{run_id:'original-run',context:{operations:{account_id:selectedId}},drafts:[{ref:'frozen-draft'}]},
  editing:true,auto:true,chosenTrend:{id:'old-topic'},chosenHypothesis:{id:'old-hypothesis'},historyAccounts:[]};
 const form=element('accountForm');
 const values={id:formId,name:'新账号名称',platform:'xiaohongshu',position_category:'知识 / 教育',position_custom:'',
  audience:'第一次整理课程文件的同学',tone:'具体清楚',goal_choice:'验证内容方向',goal_custom:'',weekly_frequency:'3'};
 form.elements=Object.fromEntries(Object.entries(values).map(([key,value])=>[key,{value,focus(){}}]));
 form.dataset={profileValues:JSON.stringify({pillars:['步骤教程'],resources:['每周 2–4 小时'],banned:[]})};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/account.js','utf8'),sandbox);
 sandbox.syncAccounts=()=>{};sandbox.renderAccounts=()=>{sandbox.renders++;};
 sandbox.history=async()=>{sandbox.historyAccounts.push(vm.runInContext('activeAccountId',sandbox));};
 sandbox.operate=async(action,payload)=>{
  sandbox.calls.push({action,payload});
  if(payload.id)Object.assign(rows.find(a=>a.id===payload.id),{name:payload.name,profile:payload.profile});
  else rows.push({id:'new-created',name:payload.name,platform:payload.platform,aliases:[payload.name],profile:payload.profile});
  return true;
 };
 return {sandbox,element,form,rows,eval:code=>vm.runInContext(code,sandbox),submit:()=>form.onsubmit({preventDefault(){},target:form})};
}

test('new account form on the same platform creates instead of overwriting selected profile',async()=>{
 const s=setup();const before=structuredClone(s.rows[0]),originalRun=s.sandbox.run;s.eval('bindAccountForm()');
 await s.submit();
 assert.equal(s.sandbox.calls[0].action,'save_account');assert.equal(s.sandbox.calls[0].payload.id,'');
 assert.deepEqual(s.rows[0],before);assert.equal(s.rows.length,3);
 assert.equal(s.eval('activeAccountId'),'new-created');
 assert.equal(s.sandbox.run,null);assert.equal(s.sandbox.editing,false);assert.equal(s.sandbox.auto,false);
 assert.equal(s.sandbox.chosenTrend,null);assert.equal(s.sandbox.chosenHypothesis,null);
 assert.equal(s.sandbox.window.activeTrialHypothesisId,null);
 assert.equal(s.element('editor').hidden,true);assert.equal(s.element('workbench').hidden,true);assert.equal(s.element('welcome').hidden,false);
 assert.match(s.element('history').innerHTML,/当前账号/);assert.deepEqual(s.sandbox.historyAccounts,['new-created']);
 assert.equal(originalRun.context.operations.account_id,'existing-a');assert.equal(originalRun.drafts[0].ref,'frozen-draft');
});

test('editing preserves exact original account id when renaming',async()=>{
 const s=setup('existing-a'),originalRun=s.sandbox.run;s.eval('bindAccountForm()');
 await s.submit();
 assert.equal(s.sandbox.calls[0].payload.id,'existing-a');assert.equal(s.rows.length,2);
 assert.equal(s.rows[0].name,'新账号名称');assert.equal(s.rows[1].name,'existing-b');
 assert.equal(s.sandbox.run,originalRun);assert.equal(s.sandbox.editing,true);
 assert.deepEqual(s.sandbox.historyAccounts,['existing-a']);
});

test('editing captures its original id and never substitutes the selected account or changed hidden value',async()=>{
 const s=setup('existing-a');s.eval('bindAccountForm()');
 s.eval("activeAccountId='existing-b'");s.form.elements.id.value='existing-b';
 await s.submit();
 assert.equal(s.sandbox.calls[0].payload.id,'existing-a');assert.equal(s.rows[1].name,'existing-b');
});

test('late account save does not switch a newly selected account back',async()=>{
 const s=setup('existing-a');let resolveSave;
 s.sandbox.operate=async(action,payload)=>{s.sandbox.calls.push({action,payload});return new Promise(resolve=>{resolveSave=resolve;});};
 s.eval('bindAccountForm()');const pending=s.submit();
 s.eval("activeAccountId='existing-b'");resolveSave(true);await pending;
 assert.equal(s.sandbox.calls[0].payload.id,'existing-a');assert.equal(s.eval('activeAccountId'),'existing-b');assert.equal(s.sandbox.renders,0);
 assert.deepEqual(s.sandbox.historyAccounts,[]);assert.equal(s.sandbox.run.run_id,'original-run');
});

test('removed original account fails closed rather than silently creating or overwriting another account',async()=>{
 const s=setup('existing-a');s.eval('bindAccountForm()');s.rows.shift();
 await s.submit();assert.equal(s.sandbox.calls.length,0);
});

test('overview waits for material readiness before updating the first-use completion guide',async()=>{
 const s=setup();let finishMaterials,materialReady=false;
 s.sandbox.api=async()=>[];
 s.sandbox.refreshMaterialDocuments=()=>new Promise(resolve=>{finishMaterials=()=>{materialReady=true;resolve([]);};});
 s.sandbox.gettingStartedHTML=()=>`materials:${materialReady}`;s.eval("currentPage='overview'");
 const pending=s.eval('renderOverview()');await Promise.resolve();
 assert.equal(s.element('gettingStarted').outerHTML,'');
 finishMaterials();await pending;
 assert.equal(s.element('gettingStarted').outerHTML,'materials:true');
});

test('late overview material readiness cannot update a different account guide',async()=>{
 const s=setup();let finishMaterials;
 s.sandbox.api=async()=>[];s.sandbox.refreshMaterialDocuments=()=>new Promise(resolve=>{finishMaterials=resolve;});
 s.sandbox.gettingStartedHTML=()=>'completed';s.eval("currentPage='overview'");
 const pending=s.eval('renderOverview()');await Promise.resolve();s.eval("activeAccountId='existing-b'");
 finishMaterials([]);await pending;
 assert.equal(s.element('gettingStarted').outerHTML,'');
});
