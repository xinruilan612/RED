'use strict';
// Actual browser handlers under DOM/API doubles; not platform or browser E2E.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function experiment(extra={}){
 return {id:'experiment-a',account_id:'a',platform:'xiaohongshu',format:'image_text',source_type:'simulation',window:'24h',
  status:'accepted',algorithm:'content-ucb1-v1',decision_mode:'explore',chosen_pillar:'素材整理',hypothesis:'仅改变开头表达',
  control:'其余条件不变',variant:'问题式开头',sample_size:0,confidence:'insufficient',candidates:[],metric_refs:[],excluded:[],limitations:[],...extra};
}
function publication(extra={}){
 return {id:'post-a',account_id:'a',account:'账号 A',platform:'xiaohongshu',format:'image_text',pillar:'未分类',traffic:'unknown',
  mode:'simulation',provenance:'simulation',status:'SIMULATED',published_at:'2026-09-20T00:00:00Z',created_at:'2026-09-20T00:00:00Z',
  run_id:'run-a',draft_ref:'draft-a',review_ref:'review-a',content_hash:'content-a',
  content:{selected_title:'已确认稿',body:'正文',cta:''},experiment_id:'experiment-a',experiment_snapshot:experiment(),...extra};
}
function fixture(){
 const elements=new Map(),groups=new Map(),requests=[],errors=[],toasts=[],renders=[];
 const make=id=>{
  const element={id,hidden:false,disabled:false,value:'',checked:false,dataset:{},elements:{},listeners:{},_html:'',textContent:'',
   classList:{toggle(){}},setAttribute(){},focus(){},scrollIntoView(){},
   addEventListener(type,handler){this.listeners[type]=handler;},click(){return this.onclick?.({target:this,currentTarget:this});}};
  Object.defineProperty(element,'innerHTML',{get:()=>element._html,set:html=>{
   element._html=html;
   for(const match of html.matchAll(/\bid="([^"]+)"/g))elements.set(match[1],make(match[1]));
   for(const name of ['record','execution-meta']){
    const field=name.replace(/-([a-z])/g,(_m,c)=>c.toUpperCase());
    groups.set('[data-'+name+']',[...html.matchAll(new RegExp('data-'+name+'="([^"]+)"','g'))].map(m=>({dataset:{[field]:m[1]},elements:{}})));
   }
  }});
  return element;
 };
 const element=id=>{if(!elements.has(id))elements.set(id,make(id));return elements.get(id);};
 const state={version:1,accounts:[{id:'a',name:'账号 A',platform:'xiaohongshu',profile:{},aliases:['账号 A']},
   {id:'b',name:'账号 B',platform:'douyin',profile:{},aliases:['账号 B']}],experiments:[],experiment_results:[],publications:[],memories:[],trends:[]};
 let handler=()=>undefined,key=0;
 const context=vm.createContext({URL,activeAccountId:'a',websiteSession:{auth_required:true},fixtureState:state,
  document:{getElementById:element,querySelector:element,querySelectorAll:q=>groups.get(q)||[],addEventListener(){}},
  window:{confirm:()=>true,scrollTo(){},addEventListener(){}},location:{hash:''},
  crypto:{randomUUID:()=>String(++key)},setInterval(){},setTimeout(){return 1;},clearTimeout(){},
  currentAccount:()=>state.accounts.find(a=>a.id===context.activeAccountId),
  accountRows:type=>(state[type]||[]).filter(row=>row.account_id===context.activeAccountId),
  matchesAccount:r=>r.context.operations.account_id===context.activeAccountId,
  syncAccounts(){},fillAccountBrief(){element('targetPlatform').value=context.currentAccount().platform;element('accountName').value=context.currentAccount().name;},
  renderOverview(){},renderAccounts(){},renderPromotion(){},renderLibrary(){},mountSourceSearch(){},
  renderMetrics:id=>{renders.push(id);element('metricWindow').value='24h';},
  recordError:e=>errors.push(e.message),recordToast:text=>toasts.push(text),
  request:(url,method='GET',data)=>{
   requests.push({url,method,data});const response=handler(url,method,data);
   if(response!==undefined)return Promise.resolve(response);
   if(url==='/api/operations')return Promise.resolve(state);
   if(url==='/api/runs'&&method==='POST')return Promise.resolve({run_id:'created',run_status:'QUEUED',current_stage:'brief',context:{workflow:data.workflow}});
   if(url==='/api/runs')return Promise.resolve([]);
   throw new Error('Unexpected request '+url);
  }});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/app.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/operations.js'),'utf8'),context);
 vm.runInContext('ops=fixtureState; api=(...args)=>request(...args); error=recordError; toast=recordToast; render=()=>{}; history=async()=>[];',context);
 for(const [id,value] of Object.entries({mode:'simulation',targetPlatform:'xiaohongshu',accountName:'账号 A',topic:'主题',audience:'读者',tone:'清楚',material:'材料',scenario:'standard',workflow:'professional'}))element(id).value=value;
 element('useKnowledge').checked=true;element('hypothesis').checked=true;
 return {context,state,element,groups,requests,errors,toasts,renders,setHandler:fn=>{handler=fn;},
  eval:code=>vm.runInContext(code,context),
  click:dataset=>element('operationsContent').onclick({target:{closest:()=>({dataset})}})};
}

