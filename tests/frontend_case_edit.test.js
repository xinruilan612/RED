'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const els=new Map(),calls=[];
 function element(id){
  if(!els.has(id)){
   let value='';const el={textContent:'',innerHTML:'',checked:false,hidden:false,open:false,scrollIntoView(){},reset(){for(const node of els.values()){node.value='';node.checked=false;}}};
   Object.defineProperty(el,'value',{get:()=>value,set:v=>{value=String(v);},enumerable:true});els.set(id,el);
  }
  return els.get(id);
 }
 const sandbox={pageInfo:{},crypto:require('node:crypto'),URL,currentPage:'research',activeAccountId:'mine',$:element,
  esc:v=>String(v??''),badge:v=>v,dateText:v=>v,document:{querySelectorAll:()=>[]},clearTimeout(){},setTimeout(){},
  api:async(...args)=>{calls.push(args);return [];},error(){}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/research.js','utf8'),sandbox);
 return {sandbox,element,calls,eval:code=>vm.runInContext(code,sandbox)};
}
function fixture(){
 const text='开头💄保湿护肤的表达参考，正文保留且不重复。',chars=Array.from(text);
 return {id:'case-1',title:'<我的案例>',version:4,source_type:'research_case',source_url:'https://example.com/item?q=1',
  chunks:[{page:1,offset:5,text:chars.slice(5).join('')},{page:1,offset:0,text:chars.slice(0,12).join('')}],
  metadata:{research_case:{platform:'xiaohongshu',author:'作者',content_kind:'lead',evidence_role:'expression_reference',
   published_at:'2026-01-01T03:04:05.123456+00:00',observed_at:'2026-01-02T08:09:10.654321+00:00',
   metrics:{views:null,likes:0,favorites:22,comments:null,shares:5},assessment:{policy:{min_interactions:55,max_age_days:90}}}},text};
}
test('edit preserves evidence category, URL, policy, null metrics and exact original timestamps',()=>{
 const s=setup(),doc=fixture();s.sandbox.doc=doc;s.eval("fillCaseEditor(doc,'mine')");
 assert.equal(s.element('caseText').value,doc.text);assert.equal(s.element('caseMetric-views').value,'');assert.equal(s.element('caseMetric-likes').value,'0');
 assert.equal(s.element('casePermission').checked,false);assert.equal(s.element('caseCancelEdit').hidden,false);assert.equal(s.element('caseEditorDetails').open,true);
 s.element('casePermission').checked=true;
 const payload=JSON.parse(JSON.stringify(s.eval("researchCasePayload('mine')"))),c=doc.metadata.research_case;
 assert.equal(payload.document_id,doc.id);assert.equal(payload.expected_version,4);assert.equal(payload.source_url,doc.source_url);
 assert.equal(payload.published_at,c.published_at);assert.equal(payload.observed_at,c.observed_at);assert.equal(payload.author,c.author);
 assert.equal(payload.content_kind,'lead');assert.equal(payload.evidence_role,'expression_reference');assert.deepEqual(payload.metrics,c.metrics);
 assert.deepEqual(payload.policy,c.assessment.policy);assert.equal(payload.permission_confirmed,true);assert.equal(payload.text,doc.text);
});
test('body joins overlapping Unicode chunks without repetition and rejects missing pieces',()=>{
 const s=setup();s.sandbox.doc=fixture();assert.equal(s.eval('caseDocumentText(doc.chunks)'),s.sandbox.doc.text);
 assert.throws(()=>s.eval("caseDocumentText([{page:1,offset:5,text:'broken'}])"),/片段缺失/);
});
test('cancel editing clears version binding without sending requests',()=>{
 const s=setup();s.sandbox.doc=fixture();s.eval("fillCaseEditor(doc,'mine');clearCaseEditor()");
 assert.equal(s.eval('researchCaseEdit'),null);assert.equal(s.element('caseCancelEdit').hidden,true);
 assert.equal(s.element('caseEditorStatus').textContent,'');assert.equal(s.element('caseText').value,'');assert.equal(s.calls.length,0);
});
test('stale editor requests cannot fill another account or reopen after cancellation',async()=>{
 const s=setup();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);
 let pending=s.eval("editResearchCase('case-1','mine')");s.sandbox.activeAccountId='other';resolve(fixture());await pending;
 assert.equal(s.eval('researchCaseEdit'),null);
 s.sandbox.activeAccountId='mine';pending=s.eval("editResearchCase('case-1','mine')");s.eval('clearCaseEditor()');resolve(fixture());await pending;
 assert.equal(s.eval('researchCaseEdit'),null);
});
test('editing cannot submit its original case under a different project account',()=>{
 const s=setup();s.sandbox.doc=fixture();s.eval("fillCaseEditor(doc,'mine')");assert.throws(()=>s.eval("researchCasePayload('other')"),/账号已切换/);
});
