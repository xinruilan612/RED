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
test('research providers distinguish an attempt from a verified connection',()=>{const s=setup();s.sandbox.settings={providers:[{id:'bing',name:'Bing',can_attempt:true,status_note:'可尝试，当前连接未核验'},{id:'baidu',name:'百度',can_attempt:false,status_note:'请配置并启用'}]};const html=s.eval('researchProviderOptions(settings)');assert.match(html,/<option value="bing" >Bing · 可尝试，当前连接未核验/);assert.match(html,/<option value="baidu" disabled>/);assert.match(html,/需绑定本机账号；当前连接未核验/);assert.doesNotMatch(html,/已绑定本机账号/);});