test('recommendation carries explicit account/platform/format and blocks stale form submissions',async()=>{
 const f=fixture();f.eval("currentPage='memory'");f.context.renderMemory();
 const submit=f.element('experimentForm').onsubmit;
 const event={preventDefault(){},target:{elements:{format:{value:'video'},source_type:{value:'manual'},window:{value:'72h'}}}};
 await submit(event);
 const command=f.requests.find(r=>r.method==='POST').data;
 assert.equal(command.action,'recommend_experiment');
 assert.deepEqual(JSON.parse(JSON.stringify(command.payload)),{account_id:'a',platform:'xiaohongshu',format:'video',source_type:'manual',window:'72h'});
 const count=f.requests.length;f.context.activeAccountId='b';await submit(event);assert.equal(f.requests.length,count);
});

test('unaccepted, cross-account, legacy-format, and already-bound experiments cannot enter creation',()=>{
 for(const change of [{status:'proposed'},{account_id:'b'},{format:undefined},{publication_id:'post-a'},{platform:'douyin'}]){
  const f=fixture();f.state.experiments=[experiment(change)];f.context.chooseExperiment('experiment-a');
  assert.equal(f.eval('chosenExperiment'),null);
 }
 const f=fixture();f.state.experiments=[experiment()];f.eval('busy=true');f.context.chooseExperiment('experiment-a');assert.equal(f.eval('chosenExperiment'),null);
 f.eval('busy=false; editing=true');f.context.window.confirm=()=>false;f.context.chooseExperiment('experiment-a');assert.equal(f.eval('chosenExperiment'),null);
});

test('accepted experiment chooses exact form/source and a normal new run clears stale association',()=>{
 const f=fixture();f.state.experiments=[experiment({format:'video',hypothesis:'实验假设'.repeat(50)})];
 f.context.chooseExperiment('experiment-a');
 assert.equal(f.eval('chosenExperiment.id'),'experiment-a');assert.equal(f.element('mode').value,'simulation');
 assert.equal(f.element('topic').value.length,100);assert.ok(f.element('selectedTrend').textContent.includes('尚未执行'));
 assert.equal(f.context.experimentCreationFields().format,'video');
 f.element('newRun').click();assert.equal(f.eval('chosenExperiment'),null);assert.equal(f.element('selectedTrend').hidden,true);
});

test('real brief submit sends experiment ID and planned format, not fabricated execution or result',async()=>{
 const f=fixture();f.state.experiments=[experiment({format:'video'})];f.context.chooseExperiment('experiment-a');
 await f.element('briefForm').listeners.submit({preventDefault(){},submitter:{disabled:false}});
 const create=f.requests.find(r=>r.url==='/api/runs'&&r.method==='POST').data;
 assert.equal(create.operations.account_id,'a');assert.equal(create.operations.format,'video');assert.equal(create.operations.experiment_id,'experiment-a');
 assert.equal(create.knowledge.enabled,true);assert.ok(!('observed_reward' in create.operations));assert.deepEqual(f.errors,[]);
});

test('source mismatch or revocation after selection blocks the real create handler',async()=>{
 for(const reason of ['source','revoked']){
  const f=fixture();f.state.experiments=[experiment()];f.context.chooseExperiment('experiment-a');
  if(reason==='source')f.element('mode').value='live';else f.state.experiments[0].status='revoked';
  await f.element('briefForm').listeners.submit({preventDefault(){},submitter:{disabled:false}});
  assert.ok(!f.requests.some(r=>r.url==='/api/runs'&&r.method==='POST'));assert.equal(f.errors.length,1);
 }
});

