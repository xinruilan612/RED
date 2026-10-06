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
