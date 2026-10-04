'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function setup(){
 const elements=new Map(),handlers={};
 const element=id=>{
  if(!elements.has(id))elements.set(id,{innerHTML:'',disabled:false,insertAdjacentHTML(_position,html){this.innerHTML+=html;},addEventListener(event,handler){handlers[event]=handler;}});
  return elements.get(id);
 };
 const sandbox={document:{getElementById:element,querySelector:()=>element('workspace'),querySelectorAll:()=>[]},window:{activeTrialHypothesisId:'unrelated-trial'},setInterval(){},crypto:{randomUUID:()=> 'bridge-test-key'}};
 vm.createContext(sandbox);
 vm.runInContext(`
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pageInfo={},states={};
  let activeAccountId='account-1',currentPage='studio',viewVersion=1;
  let run={run_id:'creation-1',workflow_type:'creation',status_version:4,snapshot_id:'snapshot-1',context:{operations:{account_id:'account-1'},audience:'第一次整理课程资料的学生',material:'作者实际操作记录：菜单内选择导出。',evidence:[{source_id:'kb-source',title:'导出说明',text:'选择 CSV 与 UTF-8。',url:'https://example.org/help',document_id:'doc-1',version:2,page:3,offset:40}]},drafts:[{ref:'v1',content_hash:'old-hash',content:{selected_title:'旧标题',body:'旧正文',cta:'',tags:[]}},{ref:'v2',content_hash:'current-hash',content:{selected_title:'新标题',body:'当前正文',cta:'请检查下载目录。',tags:['课程资料']}}]};
  let ops={hypotheses:[]},calls=[],errors=[],pages=[],allowLeave=true;
  const currentAccount=()=>({id:activeAccountId,name:'学习账号',profile:{audience:'学生'}});
  const dirtyGuard=()=>allowLeave;
  const error=e=>errors.push(e.message);
  const showPage=page=>{currentPage=page;pages.push(page);};
  let response=JSON.parse(JSON.stringify(run));
  let api=async(path,method='GET',body)=>{calls.push({path,method,body});return response;};
 `,sandbox);
 vm.runInContext(fs.readFileSync('frontend/windtunnel.js','utf8'),sandbox);
 return {sandbox,element,handlers,eval:code=>vm.runInContext(code,sandbox),value:code=>JSON.parse(vm.runInContext(`JSON.stringify(${code})`,sandbox))};
}

test('bridge imports the exact draft and existing material snapshot without saving or starting',async()=>{
 const s=setup(),original=s.value('run');
 assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),true);
 const f=s.value('wt.form');
 assert.equal(f.inputMode,'import');assert.equal(f.importRun,'creation-1');assert.equal(f.importRef,'v2');
 assert.equal(f.title,'新标题');assert.equal(f.text,'当前正文\n\n请检查下载目录。\n\n课程资料');
 assert.equal(f.scene,'第一次整理课程资料的学生');assert.equal(f.permission,false);assert.equal(f.feedback,'');assert.equal(f.origin,'user_hypothesis');
 assert.equal(f.importMaterials.length,2);assert.match(f.importMaterials[1].origin,/doc-1.*v2.*页 3.*位置 40.*kb-source.*https:\/\/example.org\/help/);
 assert.match(f.importMaterials[1].origin,/未独立核实/);
 assert.deepEqual(s.value('calls.map(c=>[c.path,c.method])'),[['/api/runs/creation-1','GET']]);
 assert.deepEqual(s.value('pages'),['windtunnel']);assert.equal(s.eval('wt.run'),null);assert.equal(s.eval('window.activeTrialHypothesisId'),null);
 assert.deepEqual(s.value('run'),original);assert.match(s.eval('wt.message'),/不会自动启动/);
});

test('wrong account, windtunnel workflow and missing version cannot be imported',async()=>{
 for(const change of ["run.context.operations.account_id='account-2'","run.workflow_type='windtunnel'","run.drafts=[]"]){
  const s=setup();s.eval(change);
  assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),false);
  assert.equal(s.eval('calls.length'),0);assert.equal(s.eval('pages.length'),0);assert.match(s.eval('errors[0]'),/当前账号/);
 }
});

test('declining unsaved-edit guard preserves the current form and makes no request',async()=>{
 const s=setup();s.eval("wt.form=wtFreshForm();wt.form.title='未保存检查';allowLeave=false");
 assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),false);
 assert.equal(s.eval('wt.form.title'),'未保存检查');assert.equal(s.eval('calls.length'),0);assert.equal(s.eval('pages.length'),0);
});

