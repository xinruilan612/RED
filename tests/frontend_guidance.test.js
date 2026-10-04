'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function setup(){
 const elements=new Map(),handlers={};
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:false,value:'',checked:false,disabled:false,textContent:'',innerHTML:'',dataset:{},listeners:{},selectedOptions:[],classList:{toggle(){}},setAttribute(){},addEventListener(type,handler){(this.listeners[type]??=[]).push(handler);},scrollIntoView(){},querySelector(){return element(id+' child');},insertAdjacentHTML(_where,text){this.innerHTML+=text;}});return elements.get(id);};
 const sandbox={document:{getElementById:element,querySelector:element,querySelectorAll(){return [];},addEventListener(type,handler){handlers[type]=handler;}},window:{addEventListener(){},confirm(){return true;},scrollTo(){}},localStorage:{getItem(){return '';},setItem(){}},location:{hash:''},websiteSession:{auth_required:true},setInterval(){},setTimeout(){},clearTimeout(){},crypto:{randomUUID:()=> 'test-key'}};
 vm.createContext(sandbox);
 for(const file of ['app','operations','account','knowledge','windtunnel','trials','guidance'])vm.runInContext(fs.readFileSync(`frontend/${file}.js`,'utf8'),sandbox);
 return {element,handlers,eval:code=>vm.runInContext(code,sandbox)};
}