test('ordinary creation keeps promotion association and uses platform-default format',async()=>{
 const f=fixture();f.context.activeAccountId='b';f.element('targetPlatform').value='douyin';
 f.eval("chosenPromotion={id:'promotion-b'}");
 await f.element('briefForm').listeners.submit({preventDefault(){},submitter:{disabled:false}});
 const create=f.requests.find(r=>r.url==='/api/runs'&&r.method==='POST').data;
 assert.equal(create.operations.experiment_id,null);assert.equal(create.operations.format,'video');assert.equal(create.operations.promotion_brief_id,'promotion-b');
});

test('results expose missing baseline, true zero, invalid history, and escape untrusted reasons',()=>{
 const f=fixture(),x=experiment();
 f.state.experiment_results=[{id:'old',experiment_id:x.id,account_id:'a',status:'superseded',invalid_reason:'<img src=x>',created_at:'2026-09-20',window:'24h',format:'image_text',source_type:'simulation',baseline_metric_refs:['baseline-old'],metric_revision:1},
  {id:'new',experiment_id:x.id,account_id:'a',status:'observed_no_baseline',observed_reward:0,baseline_reward:null,difference:null,created_at:'2026-09-21',window:'24h',format:'image_text',source_type:'simulation',baseline_metric_refs:[],metric_revision:2},
  {id:'secret',experiment_id:x.id,account_id:'b',status:'observed',reason:'other account secret',created_at:'2026-09-22'}];
 const html=f.context.experimentResultsHTML(x);
 assert.ok(html.includes('已观测 · 无可比基线'));assert.ok(html.includes('千次阅读播放：0'));
 assert.ok(html.includes('无建议时可比基线')&&html.includes('不计算差值')&&html.includes('旧结果已失效'));
 assert.ok(html.includes('&lt;img src=x&gt;')&&!html.includes('<img'));assert.ok(!html.includes('other account secret'));
});

test('every result state has an honest visible label and excludes unpublished metric shortcuts',()=>{
 const f=fixture(),statuses=['pending_publication','pending_metrics','incomplete','window_mismatch','conditions_mismatch','observed_no_baseline','observed','superseded','blocked'];
 const expected=['待完成发布','待录入目标窗口指标','指标不完整','观察时间不在目标窗口','实际执行条件不一致','无可比基线','完整观测','旧结果已失效','实验不可继续结算'];
 statuses.forEach((status,index)=>{
  f.state.experiment_results=[{id:status,experiment_id:'experiment-a',account_id:'a',status,created_at:'2026-09-21',baseline_metric_refs:[]}];
  assert.ok(f.context.experimentResultsHTML(experiment()).includes(expected[index]));
 });
 f.state.publications=[publication({status:'APPROVED',published_at:null})];
 const html=f.context.experimentCardHTML(experiment({publication_id:'post-a'}));
 assert.ok(!html.includes('data-to-metrics=')&&!html.includes('data-use-experiment='));assert.ok(html.includes('非')||html.includes('不代表因果'));
 const pending=f.context.publicationExperimentHTML(f.state.publications[0]);
 assert.ok(!pending.includes('data-execution-meta='));assert.ok(pending.includes('当前仅为计划'));
});

test('publication conditions require explicit user confirmation and never auto-submit plan values',async()=>{
 const f=fixture();f.state.publications=[publication()];f.eval("currentPage='publish'");f.context.renderPublications();
 assert.ok(!f.requests.some(r=>r.method==='POST'));
 assert.ok(f.element('operationsContent').innerHTML.includes('不会自动采用建议'));
 const form=f.groups.get('[data-execution-meta]')[0];
 form.elements={confirmed:{checked:false},format:{value:'video'},pillar:{value:'实际栏目'},traffic:{value:'unknown'}};
 await form.onsubmit({preventDefault(){}});assert.ok(!f.requests.some(r=>r.method==='POST'));
 form.elements.confirmed.checked=true;await form.onsubmit({preventDefault(){}});
 const command=f.requests.find(r=>r.method==='POST').data;
 assert.equal(command.action,'post_metadata');assert.deepEqual(JSON.parse(JSON.stringify(command.payload)),{id:'post-a',format:'video',pillar:'实际栏目',traffic:'unknown'});
 const count=f.requests.length;f.context.activeAccountId='b';await form.onsubmit({preventDefault(){}});assert.equal(f.requests.length,count);
});

