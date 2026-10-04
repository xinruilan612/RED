'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',hidden:true,options:[],insertAdjacentHTML(_pos,html){this.innerHTML+=html;}});return elements.get(id);};
 const s={pageInfo:{},activeAccountId:'a',currentPage:'library',run:null,creationSequence:0,$:element,toast:()=>{},error:e=>{s.lastError=e.message;},esc:v=>String(v).replaceAll('<','&lt;'),badge:()=>'',websiteSession:{auth_required:true},ops:{accounts:[]},showPage:page=>{s.currentPage=page;},api:async()=>{throw new Error('不能读取本机、内网或保留网络地址');},startCreation:()=>{s.creationSequence++;s.currentPage='studio';return true;},refreshMaterialDocuments:async()=>{},document:{querySelectorAll:()=>[]}};
 vm.createContext(s);vm.runInContext(fs.readFileSync('frontend/knowledge.js','utf8'),s);return {s,element};
}
test('library creation waits for refresh and selects only the requested document without paid work',async()=>{
 const {s,element}=setup();let finish;
 s.refreshMaterialDocuments=()=>new Promise(resolve=>{finish=()=>{element('materialDocumentSelect').options=[{value:'old',selected:true},{value:'target',selected:false}];resolve();};});
 const pending=s.createFromLibrary('target','a');finish();await pending;
 assert.deepEqual(element('materialDocumentSelect').options.map(o=>o.selected),[false,true]);
 assert.equal(element('useKnowledge').checked,true);assert.equal(element('materialFileBox').open,true);
});
for(const change of ['account','new creation','page','run'])test('late library selection cannot overwrite '+change,async()=>{
 const {s,element}=setup();let finish;s.refreshMaterialDocuments=()=>new Promise(resolve=>{finish=resolve;});
 element('materialDocumentSelect').options=[{value:'target',selected:false}];
 const pending=s.createFromLibrary('target','a');
 if(change==='account')s.activeAccountId='b';if(change==='new creation')s.creationSequence++;if(change==='page')s.currentPage='library';if(change==='run')s.run={run_id:'new'};
 finish();await pending;assert.equal(element('materialDocumentSelect').options[0].selected,false);
});
test('unavailable document does not enable knowledge or falsely report selection',async()=>{
 const {s,element}=setup();await s.createFromLibrary('deleted','a');assert.match(s.lastError,/已不可用/);assert.equal(element('useKnowledge').checked,undefined);
});
test('source import failure offers manual library fallback without retrying or bypassing address safety',async()=>{
 const {s,element}=setup();s.currentPage='trends';let calls=0;s.api=async()=>{calls++;throw new Error('不能读取本机、内网或保留网络地址');};
 s.mountSourceSearch();element('sourceUrl').value='https://example.com/product';const button={disabled:false,textContent:'读取正文并保存'};
 element('sourceUrlForm').onsubmit({preventDefault(){},submitter:button});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls,1);assert.equal(button.disabled,false);assert.match(element('sourceImportStatus').innerHTML,/不会自动重试/);assert.match(element('sourceImportStatus').innerHTML,/不能读取本机/);
 element('sourceManualFallback').onclick();assert.equal(s.currentPage,'library');
});
test('source import error from previous account does not replace new account screen',async()=>{
 const {s,element}=setup();s.currentPage='trends';let fail;s.api=()=>new Promise((_resolve,reject)=>{fail=reject;});s.mountSourceSearch();
 element('sourceUrlForm').onsubmit({preventDefault(){},submitter:{}});s.activeAccountId='b';element('sourceImportStatus').innerHTML='new account';fail(new Error('old error'));await new Promise(resolve=>setImmediate(resolve));assert.equal(element('sourceImportStatus').innerHTML,'new account');
});
