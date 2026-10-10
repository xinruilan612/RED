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
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/connections.js','utf8'),sandbox);
 return {sandbox,element,calls,eval:code=>vm.runInContext(code,sandbox)};
}
test('source links reject script URLs and escape source text',()=>{
 const s=setup();assert.equal(s.eval("connectionLink('javascript:alert(1)','<img>')"),'&lt;img&gt;');
 assert.match(s.eval("connectionLink('https://example.com','<img>')"),/noopener noreferrer/);
 assert.doesNotMatch(s.eval("connectionLink('https://example.com','<img>')"),/<img>/);
});
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
test('old account response cannot overwrite newly selected account',async()=>{
 const s=setup();const resolves=[];s.sandbox.api=()=>new Promise(r=>resolves.push(r));const pending=s.eval('renderConnections()');s.sandbox.activeAccountId='other';resolves.forEach(r=>r({account_name:'OLD'}));await pending;assert.doesNotMatch(s.element('operationsContent').innerHTML,/OLD/);
});
test('missing metrics stay absent and zero stays zero',()=>{
 const s=setup();s.sandbox.data={account_name:'<script>',connection_status:'not_connected',reason:'no',fields:[{key:'views',label:'阅读'},{key:'likes',label:'点赞'}],local_records:{publication_count:0,metric_snapshot_count:1,latest_metric:{observed_at:'now',window:'24h',values:{views:null,likes:0}}}};
 const html=s.eval('connectionOverview(data)');assert.match(html,/未记录/);assert.match(html,/<td>0<\/td>/);assert.match(html,/尚未连接平台/);assert.doesNotMatch(html,/<script>/);
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

test('sync observations escape text and mark missing metrics and partial comments',()=>{
 const s=setup();s.sandbox.sync={status:'synced',interval_s:900,counts:{note:1,comment:0},latest_round:{notes:[{url:'https://example.com',title:'<script>',text:'<img>',metrics:{likes:0},comments:[]}]}};
 const html=s.eval('syncOverview(sync)');assert.doesNotMatch(html,/<script>|<img>/);assert.match(html,/点赞 0/);assert.match(html,/收藏 未知/);assert.match(html,/非全量/);
});
test('stored note history is shown even when latest round omitted it',()=>{
 const s=setup();s.sandbox.sync={status:'synced',interval_s:900,counts:{note:1,comment:1},latest_round:{notes:[]}};
 s.sandbox.notes=[{id:'n',url:'https://example.com',title:'OLDER',text:'body',metrics:{}}];
 const html=s.eval('syncOverview(sync,notes)');assert.match(html,/OLDER/);assert.match(html,/data-note-comments="n"/);assert.match(html,/已保存评论/);
});
test('comment load escapes stored text and uses scoped read-only endpoint',async()=>{
 const s=setup();s.sandbox.button={disabled:false,nextElementSibling:{innerHTML:''}};
 s.sandbox.api=async url=>{s.calls.push([url]);return {items:[{content:'<script>',first_seen:1,last_seen:2}],next_offset:null};};
 await s.eval("loadSyncComments('mine','n/x',button,connectionLoad)");
 assert.equal(s.calls[0][0],'/api/social/sync/comments?account_id=mine&note_id=n%2Fx&offset=0');
 assert.match(s.sandbox.button.nextElementSibling.innerHTML,/&lt;script&gt;/);assert.equal(s.sandbox.button.disabled,true);
});
test('old comment response cannot write after account switch',async()=>{
 const s=setup();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);s.sandbox.button={nextElementSibling:{innerHTML:''}};
 const pending=s.eval("loadSyncComments('mine','n',button,connectionLoad)");s.sandbox.activeAccountId='other';resolve({items:[{content:'OLD',first_seen:1,last_seen:2}],next_offset:null});await pending;
 assert.equal(s.sandbox.button.nextElementSibling.innerHTML,'');
});
test('note case import requires confirmation and binds selected account and note',async()=>{
 const s=setup();await s.eval("importSyncCase('mine','n')");assert.equal(s.calls.length,0);
 s.sandbox.window.confirm=()=>true;await s.eval("importSyncCase('mine','n')");assert.equal(s.calls[0][0],'/api/social/sync/import-case');assert.equal(s.calls[0][1],'POST');assert.equal(s.calls[0][2].account_id,'mine');assert.equal(s.calls[0][2].note_id,'n');assert.equal(s.calls[0][2].permission_confirmed,true);
});
