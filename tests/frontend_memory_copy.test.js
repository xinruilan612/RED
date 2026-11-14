'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(ops){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',hidden:false,onclick:null});return elements.get(id);};
 const sandbox={$:element,esc:value=>String(value??''),badge:text=>`<span class="pill">${text}</span>`,empty:(title,hint)=>`${title}|${hint}`,
  platformNames:{xiaohongshu:'小红书',douyin:'抖音'},accountRows:key=>(ops[key]||[]).filter(row=>row.account_id==='mine'),
  ops,location:{hash:''},clearError(){},window:{addEventListener(){}},
  document:{addEventListener(){},querySelectorAll(){return [];}}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/operations.js','utf8'),sandbox);
 return {sandbox,element,eval:code=>vm.runInContext(code,sandbox)};
}
function metrics(count){return Array.from({length:count},(_,i)=>({account_id:'mine',publication_id:'note-'+i}));}
test('memory page counts recorded works and asks for patience instead of blaming the data',()=>{
 const s=setup({publications:[],metrics:metrics(1),analyses:[],memories:[]});
 s.eval('renderMemory()');
 const html=s.element('operationsContent').innerHTML;
 assert.match(html,/已记录 1 篇 \/ 10 篇/);
 assert.match(html,/这条作品的指标已经保存/);
 assert.match(html,/等同类作品攒到 10 篇/);
 assert.doesNotMatch(html,/数据不足/);
});
test('memory page explains what ten comparable works unlock once a report exists',()=>{
 const s=setup({publications:[],metrics:metrics(3),analyses:[{account_id:'mine',status:'insufficient'}],memories:[]});
 s.eval('renderMemory()');
 const html=s.element('operationsContent').innerHTML;
 assert.match(html,/目前记录了 3 篇/);
 assert.match(html,/到 10 篇时/);
 assert.match(html,/栏目、标题长度、发布时机还是形式/);
});
test('memory page stops asking once the target is reached',()=>{
 const s=setup({publications:[],metrics:metrics(10),analyses:[],memories:[]});
 s.eval('renderMemory()');
 const html=s.element('operationsContent').innerHTML;
 assert.match(html,/够 10 篇了/);
 assert.match(html,/按表现分成两组/);
});