test('server version change or removed draft rejects stale selection before navigation',async()=>{
 for(const change of ["response.status_version++","response.drafts.pop()","response.drafts[1].content.body='已改变正文'","response.context.operations.account_id='account-2'","response.workflow_type='windtunnel'"]){
  const s=setup();s.eval(change);
  assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),false);
  assert.equal(s.eval('pages.length'),0);assert.match(s.eval('errors[0]'),/版本已变化/);
 }
});

test('account switch while the source request is pending cannot overwrite another account',async()=>{
 const s=setup();s.eval("api=(path,method='GET')=>{calls.push({path,method});return new Promise(resolve=>{finish=resolve;});};wt.form=wtFreshForm();wt.form.title='另一个账号的未保存检查'");
 const pending=s.eval("openDraftReaderCheck(run,'v2')");
 s.eval("activeAccountId='account-2';finish(response)");
 assert.equal(await pending,false);assert.equal(s.eval('wt.form.title'),'另一个账号的未保存检查');assert.equal(s.eval('pages.length'),0);assert.equal(s.eval('errors.length'),0);
});

test('a new draft or selected-version change during the request cannot navigate unexpectedly',async()=>{
 for(const change of ["run.drafts.push({ref:'v3',content:{body:'另一版'}})","viewVersion=0","currentPage='library'"]){
  const s=setup();s.eval("api=()=>new Promise(resolve=>{finish=resolve;})");
  const pending=s.eval("openDraftReaderCheck(run,'v2')");s.eval(change);s.eval('finish(response)');
  assert.equal(await pending,false);assert.equal(s.eval('pages.length'),0);
 }
});

test('a later bridge request wins and an older source response cannot overwrite it',async()=>{
 const s=setup();s.eval("resolvers=[];api=()=>new Promise(resolve=>resolvers.push(resolve))");
 const first=s.eval("openDraftReaderCheck(run,'v1')"),second=s.eval("openDraftReaderCheck(run,'v2')");
 s.eval('resolvers[1](response)');assert.equal(await second,true);
 s.eval('resolvers[0](response)');assert.equal(await first,false);
 assert.equal(s.eval('wt.form.importRef'),'v2');assert.equal(s.eval('pages.length'),1);
});

test('late list refresh rejects changed source snapshots and account switches',async()=>{
 const s=setup();assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),true);
 s.eval("response.status_version++;api=async path=>path.includes('checklists')?[]:[response]");
 await s.eval('renderWindtunnel()');assert.equal(s.eval('wt.form.importRun'),'');assert.match(s.eval('wt.failure'),/源稿件已变化/);
 const other=setup();assert.equal(await other.eval("openDraftReaderCheck(run,'v2')"),true);
 other.eval("resolvers=[];api=()=>new Promise(resolve=>resolvers.push(resolve))");
 const load=other.eval('renderWindtunnel()');other.eval("activeAccountId='account-2';wt.form.title='账号 2 的内容';resolvers[0]([response]);resolvers[1]([])");
 await load;assert.equal(other.eval('wt.form.title'),'账号 2 的内容');
});

test('explicit form save preserves exact imported references and material provenance in real AI mode',async()=>{
 const s=setup();assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),true);
 s.eval("wt.form.permission=true;created={run_id:'reader-1',workflow_type:'windtunnel',windtunnel:{drafts:[]},context:{account_id:activeAccountId},allowed_actions:[]};api=async(path,method,body)=>{calls.push({path,method,body});return created;}");
 await s.eval('wtCreate({preventDefault(){},submitter:{disabled:false}})');
 const post=s.value("calls.find(c=>c.method==='POST')");
 assert.equal(post.path,'/api/runs');assert.deepEqual(post.body.import,{run_id:'creation-1',draft_ref:'v2'});
 assert.equal(post.body.mode,'live');assert.equal(post.body.title,undefined);assert.equal(post.body.text,undefined);
 assert.equal(post.body.materials.length,2);assert.equal(post.body.materials[1].text,'选择 CSV 与 UTF-8。');assert.match(post.body.materials[1].origin,/doc-1/);
 assert.deepEqual(post.body.feedback,[]);assert.equal(post.body.hypothesis_id,null);assert.equal(s.eval("calls.filter(c=>c.method==='POST').length"),1);
});

