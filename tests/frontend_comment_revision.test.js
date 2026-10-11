'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const elements=new Map(),windowListeners={};
 const element=id=>{if(!elements.has(id))elements.set(id,{value:'',hidden:true,checked:false,disabled:false,innerHTML:'',textContent:'',selectedOptions:[],listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},scrollIntoView(){},insertAdjacentHTML(_where,text){this.innerHTML+=text;}});return elements.get(id);};
 const sandbox={document:{getElementById:element,querySelectorAll:()=>[],addEventListener(){}},window:{addEventListener(name,fn){windowListeners[name]=fn;}},setInterval(){},setTimeout(){},clearTimeout(){},crypto:{randomUUID:()=>String(Math.random())},websiteSession:{auth_required:true},URL,accountId:'a',currentAccount(){return {id:sandbox.accountId};}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/app.js','utf8'),sandbox);
 const evaluate=code=>vm.runInContext(code,sandbox);
 const originalApi=evaluate('api');
 evaluate(`calls=[];render=()=>{};history=async()=>[];chosenTrend=null;creationRequest=async()=>({channel:'xiaohongshu',domains:['beauty'],format:'note'});api=async(path,method,body)=>{calls.push({path,method,body});return run;};run={run_id:'r',mode:'live',status_version:4,snapshot_id:'s',context:{topic:'主题'},drafts:[{ref:'d',content_hash:'hash',content:{body:'旧稿'}}],allowed_actions:['request_revision'],in_flight:false};`);
 return {element,eval:evaluate,sandbox,originalApi,windowListeners};
}
test('comment input is opt-in and cannot submit a stale or empty note selection',()=>{
 const s=setup();assert.deepEqual(JSON.parse(s.eval('JSON.stringify(commentFeedbackRequest())')),{enabled:false});
 s.element('useCommentFeedback').checked=true;assert.throws(()=>s.eval('commentFeedbackRequest()'),/公开笔记/);
 s.eval("commentNotesAccount='a'");s.element('commentNoteSelect').selectedOptions=[{value:'public'}];
 assert.deepEqual(JSON.parse(s.eval('JSON.stringify(commentFeedbackRequest())')),{enabled:true,note_ids:['public']});
 s.sandbox.accountId='b';assert.throws(()=>s.eval('commentFeedbackRequest()'),/当前账号/);
});
test('picker renders only verified public identity and never raw comments',async()=>{
 const s=setup();s.element('useCommentFeedback').checked=true;
 s.eval("api=async()=>[{id:'n',title:'公开标题',visibility:'public',comments:[{content:'SECRET'}]},{id:'p',title:'PRIVATE',visibility:'private'},{id:'u',title:'UNKNOWN'}]");
 await s.eval('refreshCommentNotes()');const html=s.element('commentNoteSelect').innerHTML;
 assert.match(html,/公开标题/);assert.doesNotMatch(html,/SECRET|PRIVATE|UNKNOWN/);
});
test('late note response cannot repaint a different account or restore disabled selection',async()=>{
 const s=setup();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);s.element('useCommentFeedback').checked=true;
 const pending=s.eval('refreshCommentNotes()');s.sandbox.accountId='b';s.eval('resetCommentSelection()');resolve([{id:'old',title:'OLD',visibility:'public'}]);await pending;
 assert.equal(s.element('commentNoteSelect').innerHTML,'');assert.equal(s.element('useCommentFeedback').checked,false);
});
test('actual form submission retains creation classification and sends selected IDs not forged samples',async()=>{
 const s=setup();s.element('useCommentFeedback').checked=true;s.element('commentNoteSelect').selectedOptions=[{value:'n'}];s.eval("commentNotesAccount='a'");
 s.element('useKnowledge').checked=false;s.element('useAutomaticReferences').checked=false;s.element('mode').value='live';
 await s.element('briefForm').listeners.submit({preventDefault(){},submitter:{disabled:false}});
 const body=s.eval('calls[0].body');assert.deepEqual(JSON.parse(JSON.stringify(body.creation)),{channel:'xiaohongshu',domains:['beauty'],format:'note'});
 assert.deepEqual(JSON.parse(JSON.stringify(body.comment_feedback)),{enabled:true,note_ids:['n']});
 assert.equal(body.operations.account_id,'a');assert.equal(body.knowledge.automatic_references,false);
});
test('revision records bind the exact draft and are saved without starting a model',async()=>{
 const s=setup();s.element('revisionInstruction').value='更自然一点';s.element('revisionInstruction').listeners.input();
 await s.element('revisionRequestForm').onsubmit({preventDefault(){}});
 assert.equal(s.eval('calls.length'),1);assert.equal(s.eval('calls[0].body.action'),'request_revision');
 assert.deepEqual(JSON.parse(s.eval('JSON.stringify(calls[0].body.payload)')),{draft_ref:'d',content_hash:'hash',instruction:'更自然一点'});
 assert.equal(s.element('revisionInstruction').value,'');
});
test('editing request cannot silently target a newly arrived draft',async()=>{
 const s=setup();s.element('revisionInstruction').value='保留数字';s.element('revisionInstruction').listeners.input();s.eval("run.drafts=[{ref:'new',content_hash:'newhash'}]");
 await s.element('revisionRequestForm').onsubmit({preventDefault(){}});
 assert.equal(s.eval('calls.length'),0);assert.equal(s.element('revisionInstruction').value,'保留数字');assert.match(s.element('error').textContent,/稿件已变化/);
});
test('uncertain request retry reuses its original idempotency key',async()=>{
 const s=setup();s.eval("api=async(path,method,body)=>{if(method==='POST'){calls.push({path,body});throw Error('network lost');}return run;}");
 await s.eval("act('request_revision',{draft_ref:'d',content_hash:'hash',instruction:'改短'})");
 await s.eval("act('request_revision',{draft_ref:'d',content_hash:'hash',instruction:'改短'})");
 assert.equal(s.eval('calls.length'),2);assert.equal(s.eval('calls[0].body.key'),s.eval('calls[1].body.key'));
});
test('API errors retain server status and domain code for safe revision recovery',async()=>{
 const s=setup();s.sandbox.fetch=async()=>({ok:false,status:409,json:async()=>({error:{code:'VERSION_CONFLICT',message:'任务已更新'}})});
 await assert.rejects(()=>s.originalApi('/api/runs/r/actions','POST',{}),error=>error.status===409&&error.code==='VERSION_CONFLICT'&&error.message==='任务已更新');
});
test('definitively rejected revision can retry unchanged text using the refreshed version',async()=>{
 const s=setup();s.eval("api=async(path,method,body)=>{if(method==='POST'){calls.push({path,body});if(body.version!==5)throw Object.assign(Error('任务已更新'),{status:409,code:'VERSION_CONFLICT'});return run;}run.status_version=5;return run;}");
 const first=await s.eval("act('request_revision',{draft_ref:'d',content_hash:'hash',instruction:'改短'})");
 const second=await s.eval("act('request_revision',{draft_ref:'d',content_hash:'hash',instruction:'改短'})");
 assert.equal(first,false);assert.equal(second,true);
 assert.deepEqual(JSON.parse(s.eval('JSON.stringify(calls.map(c=>c.body.version))')),[4,5]);
 assert.notEqual(s.eval('calls[0].body.key'),s.eval('calls[1].body.key'));
 assert.equal(s.eval('calls[0].body.payload.instruction'),s.eval('calls[1].body.payload.instruction'));
});
test('ambiguous timeout or server failure preserves revision idempotency even after a refresh',async()=>{
 for(const status of [408,503]){
  const s=setup();s.sandbox.failureStatus=status;
  s.eval("api=async(path,method,body)=>{if(method==='POST'){calls.push({path,body});throw Object.assign(Error('结果未决'),{status:failureStatus});}run.status_version=5;return run;}");
  await s.eval("act('request_revision',{draft_ref:'d',content_hash:'hash',instruction:'改短'})");
  await s.eval("act('request_revision',{draft_ref:'d',content_hash:'hash',instruction:'改短'})");
  assert.deepEqual(JSON.parse(s.eval('JSON.stringify(calls.map(c=>c.body.version))')),[4,4]);
  assert.equal(s.eval('calls[0].body.key'),s.eval('calls[1].body.key'));
 }
});
test('viewing a historical draft blocks revisions and guides an explicit return to latest',async()=>{
 const s=setup();s.eval("run.drafts.push({ref:'new',content_hash:'newhash',content:{body:'新稿'}});renderDraft=()=>{}");
 s.element('versionSelect').onchange({target:{value:'0'}});
 assert.equal(s.element('revisionRequestForm').hidden,true);
 assert.match(s.element('revisionConversationHistory').innerHTML,/历史稿件.*最新版本/);
 s.element('revisionInstruction').value='正在看的旧稿改短';s.element('revisionInstruction').listeners.input();
 await s.element('revisionRequestForm').onsubmit({preventDefault(){}});
 assert.equal(s.eval('calls.length'),0);assert.match(s.element('error').textContent,/历史稿件/);
 s.element('versionSelect').onchange({target:{value:'1'}});
 assert.equal(s.element('revisionRequestForm').hidden,false);
 s.element('revisionInstruction').value='已阅读最新稿，改短';s.element('revisionInstruction').listeners.input();
 await s.element('revisionRequestForm').onsubmit({preventDefault(){}});
 assert.equal(s.eval('calls.length'),1);assert.equal(s.eval('calls[0].body.payload.draft_ref'),'new');
});
test('real account change handler blocks switching while creation classification is awaited',async()=>{
 const s=setup();s.eval("let activeAccountId='a',opsBusy=false;currentAccount=()=>({id:activeAccountId});dirtyGuard=()=>true;resetAccountWorkspace=()=>{throw Error('must not switch')};syncAccounts=()=>{throw Error('must not sync another account')}");
 const accountSource=fs.readFileSync('frontend/account.js','utf8');
 s.eval(accountSource.slice(accountSource.indexOf("$('activeAccount').onchange="),accountSource.indexOf("$('manageAccount').onclick=")));
 let resolve;s.sandbox.creationRequest=()=>new Promise(r=>resolve=r);
 s.element('topic').value='账号A的主题';s.element('material').value='账号A的素材';s.element('accountName').value='账号A';
 const pending=s.element('briefForm').listeners.submit({preventDefault(){},submitter:{disabled:false}});
 assert.equal(s.eval('busy'),true);
 const target={value:'b'};s.element('activeAccount').listeners.change();await s.element('activeAccount').onchange({target});
 assert.equal(target.value,'a');assert.equal(s.eval('activeAccountId'),'a');
 resolve({domains:['beauty'],channel:'xiaohongshu',format:'note'});await pending;
 assert.equal(s.eval('calls[0].body.operations.account_id'),'a');assert.equal(s.eval('calls[0].body.material'),'账号A的素材');
 assert.equal(s.eval('calls[0].body.topic'),'账号A的主题');
});
test('cancelling a task switch preserves unsaved revision text and the exact original binding',async()=>{
 const s=setup();s.sandbox.window.confirm=()=>false;
 s.element('revisionInstruction').value='这段要求还没保存';s.element('revisionInstruction').listeners.input();
 await s.element('history').listeners.click({target:{closest:()=>({dataset:{run:'other'}})}});
 assert.equal(s.eval('calls.length'),0);assert.equal(s.eval('run.run_id'),'r');
 assert.equal(s.element('revisionInstruction').value,'这段要求还没保存');
 assert.equal(s.eval('revisionBinding.draftRef'),'d');
});
test('explicitly confirming a task switch clears unsaved revision text only when leaving',async()=>{
 const s=setup();s.sandbox.window.confirm=()=>true;s.eval("showPage=()=>{};api=async(path)=>{calls.push({path});return {...run,run_id:'other'}}");
 s.element('revisionInstruction').value='确认放弃这段要求';s.element('revisionInstruction').listeners.input();
 await s.element('history').listeners.click({target:{closest:()=>({dataset:{run:'other'}})}});
 assert.equal(s.eval('calls.length'),1);assert.equal(s.eval('run.run_id'),'other');
 assert.equal(s.element('revisionInstruction').value,'');assert.equal(s.eval('revisionBinding'),null);
});
test('unsaved revision text protects browser unload without persisting it',()=>{
 const s=setup();let warned=false;
 s.element('revisionInstruction').value='关闭前尚未保存';
 const event={preventDefault(){warned=true;}};s.windowListeners.beforeunload(event);
 assert.equal(warned,true);assert.equal(event.returnValue,'');
 assert.equal(s.element('revisionInstruction').value,'关闭前尚未保存');
 s.element('revisionInstruction').value='';warned=false;s.windowListeners.beforeunload({preventDefault(){warned=true;}});
 assert.equal(warned,false);
});
test('feedback report shows traceable selected notes but not raw comment text',()=>{
 const s=setup();s.eval("run.context.comment_feedback={enabled:true,sample_size:1,frozen_at:'now',notes:[{note_id:'n',title:'标题'}],samples:[{text:'RAW_PRIVATE_CONTACT'}],limitation:'部分已取得样本'};run.context.revision_requests=[{instruction:'<script>',draft_ref:'d',status:'pending'}];renderFeedbackAndRevision()");
 assert.match(s.element('commentFeedbackSummary').innerHTML,/笔记 ID：n/);assert.doesNotMatch(s.element('commentFeedbackSummary').innerHTML,/RAW_PRIVATE_CONTACT/);
 assert.match(s.element('revisionConversationHistory').innerHTML,/&lt;script&gt;/);
});