test('five primary destinations keep advanced tools secondary and process closed by default',()=>{
 const html=fs.readFileSync('frontend/index.html','utf8');
 const main=html.match(/<nav class="workspace-nav"[\s\S]*?<\/nav>/)[0];
 assert.deepEqual([...main.matchAll(/data-page="([^"]+)"/g)].map(m=>m[1]),['overview','studio','library','publish','memory']);
 assert.match(html,/data-go-page="trials"/);assert.match(html,/data-go-page="examples"/);
 assert.match(html,/<details id="processDetails" class="process-disclosure">/);
 assert.ok(html.indexOf('id="draftPanel"')<html.indexOf('id="processDetails"'));
 assert.match(html,/src="\/guidance.js"/);
});

test('sticky account header has equivalent prefixed blur for older supported Safari',()=>{
 const css=fs.readFileSync('frontend/style.css','utf8');
 assert.match(css,/(?<!-)backdrop-filter:blur\(12px\)/);
 assert.match(css,/-webkit-backdrop-filter:blur\(12px\)/);
});

test('simulation archive stays secondary but keeps an explicitly opened exercise visible after approval',()=>{
 const s=setup();s.eval("activeAccountId='a';ops={accounts:[{id:'a',name:'测试账号',profile:{}}],publications:[{id:'p',account_id:'a',mode:'simulation',status:'AWAITING_APPROVAL',content:{selected_title:'虚构演练'}}]};renderPublications()");
 assert.equal(s.element('simulationArchive').open,false);
 s.element('simulationArchive').open=true;s.eval("ops.publications[0].status='APPROVED';renderPublications()");
 assert.equal(s.element('simulationArchive').open,true);
 assert.match(s.element('operationsContent').innerHTML,/执行模拟发布（不发到平台）/);
 s.element('simulationArchive').open=false;s.eval('renderPublications()');
 assert.equal(s.element('simulationArchive').open,false);
});

test('legacy page hashes select a meaningful primary group without discarding their destination',()=>{
 const s=setup();s.eval('renderOperations=()=>{};ops={}');
 for(const [page,group] of [['accounts','overview'],['trends','studio'],['windtunnel','studio'],['trials','studio'],['metrics','publish']]){
  s.eval(`showPage('${page}')`);assert.equal(s.eval('currentPage'),page);assert.equal(s.eval('navigationGroup(currentPage)'),group);
 }
 s.eval("showPage('metrics')");assert.match(s.element('pageTools').innerHTML,/作品归档/);assert.match(s.element('pageTools').innerHTML,/aria-current="page">数据复盘/);
});

test('onboarding completion only uses the current stable account and actual saved drafts',()=>{
 const s=setup();s.eval("a={id:'a',profile:{positioning:'教育',audience:'新生',goal:'验证方向'}};docs=[{account_id:'other'}];runs=[{context:{operations:{account_id:'other'}},drafts:[{}]}]");
 assert.equal(s.eval('onboardingState(a,docs,runs).profile'),true);
 assert.equal(s.eval('onboardingState(a,docs,runs).material'),false);
 assert.equal(s.eval('onboardingState(a,docs,runs).creation'),false);
 s.eval("docs.push({account_id:'a'});runs.push({workflow_type:'windtunnel',context:{operations:{account_id:'a'}},drafts:[{}]})");
 assert.equal(s.eval('onboardingState(a,docs,runs).creation'),false);
 s.eval("runs.push({context:{operations:{account_id:'a'}},drafts:[{}]})");
 assert.equal(s.eval('onboardingState(a,docs,runs).creation'),false);
 s.eval("runs.push({run_status:'SUCCEEDED',accepted_ref:'d',context:{operations:{account_id:'a'}},drafts:[{ref:'d'}]})");
 assert.equal(s.eval('onboardingState(a,docs,runs).creation'),true);
 const html=s.eval('gettingStartedHTML(a,runs)');assert.match(html,/素材（可选）/);assert.match(html,/不是强制前置/);assert.doesNotMatch(html,/sampleAccount/);
 assert.match(html,/<details id="gettingStarted"/);
});

test('new user guidance links perform navigation only and respect dirty or busy state',()=>{
 const s=setup();s.eval("navigations=[];showPage=p=>navigations.push(p)");
 const button={disabled:false,dataset:{goPage:'library'},hasAttribute(){return false;}};
 s.handlers.click({target:{closest(){return button;}}});assert.equal(s.eval('navigations.join()'),'library');
 s.eval('busy=true');s.handlers.click({target:{closest(){return button;}}});assert.equal(s.eval('navigations.length'),1);
 s.eval('busy=false;editing=true;window.confirm=()=>false');s.handlers.click({target:{closest(){return button;}}});assert.equal(s.eval('navigations.length'),1);
});

test('current draft is the default view and old versions remain opt-in comparable',()=>{
 const s=setup();s.eval("run={mode:'simulation',run_id:'r',accepted_ref:null,in_flight:false,allowed_actions:[],artifacts:[],drafts:[{ref:'d1',actor:'model',content:{selected_title:'旧标题',body:'旧正文',cta:'',tags:[]}},{ref:'d2',actor:'user',content:{selected_title:'新标题',body:'新正文',cta:'',tags:[]}}]};renderDraft()");
 assert.match(s.element('draftView').innerHTML,/新正文/);assert.doesNotMatch(s.element('draftView').innerHTML,/旧正文/);
 s.element('compareVersions').checked=true;s.eval('renderDraft()');assert.match(s.element('draftView').innerHTML,/旧正文/);assert.match(s.element('draftView').innerHTML,/新正文/);
 s.element('versionSelect').onchange({target:{value:'0'}});assert.match(s.element('draftView').innerHTML,/旧正文/);assert.equal(s.element('compareVersions').checked,false);
});

test('starting from guidance asks only once before discarding an unsaved edit',()=>{
 const s=setup();s.eval('editing=true;confirmations=0;window.confirm=()=>{confirmations++;return true;};');
 s.element('newRun').click=()=>s.element('newRun').onclick();
 s.handlers.click({target:{closest(){return {disabled:false,hasAttribute(){return true;}};}}});
 assert.equal(s.eval('confirmations'),1);assert.equal(s.eval('editing'),false);
});

test('simultaneous same-account material refreshes share one request without mixing accounts',async()=>{
 const s=setup();s.eval("activeAccountId='a';ops={accounts:[{id:'a',profile:{}}]};requests=0;resolveMaterial=null;api=()=>{requests++;return new Promise(resolve=>resolveMaterial=resolve)}");
 const first=s.eval('refreshMaterialDocuments()'),second=s.eval('refreshMaterialDocuments()');assert.equal(s.eval('requests'),1);
 s.eval("resolveMaterial([{id:'doc',title:'资料',version:1,metadata:{}}])");await Promise.all([first,second]);
 assert.equal(s.eval('materialDocsCache[0].account_id'),'a');assert.equal(s.eval('materialRefreshes.size'),0);
});

test('new creation clears stale draft and associations while explicit topic or hypothesis links stay scoped',async()=>{
 const s=setup();s.eval("run={run_id:'old'};chosenTrend={id:'old'};chosenHypothesis={id:'old'};window.activeTrialHypothesisId='old';editing=false");
 await s.eval('startCreation()');assert.equal(s.eval('run'),null);assert.equal(s.eval('chosenTrend'),null);assert.equal(s.eval('chosenHypothesis'),null);assert.equal(s.eval('window.activeTrialHypothesisId'),null);
 await s.eval("startCreation({trend:{id:'new-trend'}})");assert.equal(s.eval('chosenTrend.id'),'new-trend');assert.equal(s.eval('chosenHypothesis'),null);
 await s.eval("startCreation({hypothesis:{id:'new-hypothesis'}})");assert.equal(s.eval('chosenHypothesis.id'),'new-hypothesis');assert.equal(s.eval('chosenTrend'),null);
});

test('new creation advances library transfer sequence only after navigation is accepted',()=>{
 const s=setup();
 assert.equal(s.eval('creationSequence'),0);
 assert.equal(s.eval('startCreation()'),true);
 assert.equal(s.eval('creationSequence'),1);
 s.eval("editing=true;window.confirm=()=>false;run={run_id:'kept'}");
 assert.equal(s.eval('startCreation()'),false);
 assert.equal(s.eval('creationSequence'),1);
 assert.equal(s.eval('run.run_id'),'kept');
 s.eval('editing=false;busy=true');
 assert.equal(s.eval('startCreation()'),false);
 assert.equal(s.eval('creationSequence'),1);
 s.eval('busy=false');
 assert.equal(s.eval('startCreation()'),true);
 assert.equal(s.eval('creationSequence'),2);
});

test('topic entry asks once and cancelling does not alter the existing brief',()=>{
 for(const consent of [true,false]){
  const s=setup();s.eval(`activeAccountId='a';ops={accounts:[{id:'a',platform:'xiaohongshu',name:'测试',profile:{}}],trends:[{id:'t',platform:'xiaohongshu',title:'新选题',category:'学习',angle:'步骤'}]};editing=true;confirmations=0;window.confirm=()=>{confirmations++;return ${consent}};`);
  s.element('topic').value='原需求';s.eval("chooseTrend('t')");assert.equal(s.eval('confirmations'),1);assert.equal(s.element('topic').value,consent?'新选题':'原需求');
 }
});

test('plan entry asks once and cancelling leaves both draft and topic untouched',async()=>{
 for(const consent of [true,false]){
  const s=setup();s.eval(`activeAccountId='a';ops={accounts:[],plans:[{id:'p',account_id:'a',tasks:[{id:'t',title:'新计划主题'}]}]};run={run_id:'old'};editing=true;confirmations=0;window.confirm=()=>{confirmations++;return ${consent}};`);
  s.element('topic').value='原需求';
  await s.element('operationsContent').listeners.click[0]({target:{closest(){return {dataset:{planCreate:'t',plan:'p'}};}}});
  assert.equal(s.eval('confirmations'),1);assert.equal(s.element('topic').value,consent?'新计划主题':'原需求');
  assert.equal(s.eval('run?.run_id??null'),consent?null:'old');
 }
});

test('hypothesis entry asks once and cancelled navigation cannot change the brief',async()=>{
 for(const consent of [true,false]){
  const s=setup();s.eval(`activeAccountId='a';currentPage='trials';ops={accounts:[],hypotheses:[{id:'h',account_id:'a',statement:'新假设',audience:'测试读者'}]};run={run_id:'old'};editing=true;confirmations=0;window.confirm=()=>{confirmations++;return ${consent}};`);
  s.element('trialHypothesisForm').elements={objective:{value:'audience_growth'},metric:{}};s.eval('trialBind()');
  s.element('topic').value='原需求';await s.element('operationsContent').listeners.click.at(-1)({target:{closest(){return {dataset:{trialCreate:'h'}};}}});
  assert.equal(s.eval('confirmations'),1);assert.equal(s.element('topic').value,consent?'新假设':'原需求');assert.equal(s.eval('run?.run_id??null'),consent?null:'old');
 }
});

test('next-action guidance does not claim a saved edit already passed review',()=>{
 const s=setup();s.eval("task={run_status:'RUNNING',current_stage:'reviewer',drafts:[{}],review:null,allowed_actions:['next']}");
 assert.match(s.eval('nextStepGuidance(task)'),/尚未完成复审/);
 s.eval("task.run_status='SUCCEEDED'");assert.match(s.eval('nextStepGuidance(task)'),/真实发布需你在平台完成/);
 s.eval('editing=true;task.run_status="RUNNING"');assert.match(s.eval('nextStepGuidance(task)'),/不调用 AI/);
});

test('metric default uses actual save-time seconds while edited history and unknown values stay intact',async()=>{
 const s=setup();
 s.eval("activeAccountId='a';ops={publications:[{id:'p',account_id:'a',published_at:new Date().toISOString(),provenance:'simulation',content:{selected_title:'演练'}}],metrics:[],analyses:[]};renderMetrics('p');saved=[];operate=async(action,payload)=>saved.push(payload)");
 assert.match(s.element('operationsContent').innerHTML,/id="metricObserved" type="datetime-local" step="1"/);
 const initial=s.element('operationsContent').innerHTML.match(/id="metricObserved"[^>]*value="([^"]+)"/)[1];
 s.element('metricObserved').value=initial;s.element('metricPost').value='p';s.element('metricWindow').value='24h';
 const before=Date.now();await s.element('metricForm').onsubmit({preventDefault(){}});
 assert.ok(Date.parse(s.eval('saved[0].observed_at'))>=before);assert.equal(s.eval('saved[0].views'),null);
 s.element('metricObserved').value='2026-09-29T09:03:12';s.element('metricObserved').oninput();await s.element('metricForm').onsubmit({preventDefault(){}});
 assert.equal(s.eval('saved[1].observed_at'),new Date('2026-09-29T09:03:12').toISOString());
});

