'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const els=new Map(),calls=[],fills=[];let reads=0;
 const element=id=>{if(!els.has(id))els.set(id,{value:'',checked:false,disabled:false,textContent:'',innerHTML:'',files:[]});return els.get(id);};
 class Reader{readAsDataURL(){reads++;this.result='data:audio/wav;base64,YWJj';this.onload();}}
 const sandbox={pageInfo:{},crypto:require('node:crypto'),URL,FileReader:Reader,currentPage:'research',activeAccountId:'mine',$:element,
  esc:v=>String(v??''),badge:v=>v,dateText:v=>v,document:{querySelectorAll:()=>[]},clearTimeout(){},setTimeout(){},api:async(...args)=>{calls.push(args);return doc();}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/research.js','utf8'),sandbox);
 sandbox.fillCaseEditor=(d,a)=>fills.push({d,a});sandbox.refreshResearchJobs=async()=>{};
 element('transcriptTitle').value='我的媒体';element('transcriptFile').files=[{name:'sample.WAV',size:1024}];element('transcriptPermission').checked=true;
 sandbox.event={preventDefault(){},submitter:element('transcriptSubmit')};
 return {sandbox,element,calls,fills,reads:()=>reads,eval:code=>vm.runInContext(code,sandbox)};
}
function doc(){return {id:'pending',source_type:'research_case',version:1,title:'转写',metadata:{research_case:{review_required:true,content_kind:'transcript',assessment:{status:'high_interaction_candidate'}}}};}
test('valid media uploads exact API fields and previews pending transcript without auto-save',async()=>{
 const s=setup();await s.eval("submitTranscript(event,'mine',0)");
 assert.equal(s.calls.length,1);assert.equal(s.calls[0][0],'/api/research/transcripts');
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0][2])),{account_id:'mine',title:'我的媒体',filename:'sample.WAV',file_base64:'YWJj',permission_confirmed:true});
 assert.equal(s.fills.length,1);assert.equal(s.fills[0].d.metadata.research_case.review_required,true);
 assert.match(s.element('transcriptStatus').textContent,/尚不参与检索/);assert.equal(s.element('transcriptSubmit').disabled,false);
 assert.equal(s.element('transcriptFile').files.length,1);
});
test('oversized media and unconfirmed permission never read file or call server',async()=>{
 for(const invalid of ['size','permission','type']){
  const s=setup();if(invalid==='size')s.element('transcriptFile').files[0].size=10*1024*1024+1;
  if(invalid==='permission')s.element('transcriptPermission').checked=false;
  if(invalid==='type')s.element('transcriptFile').files[0].name='payload.html';
  await s.eval("submitTranscript(event,'mine',0)");assert.equal(s.calls.length,0);assert.equal(s.reads(),0);assert.equal(s.element('transcriptSubmit').disabled,false);
 }
});
test('failed transcription keeps file selection and restores submit',async()=>{
 const s=setup();s.sandbox.api=async()=>{throw Error('时长超过120秒');};await s.eval("submitTranscript(event,'mine',0)");
 assert.match(s.element('transcriptStatus').textContent,/120秒/);assert.equal(s.fills.length,0);assert.equal(s.element('transcriptFile').files[0].name,'sample.WAV');assert.equal(s.element('transcriptSubmit').disabled,false);
});
test('result arriving after account switch does not replace an editor or update status',async()=>{
 const s=setup();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);
 const pending=s.eval("submitTranscript(event,'mine',0)");await Promise.resolve();const before=s.element('transcriptStatus').textContent;s.sandbox.activeAccountId='other';resolve(doc());await pending;
 assert.equal(s.fills.length,0);assert.equal(s.element('transcriptStatus').textContent,before);
});
test('in-progress uploads cannot be duplicated and newer case edits are preserved',async()=>{
 const s=setup();let resolve,count=0;s.sandbox.api=()=>{count++;return new Promise(r=>resolve=r);};
 const pending=s.eval("submitTranscript(event,'mine',0)");await Promise.resolve();await s.eval("submitTranscript(event,'mine',0)");s.eval('++caseEditLoad');resolve(doc());await pending;
 assert.equal(count,1);assert.equal(s.fills.length,0);assert.match(s.element('transcriptStatus').textContent,/未被覆盖/);
});
test('pending transcript label overrides popularity and does not claim automatic RAG',()=>{
 const s=setup();s.sandbox.d=doc();const html=s.eval('caseCards([d])');assert.match(html,/转写待校对 · 暂不参与检索/);assert.doesNotMatch(html,/高互动候选/);
});
