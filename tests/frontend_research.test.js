'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const els=new Map(),calls=[];const element=id=>{if(!els.has(id))els.set(id,{innerHTML:'',value:'',disabled:false});return els.get(id);};
 const sandbox={pageInfo:{},crypto:require("node:crypto"),URL,currentPage:'research',activeAccountId:'mine',$:element,
 esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
 badge:(v)=>v,dateText:v=>v,document:{querySelectorAll:()=>[]},clearTimeout(){},setTimeout(){throw Error('unexpected polling');},error(){},api:async(...args)=>{calls.push(args);return [];}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/research.js','utf8'),sandbox);
 return {sandbox,element,calls,eval:code=>vm.runInContext(code,sandbox)};
}
test('research links reject executable schemes and escape markup',()=>{const s=setup();assert.equal(s.eval("researchSourceLink('javascript:alert(1)','<img>')"),'&lt;img&gt;');assert.doesNotMatch(s.eval("researchSourceLink('https://example.com','<img>')"),/<img>/);});
test('all terminal jobs expose export and no cancel',()=>{const s=setup();for(const status of ['done','partial','failed','cancelled','interrupted']){s.sandbox.job={id:'a/b',status,created_at:1};const html=s.eval('jobCards([job])');assert.match(html,/a%2Fb\/export/);assert.doesNotMatch(html,/data-cancel-research/);}});
test('running jobs expose cancellation but no premature export',()=>{const s=setup();s.sandbox.job={id:'run',status:'running',created_at:1};const html=s.eval('jobCards([job])');assert.match(html,/data-cancel-research/);assert.doesNotMatch(html,/\/export/);});
test('case cards preserve unknown interaction and untrusted title',()=>{const s=setup();s.sandbox.doc={id:'x',title:'<img>',version:1,metadata:{research_case:{content_kind:'lead',assessment:{known_interactions:null}}}};const html=s.eval('caseCards([doc])');assert.match(html,/未知/);assert.match(html,/不参与检索/);assert.doesNotMatch(html,/<img>/);});
test('departed research page does not trigger polling',async()=>{const s=setup();s.sandbox.currentPage='models';await s.eval("refreshResearchJobs('mine',0)");assert.equal(s.calls.length,0);});
test('stale account response cannot repaint the new account',async()=>{const s=setup();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);const pending=s.eval("refreshResearchJobs('mine',0)");s.sandbox.activeAccountId='other';resolve([{id:'OLD',status:'done',created_at:1}]);await pending;assert.equal(s.element('researchJobs').innerHTML,'');});

test('lost response retries reuse the same research key; changed scope gets a new key',()=>{const s=setup();const a=s.eval("researchRequest({account_id:'mine',queries:['防晒'],provider:'baidu'})"),b=s.eval("researchRequest({account_id:'mine',queries:['防晒'],provider:'baidu'})"),c=s.eval("researchRequest({account_id:'other',queries:['防晒'],provider:'baidu'})");assert.equal(a.key,b.key);assert.notEqual(b.key,c.key);});
test('research provider choices are concise and omit the local social connector',()=>{const s=setup();s.sandbox.settings={providers:[{id:'bing',name:'Bing',can_attempt:true,status_note:'可尝试，当前连接未核验'},{id:'baidu',name:'百度',can_attempt:false},{id:'xhs_local',name:'本机',can_attempt:true}]};const html=s.eval('researchProviderOptions(settings)');assert.match(html,/<option value="bing" >Bing<\/option>/);assert.match(html,/<option value="baidu" disabled>/);assert.doesNotMatch(html,/xhs_local|可尝试|核验/);});

test('search leads remain visible after all body reads fail, distinct from saved documents',()=>{
 const s=setup();s.sandbox.job={id:'failed',status:'failed',created_at:1,search_result_count:8,search_results:Array.from({length:8},(_,i)=>({query:'产品查询',title:'标题'+i,url:'https://example.com/'+i,snippet:'摘要'+i,body_read:false})),candidates:[],documents:[]};
 const html=s.eval('jobCards([job])');assert.match(html,/搜索返回 8 条结果/);assert.match(html,/已保存 0 份正文/);for(let i=0;i<8;i++)assert.ok(html.includes('https://example.com/'+i));assert.match(html,/程序未读到正文 · 仅搜索线索/);assert.doesNotMatch(html,/data-rag-candidate|加入知识库/);
});
test('legacy partial retention states missing URLs truthfully and escapes remote snippets',()=>{
 const s=setup();s.sandbox.job={search_result_count:8,search_result_retention:'legacy_partial',search_results:Array.from({length:5},(_,i)=>({title:'<img>',url:i?'https://example.com/'+i:'javascript:alert(1)',snippet:'<script>bad</script>',body_read:false}))};
 const html=s.eval('researchSearchResults(job)');assert.match(html,/搜索返回 8 条结果/);assert.match(html,/旧任务仅保留 5 条链接/);assert.match(html,/无法还原/);assert.doesNotMatch(html,/<script>|<img>|href="javascript/);assert.match(html,/&lt;script&gt;/);
});

test('rereading is withheld whenever body candidates or a confirmation already exist',()=>{
 const s=setup();s.sandbox.job={status:'failed',search_results:[{body_read:false}],candidates:[]};assert.equal(s.eval('researchCanRetryReads(job)'),true);
 s.sandbox.job.candidates=[{id:'body'}];assert.equal(s.eval('researchCanRetryReads(job)'),false);
 s.sandbox.job.candidates=[];s.sandbox.job.confirmation={};assert.equal(s.eval('researchCanRetryReads(job)'),false);
});
test('source HTTP failures identify the external page and never claim the API key failed',()=>{
 const s=setup();for(const [code,label] of [['SOURCE_HTTP_403','读取被拒绝（403）'],['SOURCE_HTTP_404','页面不存在（404）'],['SOURCE_HTTP_429','限流（429）'],['SOURCE_HTTP_ERROR','上游 HTTP 错误']]){
  s.sandbox.job={id:'j',status:'failed',created_at:1,error:code,reads:[{url:'https://example.com',error:code}]};const html=s.eval('jobCards([job])');assert.ok(html.includes(label));assert.doesNotMatch(html,/密钥|Key|重新登录/);
 }
});
test('background research prefers enabled Baidu and retains explicit provider choice',async()=>{
 const s=setup();s.element('researchProvider').value='bing';s.sandbox.api=async()=>({providers:[{id:'bing',can_attempt:true},{id:'baidu',can_attempt:true},{id:'wikipedia',can_attempt:true}]});
 await s.eval("refreshResearchProviders('mine',0)");assert.equal(s.element('researchProvider').value,'baidu');
 s.eval('researchProviderExplicit=true');s.element('researchProvider').value='wikipedia';await s.eval("refreshResearchProviders('mine',0)");assert.equal(s.element('researchProvider').value,'wikipedia');
});