test('insufficient analyses explain why no memory exists instead of asking to repeat them',()=>{
 const s=setup();s.eval("activeAccountId='a';ops={memories:[],analyses:[{account_id:'a',status:'insufficient'}]};renderMemory()");
 assert.match(s.element('operationsContent').innerHTML,/每篇复盘都有下一步建议/);assert.match(s.element('operationsContent').innerHTML,/积累可比较的作品/);assert.match(s.element('operationsContent').innerHTML,/data-go-page="metrics"/);
});

test('trial inputs keep minute precision after shared metric formatter gains seconds',()=>{
 const s=setup();
 assert.equal(s.eval('dateInput().length'),19);assert.equal(s.eval('trialDate().length'),16);
});

 test('first real recap is readable and actionable without empty comparison rows',()=>{
 const s=setup();s.eval(`provider={ready:true};ops={publications:[{id:'p',content:{selected_title:'早间护肤'}}],metrics:[{id:'m',values:{views:19,saves:5,likes:2,comments:0}}]};report={id:'a',publication_id:'p',metric_id:'m',status:'insufficient',source_type:'manual',comparisons:{saves:{baseline:null}},flags:[],metric_refs:['m']}`);
 const html=s.eval('analysisHTML(report)');
 assert.match(html,/>19</);assert.match(html,/>5</);assert.match(html,/下一篇改什么/);assert.match(html,/免费，不调用 AI/);assert.match(html,/data-ai-review-open/);assert.doesNotMatch(html,/不足以比较|<pre>|历史中位数/);
 s.eval("report.source_type='simulation'");assert.doesNotMatch(s.eval('analysisHTML(report)'),/data-ai-review-open/);assert.match(s.eval('analysisHTML(report)'),/示例数据计算/);
 });

