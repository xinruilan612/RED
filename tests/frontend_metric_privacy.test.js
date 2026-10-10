'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',value:'',addEventListener(){}});return elements.get(id);};
 const state={accounts:[{id:'mine'}],publications:[{id:'note-one',account_id:'mine',published_at:'2026-10-01',provenance:'manual',content:{selected_title:'真实作品'},url:'https://www.xiaohongshu.com/explore/one'}],metrics:[{id:'metric-one',account_id:'mine',publication_id:'note-one',window:'24h',revision:1,observed_at:'2026-10-02T10:00:00Z',source_type:'manual',values:{views:null,saves:0,impressions:17,new_followers:3,profile_visits:4}}],analyses:[]};
 const calls=[];
 const sandbox={localStorage:{getItem:()=> 'mine'},window:{addEventListener(){}},$:element,ops:state,
 esc:v=>String(v??'').replace(/</g,'&lt;'),dateText:v=>v,dateInput:()=> '2026-10-02T10:00',badge:v=>v,empty:(a,b)=>a+b,
 latestMetrics:()=>state.metrics,operate:async(...args)=>calls.push(args)};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/account.js','utf8'),sandbox);
 return {sandbox,element,calls,eval:code=>vm.runInContext(code,sandbox)};
}
test('manual observations identify their note and date without unavailable metric inputs or history mutation',()=>{
 const s=setup(),before=JSON.stringify(s.sandbox.ops);s.eval('renderMetrics()');const html=s.element('operationsContent').innerHTML;
 assert.match(html,/真实作品/);assert.match(html,/作品 ID：note-one/);assert.match(html,/https:\/\/www.xiaohongshu.com\/explore\/one/);assert.match(html,/2026-10-02T10:00:00Z/);
 assert.doesNotMatch(html,/metric-impressions|metric-new_followers|metric-profile_visits|更多指标/);assert.match(html,/<td>—<\/td><td>0<\/td>/);assert.equal(JSON.stringify(s.sandbox.ops),before);
});
test('saving manual observation sends absent metrics as null and keeps real zero',async()=>{
 const s=setup();s.eval('renderMetrics()');s.element('metricPost').value='note-one';s.element('metricWindow').value='24h';s.element('metricObserved').value='2026-10-02T10:00:00Z';s.element('metric-likes').value='0';
 await s.element('metricForm').onsubmit({preventDefault(){}});
 const [action,payload]=s.calls[0];assert.equal(action,'metrics');assert.equal(payload.id,'note-one');assert.equal(payload.likes,0);assert.equal(payload.views,null);assert.equal(payload.saves,null);assert.equal(payload.comments,null);assert.equal(payload.shares,null);assert.equal(payload.observed_at,'2026-10-02T10:00:00.000Z');assert.equal('impressions' in payload,false);
});
