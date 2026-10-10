'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const file=fs.readFileSync('frontend/app.js','utf8');
const source=file.slice(file.indexOf('function draftEvidenceNode('),file.indexOf('function renderDraft('));
function setup(){
 const draft={ref:'draft-old',snapshot_id:'snapshot-old',actor:'content',content:{selected_title:'原标题',body:'旧稿事实'}};
 const material={source_id:'kb:old',version:2,title:'原始来源',url:'https://example.com/original',page:3,offset:24,fetched_at:'2026-10-01',text:'真正送入旧模型的片段'};
 const node={id:'node-old',agent:'content',stage:'body',mode:'live',snapshot_id:draft.snapshot_id,output:draft.content,input:{retrieved_references:[],materials:[material]}};
 const run={node_runs:[node],events:[],reviews:[],context:{evidence:[{source_id:'WRONG-CURRENT',text:'NEVER-SHOW-CURRENT'}]}};
 const sandbox={run,draft,URL,esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};vm.createContext(sandbox);vm.runInContext(source,sandbox);
 return {run,draft,node,material,html:()=>vm.runInContext('draftEvidenceHTML(draft)',sandbox),selected:()=>vm.runInContext('draftEvidenceNode(draft)',sandbox)};
}
test('old draft displays only frozen actual sent input with source metadata',()=>{
 const s=setup(),html=s.html();for(const value of ['查看本稿资料依据','kb:old','资料版本：2','页码：3','原文位置：24','2026-10-01','https://example.com/original','真正送入旧模型的片段','snapshot-old'])assert.ok(html.includes(value),value);
 assert.doesNotMatch(html,/WRONG-CURRENT|NEVER-SHOW-CURRENT/);assert.match(html,/送入模型不等于稿件实际引用/);assert.match(html,/实际引用未知/);
});
test('review citations must match selected draft and snapshot, not latest review',()=>{
 const s=setup();s.run.review={draft_ref:'another',snapshot_id:'snapshot-new',claim_map:[{excerpt:'WRONG',source_id:'WRONG'}]};s.run.reviews=[{draft_ref:'draft-old',snapshot_id:'snapshot-old',claim_map:[{excerpt:'旧稿事实',source_id:'kb:old',quote:'真实原文'}],learned_from:['kb:style 的分点结构'],limitations:['仅检查已取得来源']}];
 const html=s.html();assert.match(html,/稿件原文：旧稿事实/);assert.match(html,/真实原文/);assert.match(html,/kb:style 的分点结构/);assert.match(html,/仅检查已取得来源/);assert.doesNotMatch(html,/WRONG/);
});
test('ambiguous identical draft outputs stay unknown unless creation event binds exact call',()=>{
 const s=setup();s.run.node_runs.push({...s.node,id:'node-other',input:{materials:[{source_id:'other-call',text:'WRONG-INPUT'}],retrieved_references:[]}});
 assert.equal(s.selected(),null);assert.match(s.html(),/不能|未知/);assert.doesNotMatch(s.html(),/真正送入旧模型的片段|WRONG-INPUT/);
 s.run.events=[{type:'agent.completed',payload:{agent:'content',stage:'body',node_ref:'node-old'}},{type:'artifact.created',payload:{artifact_ref:'draft-old'}}];assert.equal(s.selected().id,'node-old');assert.match(s.html(),/真正送入旧模型的片段/);assert.doesNotMatch(s.html(),/WRONG-INPUT/);
});
test('manual and missing historical drafts do not inherit nearby creation inputs',()=>{
 const s=setup();s.draft.actor='user';assert.match(s.html(),/手动修改/);assert.doesNotMatch(s.html(),/真正送入旧模型的片段/);
 s.draft.actor='content';s.draft.snapshot_id='snapshot-missing';assert.match(s.html(),/资料依据未知/);assert.doesNotMatch(s.html(),/真正送入旧模型的片段|NEVER-SHOW-CURRENT/);
});
test('source text and links are safe and missing metadata remains explicitly unknown',()=>{
 const s=setup();s.material.url='javascript:alert(1)';s.material.text='<script>alert(1)</script>';delete s.material.page;delete s.material.offset;delete s.material.fetched_at;const html=s.html();assert.doesNotMatch(html,/href="javascript:|<script>/);assert.match(html,/&lt;script&gt;/);assert.match(html,/页码：未知/);assert.match(html,/原文位置：未知/);assert.match(html,/获取时间：未知/);
});
test('duplicate materials and references are shown once, empty known inputs differ from missing records',()=>{
 const s=setup();s.material.evidence_role='expression_reference';s.node.input.retrieved_references=[s.material];let html=s.html();assert.equal(html.split('真正送入旧模型的片段').length-1,1);assert.match(html,/表达参考：学习结构和方法/);
 s.node.input={materials:[],retrieved_references:[]};assert.match(s.html(),/本次调用未送入资料或表达参考/);s.node.input={};assert.match(s.html(),/历史调用缺少完整资料字段/);
});