test('evaluate delegates only an experiment ID and metrics shortcut keeps its target window',async()=>{
 const f=fixture();f.state.experiments=[experiment({window:'72h',publication_id:'post-a'})];f.state.publications=[publication()];f.eval("currentPage='memory'");
 await f.click({evaluateExperiment:'experiment-a'});
 const command=f.requests.find(r=>r.method==='POST').data;
 assert.equal(command.action,'evaluate_experiment');assert.deepEqual(Object.keys(command.payload),['id']);
 await f.click({toMetrics:'post-a',metricWindow:'72h'});
 assert.equal(f.eval('currentPage'),'metrics');assert.equal(f.element('metricWindow').value,'72h');assert.equal(f.renders.at(-1),'post-a');
 const count=f.requests.length;f.context.activeAccountId='b';await f.click({evaluateExperiment:'experiment-a'});assert.equal(f.requests.length,count);
});

test('late confirmed-run responses cannot leak across account or page remounts',async()=>{
 const f=fixture(),pending=deferred();f.setHandler(url=>url==='/api/runs'?pending.promise:undefined);f.eval("currentPage='publish'");f.context.renderPublications();
 const request=f.element('loadConfirmed').onclick();
 f.context.activeAccountId='b';f.context.renderPublications();
 pending.resolve([{run_id:'old-run',accepted_ref:'draft',run_status:'SUCCEEDED',context:{topic:'other account hidden',operations:{account_id:'a'}}}]);await request;
 assert.equal(f.element('confirmedRuns').innerHTML,'');assert.deepEqual(f.errors,[]);
});

test('ordinary publications and promotion snapshots remain visible without experimental controls',()=>{
 const f=fixture();f.state.publications=[publication({experiment_id:null,promotion:{goal_label:'建立信任',public_service:{name:'原创摄影'},service_version:1,id:'brief-a',problem_source_label:'用户提供'}})];
 f.eval("currentPage='publish'");f.context.renderPublications();const html=f.element('operationsContent').innerHTML;
 assert.ok(html.includes('接单推广')&&html.includes('原创摄影'));assert.ok(!html.includes('data-execution-meta='));assert.ok(html.includes('data-to-metrics='));
});

test('manual publication form accepts and preserves second precision without relaxing experiment time rules',async()=>{
 const f=fixture();f.state.publications=[publication({mode:'live',provenance:'manual',status:'APPROVED',published_at:null})];
 f.eval("currentPage='publish'");f.context.renderPublications();
 const html=f.element('operationsContent').innerHTML;
 assert.match(html,/name="published_at" type="datetime-local" step="1" required/);
 assert.ok(html.includes('可输入秒')&&html.includes('不得早于稿件进入发布中心的准备时间'));
 const form=f.groups.get('[data-record]')[0],publishedAt='2026-09-22T12:34:56';
 form.elements={url:{value:'https://www.xiaohongshu.com/explore/example'},published_at:{value:publishedAt}};
 await form.onsubmit({preventDefault(){}});
 const command=f.requests.find(r=>r.method==='POST').data;
 assert.equal(command.action,'record');assert.equal(command.payload.published_at,new Date(publishedAt).toISOString());
 assert.equal(new Date(command.payload.published_at).getSeconds(),56);
});

test('repeated confirmed-list clicks keep only the newest response',async()=>{
 const f=fixture(),first=deferred(),second=deferred();let calls=0;
 f.setHandler(url=>url==='/api/runs'?(++calls===1?first.promise:second.promise):undefined);
 f.eval("currentPage='publish'");f.context.renderPublications();const click=f.element('loadConfirmed').onclick;
 const one=click(),two=click();
 const row=topic=>({run_id:topic,accepted_ref:'draft',run_status:'SUCCEEDED',context:{topic,operations:{account_id:'a'}}});
 second.resolve([row('最新列表')]);await two;first.resolve([row('过期列表')]);await one;
 assert.ok(f.element('confirmedRuns').innerHTML.includes('最新列表'));assert.ok(!f.element('confirmedRuns').innerHTML.includes('过期列表'));
});
