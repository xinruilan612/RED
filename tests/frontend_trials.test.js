'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){const context=vm.createContext({pageInfo:{},dateInput:()=> '2026-10-04T14:00',esc:value=>String(value??'').replace(/[<>]/g,c=>c==='<'?'&lt;':'&gt;'),activeAccountId:'mine'});vm.runInContext(fs.readFileSync('frontend/trials.js','utf8'),context);return code=>vm.runInContext(code,context);}
test('trial offers existing real drafts and excludes simulation or another account after list filtering',()=>{
 const run=setup();run(`trialRuns=[{run_id:'existing',workflow_type:'creation',context:{mode:'live',operations:{account_id:'mine'}},drafts:[{ref:'v1',content:{selected_title:'<unsafe>'}}]},{run_id:'demo',workflow_type:'creation',context:{mode:'simulation',operations:{account_id:'mine'}},drafts:[{ref:'v1',content:{selected_title:'demo'}}]}].filter(trialRunBelongs)`);
 const html=run("trialDraftOptions({id:'new-hypothesis'})");assert.match(html,/existing\|v1/);assert.doesNotMatch(html,/demo\|v1/);assert.match(html,/&lt;unsafe&gt;/);
});
test('reader form records real individual answers and does not ask users to invent aggregate numbers',()=>{
 const run=setup();const html=run("trialReaderForm({id:'h',desired_action:'收藏教程'})");assert.match(html,/data-reader-rows/);assert.match(html,/reader_question/);assert.match(html,/下载 A\/B/);assert.match(html,/不要替读者回答/);assert.doesNotMatch(html,/name="(?:denominator|outcomes)_/);
 const row=run("trialReaderRow(1,'B')");assert.match(row,/data-reader-understood required/);assert.match(row,/data-reader-answer/);assert.match(row,/value="B" selected/);
});

test('attribution labels use frozen arm identity when two runs share a ref',()=>{
 const run=setup();run(`badge=t=>String(t);accountRows=()=>[];h={id:'h',status:'awaiting_review',objective:'audience_growth',metric:'new_followers',signal_refs:[],validations:{small_race:{arms:[{label:'A',run_id:'first',draft_ref:'same',denominator:2,outcomes:1},{label:'B',run_id:'second',draft_ref:'same',denominator:2,outcomes:2}]},live_attribution:{items:[{label:'B',run_id:'second',draft_ref:'same',rate:.5}]}}}`);
 assert.match(run('trialHypothesisCard(h)'),/B 50\.00%/);
});

test('empty trial choices explain how to prepare a pair and where to record published data',()=>{
 const run=setup();run(`badge=t=>String(t);accountRows=()=>[];h={id:'h',status:'testing',objective:'audience_growth',metric:'new_followers',signal_refs:[],validations:{small_race:{arms:[]}}}`);
 assert.match(run('trialReaderForm(h)'),/无需重新生成两次/);
 assert.match(run('trialHypothesisCard(h)'),/href="#metrics"/);
 assert.match(run('trialHypothesisCard(h)'),/还没有可关联的发布数据/);
 assert.match(run("trialReaderRow(3,'A')"),/data-remove-reader/);
});

test('trial setup is progressive and existing reader work is shown before new setup',()=>{
 const run=setup();run(`badge=t=>String(t);currentAccount=()=>({name:'test'});empty=()=>'';output={innerHTML:''};$=()=>output;trialBind=()=>{};accountRows=()=>[];trialPaint()`);
 let html=run('output.innerHTML');assert.match(html,/<strong>选两份稿件<\/strong>/);assert.match(html,/<strong>记录读者反馈<\/strong>/);assert.match(html,/<strong>看结果<\/strong>/);
 assert.match(html,/<details class="trial-advanced"><summary>发布后比较设置/);
 assert.match(html,/<details class="trial-setup" open>/);
 run(`accountRows=kind=>kind==='hypotheses'?[{id:'h',status:'testing',statement:'改成步骤',validations:{},signal_refs:[]}]:[];trialPaint()`);
 html=run('output.innerHTML');assert.match(html,/<details class="trial-setup" >/);assert.ok(html.indexOf('开始试读')<html.indexOf('新建一次试读'));
 assert.ok(html.indexOf('1 · 选两份稿件')<html.indexOf('可选 · 先让 AI'));
});

test('reader result shows counts prominently without pretending small feedback proves growth',()=>{
 const run=setup();const html=run(`trialReaderSummary({desired_action:'了解产品',validations:{small_race:{arms:[{label:'A',denominator:2,outcomes:1},{label:'B',denominator:3,outcomes:2}],comprehension:{A:{understood:1},B:{understood:3}}}}})`);
 assert.match(html,/3 · 试读结果/);assert.match(html,/3 人看懂 · 2 人愿意了解产品/);assert.match(html,/不能证明发布后会涨粉或成交/);
 assert.equal(run('trialReaderSummary({validations:{}})'), '');
});


test('cold start explains the real first step and reuses audience without inventing signals',()=>{
 const run=setup();run(`badge=t=>String(t);currentAccount=()=>({name:'test',profile:{audience:'初学者'}});empty=()=>'';output={innerHTML:''};$=()=>output;trialBind=()=>{};accountRows=()=>[];trialPaint()`);
 const html=run('output.innerHTML');assert.match(html,/先请一位朋友看看原稿/);assert.match(html,/href="#studio"/);assert.match(html,/name="audience"[^>]*value="初学者"/);assert.doesNotMatch(html,/name="signal_ids" multiple/);
});
test('default pair chooses two different revisions of one work and never mixes topics',()=>{
 const run=setup();run(`trialRuns=[{run_id:'only',workflow_type:'creation',context:{mode:'live'},drafts:[{ref:'one',content_hash:'1'}]},{run_id:'pair',workflow_type:'creation',context:{mode:'live'},drafts:[{ref:'old',content_hash:'2'},{ref:'copy',content_hash:'2'},{ref:'new',content_hash:'3'}]}]`);
 assert.equal(run('JSON.stringify(trialDefaultPair().map(x=>x.run.run_id+"|"+x.draft.ref))'),'["pair|old","pair|new"]');
 run('trialRuns=trialRuns.map(r=>({...r,drafts:r.drafts.slice(0,1)}))');assert.equal(run('trialDefaultPair().length'),1);
});
test('download validates both versions and the shared question using local guidance',()=>{
 const run=setup();assert.match(run('trialReaderDownloadIssue([],"问题")'),/两份稿件/);
 assert.match(run('trialReaderDownloadIssue([{content_hash:"x"},{content_hash:"x"}],"问题")'),/内容相同/);
 assert.match(run('trialReaderDownloadIssue([{content_hash:"x"},{content_hash:"y"}],"   ")'),/理解问题/);
 assert.equal(run('trialReaderDownloadIssue([{content_hash:"x"},{content_hash:"y"}],"读完先做什么？")'),'');
 const html=run("trialReaderForm({id:'h',desired_action:'进一步了解'})");assert.match(html,/data-reader-message role="status" hidden/);assert.doesNotMatch(html,/style="/);
});


test('demo account cannot accidentally enter invented evidence as real reader feedback',()=>{
 const run=setup();run(`currentAccount=()=>({demo_sample:true});output={innerHTML:''};$=()=>output;trialPaint()`);
 const html=run('output.innerHTML');assert.match(html,/当前是虚构数据练习账号/);assert.match(html,/href="#examples"/);assert.doesNotMatch(html,/<form/);
});
