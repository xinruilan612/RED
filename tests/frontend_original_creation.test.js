'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync('frontend/app.js','utf8'),knowledge=fs.readFileSync('frontend/knowledge.js','utf8');
function setup(){
 const fields={},sandbox={$:id=>fields[id],esc:v=>String(v??'').replace(/</g,'&lt;').replace(/>/g,'&gt;'),URL,api:async()=>({domains:{beauty:{label:'美妆'},photography:{label:'摄影'},digital:{label:'数码'}}})};
 vm.createContext(sandbox);
 vm.runInContext(app.slice(app.indexOf('async function creationRequest('),app.indexOf('function renderDraft(')),sandbox);
 vm.runInContext(knowledge.slice(knowledge.indexOf('async function documentClassificationRequest(')),sandbox);
 return {fields,sandbox,eval:code=>vm.runInContext(code,sandbox)};
}
test('creation request sends explicit domain/form goals but preserves blank automatic classification',async()=>{
 const s=setup();assert.deepEqual(JSON.parse(JSON.stringify(await s.eval('creationRequest()'))),{channel:'xiaohongshu'});
 Object.assign(s.fields,{creationDomains:{value:'数码、摄影,数码'},creationFormat:{value:'video_script'},creationGoal:{value:'  选购比较  '},creationWordCount:{value:'300'}});
 assert.deepEqual(JSON.parse(JSON.stringify(await s.eval('creationRequest()'))),{channel:'xiaohongshu',domains:['digital','photography'],format:'video_script',goal:'选购比较',word_count:300});
 assert.match(app,/api\('\/api\/runs','POST',\{creation:await creationRequest\(\)/);
});
test('knowledge classification retains purpose and optional scope in actual save',async()=>{
 const s=setup();Object.assign(s.fields,{documentDomains:{value:'美妆，摄影'},documentMaterialType:{value:'example'},documentChannel:{value:'xiaohongshu'},documentFormat:{value:'note'}});
 assert.deepEqual(JSON.parse(JSON.stringify(await s.eval('documentClassificationRequest()'))),{material_type:'example',domains:['beauty','photography'],channel:'xiaohongshu',format:'note'});
 assert.match(knowledge,/data.classification=await documentClassificationRequest\(\)/);
});
test('grouped reference report exposes exact conditions IDs and gap without inserting instructions as HTML',()=>{
 const s=setup();s.sandbox.input={creation_classification:{domains:['digital'],channel:'xiaohongshu',format:'video_script'},creation_retrieval:{engine:'vector+rerank',filters:{examples:{domains:['digital'],format:'video_script'}},groups:{methods:[{source_id:'method:1',text:'<script>bad</script>'}],examples:[],facts:[{source_id:'fact:2',text:'产品重量 80g'}]},gaps:['缺少匹配样例']}};
 const html=s.eval('creationReferenceHTML(input)');for(const expected of ['digital','短视频口播','实际检索条件','video_script','method:1','fact:2','缺少匹配样例','无匹配材料','产品重量 80g'])assert.ok(html.includes(expected),expected);
 assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
});
test('draft grouping uses frozen call not current run classification',async()=>{
 const s=setup();s.sandbox.draft={ref:'d',actor:'content',snapshot_id:'old',content:{body:'原稿'}};s.sandbox.run={events:[],reviews:[],context:{creation_classification:{domains:['WRONG_CURRENT']}},node_runs:[{id:'n',agent:'content',stage:'body',mode:'live',snapshot_id:'old',output:{body:'原稿'},input:{creation_classification:{domains:['beauty'],format:'note'},creation_retrieval:{groups:{examples:[{source_id:'frozen-example'}]},filters:{},gaps:[]}}}]};
 const html=s.eval('draftEvidenceHTML(draft)');assert.match(html,/beauty|frozen-example/);assert.doesNotMatch(html,/WRONG_CURRENT/);
});
test('unclassified default facts preserve automatic inference while unscoped examples fail visibly',async()=>{
 const s=setup();assert.equal(await s.eval('documentClassificationRequest()'),undefined);
 s.fields.documentMaterialType={value:'example'};await assert.rejects(s.eval('documentClassificationRequest()'),/所属领域/);
});
test('actual runtime direct groups resolve fact text and sample indices from frozen input only',()=>{
 const s=setup();s.sandbox.draft={ref:'d',actor:'content',snapshot_id:'old',content:{body:'原稿'}};
 const input={creation_classification:{domains:['digital'],format:'note'},creation_retrieval:{methods:[{source_id:'m',text:'通用方法'}],examples:[{source_id:'e',version:2,text:'真实样例正文'}],facts:[{source_id:'f',version:3}],engine:'dense',filters:{examples:{format:'note'}},gaps:[]},materials:[{source_id:'f',version:3,text:'真实事实正文'}],retrieved_references:[{source_id:'e',version:2}]};
 s.sandbox.run={events:[],context:{material:'错误当前材料'},node_runs:[{id:'n',agent:'content',stage:'body',mode:'live',snapshot_id:'old',output:{body:'原稿'},input}],review:{draft_ref:'d',snapshot_id:'old',claim_map:[],reference_records:{groups:{examples:['e']},adoption_notes:['采用 e 的对比结构'],scope:'仅验证本任务引文'}}};
 const html=s.eval('draftEvidenceHTML(draft)');for(const expected of ['通用方法','真实样例正文','真实事实正文','采用 e 的对比结构','不等于全部采用','仅验证本任务引文','dense'])assert.ok(html.includes(expected),expected);
 assert.doesNotMatch(html,/错误当前材料|历史记录未保存正文|未记录逐项表达借鉴/);
});
test('existing research cases expose classification editing and save a scoped version without modifying provenance',async()=>{
 const s=setup(),calls=[];Object.assign(s.sandbox,{classificationEdit:1,activeAccountId:'a',currentPage:'library',toast(){},error(e){throw e;},renderLibrary:async()=>calls.push(['refresh']),api:async(...args)=>{calls.push(args);return args[0]==='/api/creation/taxonomy'?{domains:{beauty:{label:'美妆'}}}:{};}});
 Object.assign(s.fields,{classificationDomains:{value:'美妆'},classificationMaterialType:{value:'example'},classificationChannel:{value:'xiaohongshu'},classificationFormat:{value:'video_script'}});
 s.sandbox.event={preventDefault(){},submitter:{disabled:false}};s.sandbox.doc={id:'research/case',version:7,source_type:'research_case',source_url:'https://example.com',text:'Do not send original body'};
 await s.eval("saveDocumentClassification(event,doc,'a',1)");
 const request=calls.find(c=>c[1]==='POST');assert.equal(request[0],'/api/knowledge/research%2Fcase/classification');
 assert.deepEqual(JSON.parse(JSON.stringify(request[2])),{account_id:'a',version:7,classification:{domains:['beauty'],material_type:'example',channel:'xiaohongshu',format:'video_script'}});
 assert.ok(calls.some(c=>c[0]==='refresh'));assert.equal(s.sandbox.event.submitter.disabled,false);assert.match(knowledge,/data-classify-document/);
});
test('a classification request cannot post after account changes during taxonomy lookup',async()=>{
 const s=setup(),calls=[];Object.assign(s.sandbox,{classificationEdit:1,activeAccountId:'a',currentPage:'library',error(e){throw e;},api:async(...args)=>{calls.push(args);s.sandbox.activeAccountId='b';return {domains:{beauty:{label:'美妆'}}};}});
 Object.assign(s.fields,{classificationDomains:{value:'美妆'},classificationMaterialType:{value:'example'},classificationChannel:{value:'xiaohongshu'},classificationFormat:{value:'note'}});
 s.sandbox.event={preventDefault(){},submitter:{disabled:false}};s.sandbox.doc={id:'d',version:1};await s.eval("saveDocumentClassification(event,doc,'a',1)");assert.equal(calls.some(c=>c[1]==='POST'),false);assert.equal(s.sandbox.event.submitter.disabled,false);
});
test('run heading uses actual content form instead of always claiming a note',()=>{
 const line=app.split('\n').find(l=>l.includes("$('runSummary').textContent="));assert.match(line,/creation_classification\?\.format/);assert.match(line,/video_script:'短视频口播'/);assert.match(line,/product_detail:'商品详情'/);
});
