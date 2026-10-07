'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const sandbox={pageInfo:{},setInterval(){},document:{querySelectorAll:()=>[]},window:{},activeAccountId:'a',crypto:{randomUUID:()=>Math.random().toString()}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/windtunnel.js','utf8'),sandbox);
 vm.runInContext(`wtPaint=()=>{};wtReadConditions=()=>wtCards();wt.account='a';wt.run={run_id:'r',status_version:1,allowed_actions:['confirm_conditions','edit_conditions'],windtunnel:{condition_sets:[{id:'s',hash:'h',conditions:[{id:'c',question:'先做什么？'}]}]}};wt.runs=[wt.run];calls=[];api=async(path,method,body)=>{calls.push({path,body});return {...wt.run,status_version:wt.run.status_version+1,allowed_actions:body.action==='edit_conditions'?['edit_conditions','confirm_conditions']:[],in_flight:body.action==='start'};};event={preventDefault(){},submitter:{value:'confirm'}};`,sandbox);
 return code=>vm.runInContext(code,sandbox);
}
test('confirm schedules the next check once using returned version and existing background endpoint',async()=>{
 const e=setup();await e('wtSaveConditions(event)');
 assert.deepEqual(JSON.parse(e('JSON.stringify(calls.map(x=>[x.path,x.body.action,x.body.version]))')),[['/api/runs/r/actions','confirm_conditions',1],['/api/runs/r/background','start',2]]);
 assert.equal(e('wt.tab'),'report');assert.match(e('wt.message'),/正在检查正文与材料/);
 await e('wtSaveConditions(event)');assert.equal(e('calls.length'),2);
});
test('changed questions save before confirmation and background start',async()=>{
 const e=setup();e("wtReadConditions=()=>[{id:'c',question:'下一步是什么？'}]");await e('wtSaveConditions(event)');
 assert.equal(e("calls.map(x=>x.body.action).join(',')"),'edit_conditions,confirm_conditions,start');
});
test('edit or confirmation failure never starts model work',async()=>{
 for(const changed of [false,true]){const e=setup();if(changed)e("wtReadConditions=()=>[{id:'c',question:'changed'}]");e("api=async(path,method,body)=>{calls.push({path,body});throw new Error('版本已变化，请刷新');}");await e('wtSaveConditions(event)');assert.equal(e('calls.length'),1);assert.match(e('wt.failure'),/版本已变化/);}
});
test('budget rejection preserves confirmed state without retrying or announcing work started',async()=>{
 const e=setup();e("const success=api;api=async(path,method,body)=>{if(body.action==='start'){calls.push({path,body});throw new Error('已达到本次用量上限');}return success(path,method,body)}");await e('wtSaveConditions(event)');
 assert.equal(e('calls.length'),2);assert.match(e('wt.failure'),/用量上限/);assert.match(e('wt.message'),/检查尚未启动/);
});
test('double click while confirm is pending does not create duplicate requests',async()=>{
 const e=setup();e("const success=api;let resume;api=async(...args)=>{await new Promise(resolve=>resume=resolve);return success(...args)};const first=wtSaveConditions(event)");await e('wtSaveConditions(event)');assert.equal(e('wt.busy'),true);e('resume()');await new Promise(resolve=>setImmediate(resolve));assert.equal(e('calls.length'),1);e('resume()');await e('first');assert.equal(e('calls.length'),2);
});
test('confirmation copy names its action and loading avoids internal jargon',()=>{
 const source=fs.readFileSync('frontend/windtunnel.js','utf8');assert.match(source,/确认问题并开始检查/);assert.doesNotMatch(source,/风洞记录/);
});