test('ordinary new creation chooses configured real API and never silently starts a paid call',()=>{
 const s=setup();s.eval("provider={ready:true};activeAccountId='a';ops={accounts:[]};busy=false;editing=false;run=null;paidCalls=0;api=async()=>{paidCalls++;return []};refreshMaterialDocuments=()=>{};fillAccountBrief=()=>{};startCreation()");
 assert.equal(s.element('mode').value,'live');assert.doesNotMatch(fs.readFileSync('frontend/index.html','utf8'),/默认免费模拟/);assert.equal(s.eval('paidCalls'),0);assert.match(s.element('modeNotice').textContent,/DeepSeek/);
});

test('empty reader conditions offer an explicit free author question without fake feedback',()=>{
 const s=setup();s.eval("wt.run={workflow_type:'windtunnel',mode:'live',run_status:'RUNNING',current_stage:'wt_conditions',in_flight:false,allowed_actions:['set_initial_conditions'],background:{status:'blocked',error:'检查条件需要1至12项'},windtunnel:{scene:'护肤新手',condition_sets:[],sources:[]}};wt.busy=false");
 const html=s.eval('wtCardsView()');assert.match(html,/id="wtInitialQuestion"/);assert.match(html,/保存我的问题（不调用 AI）/);assert.match(html,/来源：作者设定/);
 s.eval('wt.run.in_flight=true');assert.doesNotMatch(s.eval('wtCardsView()'),/id="wtInitialQuestion"/);
});
