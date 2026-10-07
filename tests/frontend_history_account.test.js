'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const elements=new Map(),listeners={};const get=id=>{if(!elements.has(id))elements.set(id,{hidden:false,value:'',textContent:'',innerHTML:'',addEventListener(){}});return elements.get(id);};
 const context=vm.createContext({document:{getElementById:get,addEventListener(k,fn){listeners[k]=fn;},querySelectorAll(){return [];}},window:{addEventListener(){}},setInterval(){},setTimeout(){},clearTimeout(){},crypto:{randomUUID:()=> 'key'}});
 vm.runInContext(fs.readFileSync('frontend/app.js','utf8'),context);
 return {get,listeners,run:s=>vm.runInContext(s,context)};
}
test('refresh initializes saved account before listing or rendering any creation',async()=>{
 const s=setup();s.run(`order=[];api=async path=>{order.push(path);return {csrf:'x',provider:{ready:false,message:'test'}}};showWebsiteUser=()=>{};renderMode=()=>{};render=()=>order.push('render');currentAgent=()=>null;history=async()=>{order.push('history');return []};initOperations=async()=>{order.push('accounts');return []};`);
 await s.listeners.DOMContentLoaded();assert.equal(s.run("JSON.stringify(order)"),'["/api/session","accounts"]');
});
test('uninitialized accounts never match all history, and demo excludes real account runs',()=>{
 const s=setup();s.run(fs.readFileSync('frontend/account.js','utf8').split('\n').find(l=>l.startsWith('function matchesAccount(')));
 s.run('currentAccount=()=>null');assert.equal(s.run("matchesAccount({context:{operations:{account_id:'real'}}})"),false);
 s.run("currentAccount=()=>({id:'demo',platform:'xiaohongshu',aliases:['示例账号']})");
 assert.equal(s.run("matchesAccount({context:{operations:{account_id:'real'}}})"),false);
 assert.equal(s.run("matchesAccount({context:{operations:{account_id:'demo'}}})"),true);
});
test('a history response from before an account switch cannot repaint the new account sidebar',async()=>{
 const s=setup();s.run("activeAccountId='real';matchesAccount=()=>true;api=()=>new Promise(resolve=>{finish=resolve})");
 const pending=s.run('history()');s.run("activeAccountId='demo';finish([{run_id:'real',context:{topic:'真实稿'},drafts:[]}])");
 await pending;assert.equal(s.get('history').innerHTML,'');
});

test('operations initialization returns only history selected after account synchronization',async()=>{
 const s=setup();s.run(fs.readFileSync('frontend/operations.js','utf8').split('\n').find(l=>l.startsWith('async function initOperations(')));
 s.run("location={hash:'#trials'};ops=null;order=[];api=async()=>{order.push('load accounts');return {accounts:[{id:'demo'}]}};syncAccounts=()=>{order.push('select demo')};showPage=p=>order.push(p);history=async()=>{order.push('filtered history');return [{run_id:'demo-only'}]}");
 const rows=await s.run('initOperations()');assert.equal(rows[0].run_id,'demo-only');assert.equal(s.run('JSON.stringify(order)'),'["load accounts","select demo","trials","filtered history"]');
});
