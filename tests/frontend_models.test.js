'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',elements:{},value:'',disabled:false});return elements.get(id);};
 const calls=[];
 const sandbox={pageInfo:{},URL,currentPage:'connections',activeAccountId:'mine',$:element,
  esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  document:{querySelectorAll:()=>[]},window:{confirm:()=>false},dateText:v=>v,toast(){},error(){},clearError(){},refreshModelStatus:async()=>{},
  api:async(...args)=>{calls.push(args);return {};}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/connections.js','utf8'),sandbox);vm.runInContext(fs.readFileSync('frontend/models.js','utf8'),sandbox);
 return {sandbox,element,calls,eval:code=>vm.runInContext(code,sandbox)};
}
test('model form never echoes credentials returned by a server',()=>{
 const s=setup();const html=s.eval("modelConnectionForm([{id:'vendor',name:'厂商',base_url:'https://example.com',docs:'https://example.com'}],{api_key:'LEAK',label:'<script>'})");
 assert.doesNotMatch(html,/LEAK|<script>/);assert.match(html,/type="password"/);assert.match(html,/https:\/\/example.com/);
});
test('cancelled paid test sends no request',async()=>{
 const s=setup();await s.eval("testModelConnection({id:'id',label:'test',version:2})");assert.equal(s.calls.length,0);
});
test('confirmed paid test binds version and cost acknowledgement',async()=>{
 const s=setup();s.sandbox.window.confirm=()=>true;await s.eval("testModelConnection({id:'a/b',label:'test',version:2})");
 assert.equal(s.calls[0][0],'/api/models/connections/a%2Fb/test');assert.equal(s.calls[0][2].version,2);assert.equal(s.calls[0][2].acknowledge_cost,true);
});
test('saving an existing model omits blank key and retains optimistic version',async()=>{
 const s=setup(),fields={id:'saved',version:'3',provider:'vendor',label:'name',model:'model',base_url:'https://example.com',api_key:'',rate_usd_per_million:'2',run_budget_usd:'1',day_budget_usd:'5'};
 const form=s.element('modelConnectionForm');form.elements=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,{value:v}]));
 s.eval('bindModelForm([])');await form.onsubmit({preventDefault(){}});
 assert.equal(s.calls[0][0],'/api/models/connections');assert.equal(s.calls[0][2].version,3);assert.equal(s.calls[0][2].rate_usd_per_million,2);assert.equal('api_key' in s.calls[0][2],false);
});
test('successful save clears key input',async()=>{
 const s=setup(),fields={id:'',version:'',provider:'vendor',label:'name',model:'model',base_url:'https://example.com',api_key:'PRIVATE',rate_usd_per_million:'2',run_budget_usd:'1',day_budget_usd:'5'};
 const form=s.element('modelConnectionForm');form.elements=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,{value:v}]));s.eval('bindModelForm([])');await form.onsubmit({preventDefault(){}});assert.equal(form.elements.api_key.value,'');
});
