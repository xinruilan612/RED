'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const guidance=fs.readFileSync('frontend/guidance.js','utf8');
function setup(){
 const host={},calls=[],listeners={};
 const context={pageInfo:{},materialDocsCache:[],websiteSession:{auth_required:true},busy:false,opsBusy:false,auto:true,
  $:id=>id==='newRun'?{click:()=>{if(context.dirtyGuard())calls.push('new');}}:host,
  dirtyGuard:()=>true,showPage:page=>calls.push(page),document:{addEventListener:(name,fn)=>listeners[name]=fn}};
 vm.createContext(context);vm.runInContext(guidance,context);return {context,host,calls,listeners};
}
test('onboarding completion belongs to exact account and accepted draft',()=>{
 const {context}=setup(),a={id:'a',profile:{positioning:'摄影',audience:'初学者',goal:'介绍产品'}};
 const complete={run_status:'SUCCEEDED',accepted_ref:'d',drafts:[{ref:'d'}],context:{operations:{account_id:'b'}}};
 assert.equal(context.onboardingState(a,[{account_id:'b'}],[complete]).creation,false);
 assert.equal(context.onboardingState(a,[{account_id:'b'}],[complete]).material,false);
 complete.context.operations.account_id='a';assert.equal(context.onboardingState(a,[],[complete]).creation,true);
 const html=context.gettingStartedHTML(a,[complete]);assert.match(html,/^<details/);assert.doesNotMatch(html,/<details[^>]*\bopen\b/);
 complete.accepted_ref='missing';assert.equal(context.onboardingState(a,[],[complete]).creation,false);
});
test('right tools preserve exact route selection and omit retired checks',()=>{
 const {context,host}=setup();context.renderPageTools('trends');
 assert.match(host.innerHTML,/class="active" data-go-page="trends" aria-current="page"/);
 assert.doesNotMatch(host.innerHTML,/windtunnel|trials|读者理解/);
 for(const route of ['library','connections','models']){context.renderPageTools(route);assert.equal(host.hidden,true);}
 const operations=fs.readFileSync('frontend/operations.js','utf8');
 assert.match(operations,/const active=b.dataset.page===page/);assert.doesNotMatch(operations,/navigationGroup/);
 assert.match(operations,/if\(page==='trials'\|\|page==='windtunnel'\)page='studio'/);
});
test('delegated navigation and creation respect busy and dirty checks',()=>{
 const {context,calls,listeners}=setup();
 const click=(creation=false)=>listeners.click({target:{closest:()=>({disabled:false,dataset:{goPage:'library'},hasAttribute:()=>creation})}});
 context.busy=true;click();click(true);assert.equal(calls.length,0);
 context.busy=false;context.opsBusy=true;click();assert.equal(calls.length,0);
 context.opsBusy=false;context.dirtyGuard=()=>false;click();click(true);assert.equal(calls.length,0);
 context.dirtyGuard=()=>true;click();click(true);assert.deepEqual(calls,['library','new']);
});
test('creation statuses distinguish pending confirmation from running',()=>{
 const {context}=setup();assert.equal(context.creationStatusText({run_status:'WAITING_USER',wait_reason:'final_confirmation'}),'成稿待你确认');
 assert.equal(context.creationStatusText({run_status:'RUNNING'}),'正在创作');
});
