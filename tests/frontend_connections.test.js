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
test('old account response cannot overwrite newly selected account',async()=>{
 const s=setup();const resolves=[];s.sandbox.api=()=>new Promise(r=>resolves.push(r));const pending=s.eval('renderConnections()');s.sandbox.activeAccountId='other';resolves.forEach(r=>r({account_name:'OLD'}));await pending;assert.doesNotMatch(s.element('operationsContent').innerHTML,/OLD/);
});
test('missing metrics stay absent and zero stays zero',()=>{
 const s=setup();s.sandbox.data={account_name:'<script>',connection_status:'not_connected',reason:'no',fields:[{key:'views',label:'阅读'},{key:'likes',label:'点赞'}],local_records:{publication_count:0,metric_snapshot_count:1,latest_metric:{observed_at:'now',window:'24h',values:{views:null,likes:0}}}};
 const html=s.eval('connectionOverview(data)');assert.match(html,/未记录/);assert.match(html,/<td>0<\/td>/);assert.match(html,/尚未连接平台/);assert.doesNotMatch(html,/<script>/);
});
test('removed notes and comments section cannot expose historic text',()=>{
 const s=setup();s.sandbox.sync={status:'synced',interval_s:900,counts:{note:1,comment:0},latest_round:{notes:[{title:'PRIVATE',text:'SECRET',metrics:{}}]}};
 const html=s.eval('syncOverview(sync)');assert.doesNotMatch(html,/PRIVATE|SECRET|已同步笔记与评论|data-note-comments/);
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
test('reconnect renders only bounded PNG after owner-scoped login request',async()=>{
 const s=setup();s.sandbox.api=async(url,method,data)=>{s.calls.push([url,method,data]);if(url.endsWith('/login'))return {img:'data:image/png;base64,AA==',timeout:'4m0s'};if(url.includes('/notes'))return [];if(url.includes('/sync?'))return {bound:true,interval_s:900,counts:{note:0,comment:0}};return {};};
 await s.eval("reconnectSync('mine',connectionLoad)");assert.equal(s.calls[0][0],'/api/social/sync/login');assert.equal(s.calls[0][2].account_id,'mine');assert.match(s.element('syncLoginQRCode').innerHTML,/data:image\/png;base64/);assert.match(s.element('syncLoginQRCode').innerHTML,/原绑定/);
});

test('only public per-note metrics render and removed account metrics never render',()=>{
 const s=setup();s.sandbox.creator={status:'synced',source_method:'creator_browser_dom',account:{metrics:{views:9999,followers_gained:333}},notes:[{id:'public-id',visibility:'public',title:'公开标题',source_url:'https://example.com',metrics:{views:23,likes:0,comments:null}},{id:'private',visibility:'private',title:'PRIVATE',metrics:{views:777}},{id:'legacy',title:'LEGACY',metrics:{views:888}}]};
 const html=s.eval('creatorMetricsOverview(creator)');assert.match(html,/公开标题/);assert.match(html,/笔记 ID：public-id/);assert.match(html,/<td>23<\/td><td>0<\/td>/);assert.match(html,/<td>未知<\/td>/);
 assert.doesNotMatch(html,/9999|333|PRIVATE|LEGACY|777|888|账号周期汇总|净涨粉|新增关注|取消关注|主页访客|<th>曝光/);
});
test('failed read retains only public prior values with stale label',()=>{
 const s=setup();s.sandbox.failed={status:'failed',observed_at:200,error:'login lost'};s.sandbox.previous={status:'synced',observed_at:100,notes:[{id:'n',visibility:'public',metrics:{views:321}}]};
 const html=s.eval('creatorMetricsOverview(failed,previous)');assert.match(html,/旧数据 · 本轮读取失败/);assert.match(html,/<td>321<\/td>/);assert.match(html,/本轮失败尝试/);
});
test('unknown and abbreviated metrics are not converted to exact zero',()=>{
 const s=setup();s.sandbox.creator={status:'synced',notes:[{id:'n',visibility:'public',metrics:{views:null},metric_displays:{views:'2千'}}]};const html=s.eval('creatorMetricsOverview(creator)');assert.match(html,/2千（页面显示，精确值未知）/);assert.doesNotMatch(html,/2000|<td>0<\/td>/);
});
