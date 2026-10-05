'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const nodes={},calls=[],notes=[];const node=id=>nodes[id]??=( {hidden:true,style:{},events:{},addEventListener(k,f){this.events[k]=f;},focus(){this.focused=true;}} );
 const c={busy:false,run:{run_id:'r1'},auto:false,editing:false,viewVersion:null,states:{SUCCEEDED:'已确认完成'},esc:String,$:node,dirtyGuard:()=>true,clearError(){},encodeURIComponent,toast:m=>notes.push(m),error:e=>{throw e;},window:{innerWidth:800,innerHeight:600,addEventListener(){}},document:{addEventListener(){}},api:async(path,method,body)=>{calls.push({path,method,body});return method==='POST'?{}:[{run_id:'r1',context:{topic:'洞洞板'},drafts:[],run_status:'SUCCEEDED'}];}};
 vm.createContext(c);const code=fs.readFileSync('frontend/app.js','utf8');vm.runInContext(code.slice(code.indexOf('let historyDeleted='),code.indexOf('function currentAgent()')),c);
 return {c,nodes,calls,notes,node};
}
test('right click targets its own record then deletes and clears selected workbench',async()=>{
 const s=setup(),button={dataset:{run:'r1',title:'洞洞板'}};let prevented=false;
 s.node('history').events.contextmenu({target:{closest:()=>button},preventDefault(){prevented=true;},clientX:790,clientY:590});
 assert.ok(prevented);assert.equal(s.node('historyContextMenu').hidden,false);assert.equal(s.node('historyContextMenu').style.left,'600px');
 await s.node('historyDelete').onclick();assert.equal(s.calls[0].path,'/api/runs/r1/visibility');assert.equal(s.calls[0].body.deleted,true);
 assert.equal(s.c.run,null);assert.equal(s.node('welcome').hidden,false);assert.equal(s.notes.length,0);
});
test('deleted list restores instead of deleting again',async()=>{
 const s=setup();await s.node('historyTrash').onclick();assert.equal(s.calls[0].path,'/api/runs?deleted=true');
 s.c.openHistoryMenu({dataset:{run:'r1',title:'洞洞板'}},10,20);assert.equal(s.node('historyDelete').textContent,'恢复这条创作');
 await s.node('historyDelete').onclick();assert.equal(s.calls[1].body.deleted,false);
});
test('deleting another record does not discard current draft',async()=>{
 const s=setup();s.c.openHistoryMenu({dataset:{run:'r2',title:'其他'}},10,20);await s.node('historyDelete').onclick();assert.equal(s.c.run.run_id,'r1');
});
