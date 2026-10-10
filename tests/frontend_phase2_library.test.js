'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const elements=new Map(),calls=[];
 const element=id=>{if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',disabled:false,hidden:false});return elements.get(id);};
 const ctx={pageInfo:{},activeAccountId:'a',currentPage:'library',crypto:{randomUUID:()=>String(Math.random())},URL,Set,Map,
  esc:v=>String(v??''),api:async(...args)=>{calls.push(args);return {};},error(){},toast(){},$:element,
  document:{querySelectorAll:()=>[]},setTimeout(){}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('frontend/knowledge.js','utf8'),ctx);
 return {ctx,calls,element,run:s=>vm.runInContext(s,ctx)};
}
test('source capability uses attempt permission, not legacy ready or configuration',async()=>{
 const s=setup();s.element('ragProvider').options=['xhs_local','bing','baidu'].map(value=>({value}));s.element('ragProvider').value='xhs_local';s.element('ragProvider').onchange=()=>{};
 s.ctx.api=async url=>url.includes('/settings')?{providers:[{id:'bing',ready:false,can_attempt:true},{id:'baidu',ready:true,configured:true,can_attempt:false}]}:{bound:false};
 await s.run("loadRagCapabilities('a',0)");
 assert.equal(s.element('ragProvider').value,'bing');assert.equal(s.element('ragSearchButton').disabled,false);
 assert.equal(s.element('ragProvider').options[0].disabled,true);assert.equal(s.element('ragProvider').options[2].disabled,true);
 assert.match(s.element('ragProvider').options[1].textContent,/尚未核验/);
});
test('late capability response cannot overwrite another account',async()=>{
 const s=setup();s.element('ragProvider').value='keep';s.ctx.activeAccountId='other';
 await s.run("loadRagCapabilities('a',0)");assert.equal(s.element('ragProvider').value,'keep');
});
test('uncertain creation retry reuses key, different query and account get new keys',()=>{
 const s=setup();s.ctx.payload={queries:['白衬衫'],provider:'bing'};
 const one=s.run("ragSearchRequest('a',payload)"),two=s.run("ragSearchRequest('a',payload)"),other=s.run("ragSearchRequest('b',payload)");
 assert.equal(one.key,two.key);assert.notEqual(one.key,other.key);
 s.ctx.payload={queries:['棉衬衫'],provider:'bing'};assert.notEqual(one.key,s.run("ragSearchRequest('a',payload)").key);
});
test('JD scope is submitted without pretending a native shopping API',async()=>{
 const s=setup();for(const [id,value]of Object.entries({ragProvider:'bing',ragQuery:'白衬衫',ragTarget:'jd'}))s.element(id).value=value;
 s.ctx.api=async(...args)=>{s.calls.push(args);return args[0].includes('/jobs?')?[]:args[0].includes('/settings')?{providers:[{id:'bing',can_attempt:true}]}:{};};
 s.run("bindRagSearch('a',0)");await s.element('ragSearchForm').onsubmit({preventDefault(){},submitter:{disabled:false}});
 assert.equal(s.calls.find(c=>c[1]==='POST')[2].targets[0],'jd');
 assert.match(s.run('ragSearchPanel()'),/不是商城专用接口/);
});