test('saving cannot auto-consent or create a check for a switched account',async()=>{
 for(const change of ["wt.form.permission=false","wt.form.permission=true;activeAccountId='account-2'"]){
  const s=setup();assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),true);s.eval(change);
  await s.eval('wtCreate({preventDefault(){},submitter:{disabled:false}})');
  assert.equal(s.eval("calls.filter(c=>c.method==='POST').length"),0);
 }
});

test('switching imported version clears prior draft material snapshots',async()=>{
 const s=setup();assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),true);s.eval('wtPaint()');
 s.handlers.change({target:{dataset:{wtField:'importRef'},type:'select-one',value:'v1'}});
 assert.equal(s.eval('wt.form.importRef'),'v1');assert.equal(s.eval('wt.form.importMaterials.length'),0);assert.equal(s.eval('wt.form.bridge'),null);
});

test('long source text is split without loss and excessive material is not silently truncated',async()=>{
 const s=setup();s.eval("run.context.evidence=[];run.context.material='字'.repeat(6001);response=JSON.parse(JSON.stringify(run))");
 assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),true);
 assert.deepEqual(s.value('wt.form.importMaterials.map(s=>s.text.length)'),[6000,1]);assert.equal(s.eval("wt.form.importMaterials.map(s=>s.text).join('')===run.context.material"),true);
 const large=setup();large.eval("run.context.material='字'.repeat(24001);run.context.evidence=[];response=JSON.parse(JSON.stringify(run))");
 assert.equal(await large.eval("openDraftReaderCheck(run,'v2')"),false);assert.equal(large.eval('pages.length'),0);assert.match(large.eval('errors[0]'),/没有自动截断或创建任务/);
});

test('source splitting preserves complete Unicode characters at the material boundary',async()=>{
 const s=setup();s.eval("run.context.evidence=[];run.context.material='字'.repeat(5999)+'📚'.repeat(3);response=JSON.parse(JSON.stringify(run))");
 assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),true);
 assert.deepEqual(s.value('wt.form.importMaterials.map(s=>Array.from(s.text).length)'),[6000,2]);
 assert.equal(s.eval("wt.form.importMaterials.map(s=>s.text).join('')===run.context.material"),true);
});

test('long source URLs are rejected explicitly instead of dropping location or URL provenance',async()=>{
 const s=setup();s.eval("wt.form=wtFreshForm();wt.form.title='原有未保存检查';run.context.evidence[0].url='https://example.org/help?reference='+'x'.repeat(800);response=JSON.parse(JSON.stringify(run))");
 const original=s.value('run.context.evidence[0]');
 assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),false);
 assert.equal(s.eval('pages.length'),0);assert.equal(s.eval('wt.form.title'),'原有未保存检查');
 assert.deepEqual(s.value('run.context.evidence[0]'),original);
 assert.equal(s.eval("calls.filter(c=>c.method==='POST').length"),0);
 assert.match(s.eval('errors[0]'),/无法完整带入.*未截断来源或创建任务/);
});

test('switching to pasted text keeps old material snapshots labelled for applicability review',async()=>{
 const s=setup();assert.equal(await s.eval("openDraftReaderCheck(run,'v2')"),true);
 const original=s.value('wt.form.importMaterials');
 await s.eval("wtClick({target:{closest:()=>({dataset:{wt:'input-mode',value:'paste'}})}})");
 s.eval("wt.form.text='另外一篇手工输入的正文'");
 assert.equal(s.eval('wt.form.inputMode'),'paste');assert.equal(s.eval('wt.form.bridge'),null);
 assert.deepEqual(s.value('wt.form.importMaterials'),original);
 assert.match(s.eval('wt.message'),/确认它们适用于当前正文/);
 const preview=s.eval('wtImportMaterialsPreview()');
 assert.match(preview,/创作时保存的材料，不代表已经核实/);assert.match(preview,/doc-1.*v2.*页 3.*位置 40.*kb-source/);
 assert.equal(s.eval("calls.filter(c=>c.method==='POST').length"),0);
});

test('real AI is the default while the explicit fictional example stays free simulation',async()=>{
 const s=setup();assert.equal(s.eval('wtFreshForm().mode'),'live');
 s.eval('wt.form=wtFreshForm()');assert.match(s.eval('wtNotice()'),/真实 AI.*计费/);
 await s.eval("wtClick({target:{closest(){return {dataset:{wt:'example'}};}}})");
 assert.equal(s.eval('wt.form.mode'),'simulation');assert.match(s.eval('wtNotice()'),/开发模拟/);
});
